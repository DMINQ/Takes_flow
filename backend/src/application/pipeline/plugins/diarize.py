"""
DiarizePlugin — assigns speaker labels via DiarizerPort.

Runs after transcription so a later stage can attach `speaker` to each Word if
the diarizer output is refined into per-word ranges. For now it just populates
`context.speakers`; the stub adapter returns a single speaker.
"""
from __future__ import annotations

from pathlib import Path

from src.application.pipeline.plugin import BasePlugin
from src.domain.dto import PipelineContext
from src.domain.ports.services import DiarizerPort


class DiarizePlugin(BasePlugin):
    """Detects speakers over the working audio."""

    name = "diarize"

    def __init__(self, diarizer: DiarizerPort) -> None:
        self._diarizer = diarizer

    async def run(self, context: PipelineContext) -> PipelineContext:
        audio_path = context.working_audio_path or context.input_path
        context.speakers = self._diarizer.diarize(Path(audio_path))
        return context
