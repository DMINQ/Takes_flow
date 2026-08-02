"""
Worker entry point — `python -m src.worker.main`.

Separate process from the API. It preloads heavy models once, then consumes
analysis/export jobs from the broker (FastStream) and runs the pipelines.

Step 4 wires the FastStream subscribers: one per stream (analysis/export),
both delegating to `worker.processor.process_job_event`, which claims the job
and runs it through the pipeline `Runner`. Delivery is at-least-once (Redis
Streams + consumer group), and `process_job_event` never raises, so a message
is acked once handled regardless of whether the job itself succeeded or failed.
"""
from __future__ import annotations

import asyncio
import logging
import uuid

from faststream import FastStream
from faststream.redis import RedisBroker
from faststream.redis.schemas import StreamSub

from src.application.services.upload_service import UploadService
from src.infrastructure.db import AsyncSessionLocal
from src.infrastructure.repositories.media import SqlMediaRepository
from src.infrastructure.repositories.upload_session import SqlUploadSessionRepository
from src.settings.config import broker_settings, core_settings, storage_settings, transcription_settings
from src.settings.providers import get_storage, get_transcriber
from src.worker.processor import process_job_event

logging.basicConfig(
    level=core_settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("takeflow.worker")

# How often to sweep for upload sessions whose tickets expired without
# completion. Independent of `presign_ttl_seconds` — this is a poll cadence,
# not the TTL itself, so a slow sweep only delays cleanup, not correctness.
_REAP_INTERVAL_SECONDS = 300


async def _reap_stale_uploads_loop() -> None:
    """
    Periodically abort upload sessions left in INITIATED past their expiry.

    Without this, multipart parts never uploaded to completion linger in the
    bucket and are billed indefinitely (see UploadService.reap_stale). Runs
    forever until the worker process is stopped; failures are logged and
    retried on the next tick rather than crashing the worker.
    """
    storage = get_storage()
    while True:
        try:
            async with AsyncSessionLocal() as session:
                service = UploadService(
                    session,
                    SqlUploadSessionRepository(session),
                    SqlMediaRepository(session),
                    storage,
                    core_settings,
                    storage_settings,
                )
                reaped = await service.reap_stale()
                if reaped:
                    logger.info("Upload reap: aborted %d stale session(s)", reaped)
        except Exception:
            logger.exception("Upload reap sweep failed; will retry next tick")
        await asyncio.sleep(_REAP_INTERVAL_SECONDS)


def _build_broker() -> RedisBroker:
    """One RedisBroker with a subscriber per stream, both routed to the same processor.

    A shared consumer group means multiple worker replicas load-balance the
    same stream instead of each replica processing every message. Each
    replica still needs its own unique `consumer` name within that group
    (Redis' `XREADGROUP` identifies readers by it) — `StreamSub` requires
    `group` and `consumer` to be set together.
    """
    broker = RedisBroker(broker_settings.url)
    consumer_name = f"worker-{uuid.uuid4().hex[:8]}"

    @broker.subscriber(
        stream=StreamSub(
            broker_settings.analysis_stream,
            group=broker_settings.consumer_group,
            consumer=consumer_name,
        ),
    )
    async def _on_analysis(payload: dict) -> None:
        await process_job_event(payload)

    @broker.subscriber(
        stream=StreamSub(
            broker_settings.export_stream,
            group=broker_settings.consumer_group,
            consumer=consumer_name,
        ),
    )
    async def _on_export(payload: dict) -> None:
        await process_job_event(payload)

    return broker


async def main() -> None:
    storage_settings.require_secure_presign_secret(core_settings.debug)
    logger.info("Worker starting (transcriber=%s)", transcription_settings.provider.value)

    # Preload the model once at startup (skip for remote provider).
    transcriber = get_transcriber()
    warmup = getattr(transcriber, "warmup", None)
    if callable(warmup):
        logger.info("Warming up transcriber…")
        await asyncio.to_thread(warmup)
        logger.info("Transcriber ready.")

    reap_task = asyncio.create_task(_reap_stale_uploads_loop())

    broker = _build_broker()
    app = FastStream(broker)
    logger.info(
        "Worker subscribing to '%s' / '%s' (group=%s)",
        broker_settings.analysis_stream,
        broker_settings.export_stream,
        broker_settings.consumer_group,
    )
    try:
        await app.run()
    finally:
        reap_task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
