"""
AssembleExportPlugin — builds the final cut of the source audio for export.

Resolves the export ranges from `context.regions` + the user's take choices
(`context.export_selection`), then assembles them via AudioEnginePort.assemble.
Runs on the denoised working copy DenoisePlugin just produced (not the raw
upload) so the exported file reflects the same noise reduction the ANALYSIS
pipeline applied, while still re-deriving ranges fresh here rather than
reusing ANALYSIS's own CUT_AUDIO artifact (that one was only ever a scratch
copy for transcription, built with a different padding/selection).
"""
from __future__ import annotations

from pathlib import Path

from src.application.pipeline.export_selection import parse_export_selection, resolve_export_ranges
from src.application.pipeline.plugin import BasePlugin
from src.domain.dto import PipelineContext
from src.domain.errors import DomainError
from src.domain.ports.services import AudioEnginePort


class AssembleExportPlugin(BasePlugin):
    """Assembles the KEEP (minus user-dropped REVIEW) ranges into one file."""

    name = "assemble_export"
    progress_weight = 2.0

    def __init__(self, audio_engine: AudioEnginePort) -> None:
        self._audio_engine = audio_engine

    async def run(self, context: PipelineContext) -> PipelineContext:
        cut_regions = parse_export_selection(context.export_selection)
        ranges = resolve_export_ranges(context.regions, cut_review_regions=cut_regions)
        if not ranges:
            raise DomainError("Export selection leaves nothing to keep — nothing to assemble.")

        source_path = Path(context.working_audio_path or context.input_path)
        assembled_path = source_path.with_name(f"{source_path.stem}.assembled{source_path.suffix}")
        result = self._audio_engine.assemble(source_path, ranges, assembled_path)

        context.working_audio_path = str(result)
        context.temp_files.append(str(result))
        return context
