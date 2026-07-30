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

from src.settings.config import core_settings, storage_settings, transcription_settings
from src.settings.providers import get_transcriber

logging.basicConfig(
    level=core_settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("takeflow.worker")


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

    # TODO(step 4): start FastStream subscribers for analysis/export streams.
    logger.info("Worker idle — awaiting job subscribers (wired in step 4).")
    stop = asyncio.Event()
    await stop.wait()


if __name__ == "__main__":
    asyncio.run(main())
