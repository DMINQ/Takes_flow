"""
MasterPlugin — runs the mastering chain on the assembled export audio.

Wraps AudioEnginePort.master (noise gate -> highpass -> EQ -> compressor ->
LUFS normalize). Runs after AssembleExportPlugin so mastering processes the
final cut, not the raw source (processing before assembly would waste time
mastering audio spans that get thrown away).
"""
from __future__ import annotations

from pathlib import Path

from src.application.pipeline.plugin import BasePlugin
from src.domain.dto import PipelineContext
from src.domain.ports.services import AudioEnginePort


class MasterPlugin(BasePlugin):
    """Applies the mastering chain to `context.working_audio_path`."""

    name = "master"

    def __init__(self, audio_engine: AudioEnginePort) -> None:
        self._audio_engine = audio_engine

    async def run(self, context: PipelineContext) -> PipelineContext:
        source_path = Path(context.working_audio_path or context.input_path)
        mastered_path = source_path.with_name(f"{source_path.stem}.mastered{source_path.suffix}")
        result = self._audio_engine.master(source_path, mastered_path)

        context.working_audio_path = str(result)
        context.output_path = str(result)
        context.temp_files.append(str(result))
        return context
