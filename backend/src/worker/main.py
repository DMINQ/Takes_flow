"""
Worker entry point — `python -m src.worker.main`.

Separate process from the API. It preloads heavy models once, then consumes
analysis/export jobs from the broker (FastStream) and runs the pipelines.

Step 4 fills in the FastStream subscribers + processors. For now this is a
runnable skeleton: it warms the transcriber (so the model volume is populated)
and idles, proving the worker service boots on the shared image.
"""
from __future__ import annotations

import asyncio
import logging

from src.application.services.upload_service import UploadService
from src.infrastructure.db import AsyncSessionLocal
from src.infrastructure.repositories.media import SqlMediaRepository
from src.infrastructure.repositories.upload_session import SqlUploadSessionRepository
from src.settings.config import core_settings, storage_settings, transcription_settings
from src.settings.providers import get_storage, get_transcriber

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

    # TODO(step 4): start FastStream subscribers for analysis/export streams.
    logger.info("Worker idle — awaiting job subscribers (wired in step 4).")
    stop = asyncio.Event()
    try:
        await stop.wait()
    finally:
        reap_task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
