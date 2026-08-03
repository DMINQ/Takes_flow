"""
TranscribePlugin — word-level transcription via TranscriberPort.

Blocking (CPU/GPU-bound), so it's offloaded to a thread — same pattern as the
synchronous /media/transcribe route. Populates words/detected_language on the
context; a later stage groups words into Phrases for bad-take detection.
"""
from __future__ import annotations

from pathlib import Path

from anyio import to_thread

from src.application.pipeline.plugin import BasePlugin
from src.domain.dto import PipelineContext
from src.domain.ports.services import TranscriberPort


class TranscribePlugin(BasePlugin):
    """Runs the configured transcriber over the (preprocessed) working audio."""

    name = "transcribe"
    progress_weight = 6.0

    def __init__(self, transcriber: TranscriberPort) -> None:
        self._transcriber = transcriber

    async def run(self, context: PipelineContext) -> PipelineContext:
        audio_path = context.working_audio_path or context.input_path
        words, language, language_probability, duration = await to_thread.run_sync(
            self._transcriber.transcribe, Path(audio_path), context.language
        )

        context.words = words
        context.detected_language = language
        context.language_probability = language_probability
        if context.duration is None:
            context.duration = duration
        return context
