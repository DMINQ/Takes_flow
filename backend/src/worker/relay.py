"""
Outbox relay — `python -m src.worker.relay`.

Polls the `outbox` table for PENDING events and publishes them to the broker,
marking them PUBLISHED on success (at-least-once delivery). This decouples the
DB write (job + event in one transaction) from broker availability.

Failed publishes stay PENDING (retried on the next poll) until they exhaust
`OutboxSettings.max_publish_attempts`, at which point they become terminally
FAILED and `fetch_pending` stops returning them — this bounds retries without
losing events (Redis Streams don't need consumers to be up for publishes to
land; Step 4 adds the consumer side).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Protocol

from faststream.redis import RedisBroker

from src.infrastructure.db import AsyncSessionLocal
from src.infrastructure.repositories.outbox import SqlOutboxRepository
from src.settings.config import broker_settings, core_settings, outbox_settings

logging.basicConfig(
    level=core_settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("takeflow.relay")


class Publisher(Protocol):
    """The only broker capability the relay needs — lets tests use a fake."""

    async def publish(self, message: dict, *, stream: str) -> object: ...


async def _publish_pending_batch(broker: Publisher) -> None:
    async with AsyncSessionLocal() as session:
        outbox = SqlOutboxRepository(session)
        events = await outbox.fetch_pending(
            outbox_settings.batch_size, outbox_settings.max_publish_attempts
        )
        for event in events:
            try:
                published = False
                try:
                    await broker.publish(event["payload"], stream=event["stream"])
                    published = True
                except Exception:
                    logger.exception("Failed to publish outbox event %s", event["id"])

                if published:
                    await outbox.mark_published(event["id"])
                else:
                    await outbox.mark_failed(
                        event["id"],
                        event["attempts"] + 1,
                        outbox_settings.max_publish_attempts,
                    )
            except Exception:
                # A DB error on the mark call itself must not lose progress
                # already made on other events in this batch's commit below.
                logger.exception("Failed to record outcome for outbox event %s", event["id"])
        if events:
            await session.commit()


async def main() -> None:
    logger.info("Outbox relay starting (poll=%.1fs)", outbox_settings.poll_interval_seconds)
    broker = RedisBroker(broker_settings.url)
    await broker.connect()
    try:
        while True:
            await _publish_pending_batch(broker)
            await asyncio.sleep(outbox_settings.poll_interval_seconds)
    finally:
        await broker.close()


if __name__ == "__main__":
    asyncio.run(main())
