"""
Outbox relay — `python -m src.worker.relay`.

Polls the `outbox` table for PENDING events and publishes them to the broker,
marking them PUBLISHED on success (at-least-once delivery). This decouples the
DB write (job + event in one transaction) from broker availability.

Step 3 fills in the actual publish via FastStream + OutboxRepository. For now
this is a runnable skeleton proving the relay service boots on the shared image.
"""
from __future__ import annotations

import asyncio
import logging

from src.settings.config import core_settings, outbox_settings

logging.basicConfig(
    level=core_settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("takeflow.relay")


async def main() -> None:
    logger.info("Outbox relay starting (poll=%.1fs)", outbox_settings.poll_interval_seconds)
    # TODO(step 3): fetch_pending -> publish to FastStream -> mark_published.
    while True:
        await asyncio.sleep(outbox_settings.poll_interval_seconds)


if __name__ == "__main__":
    asyncio.run(main())
