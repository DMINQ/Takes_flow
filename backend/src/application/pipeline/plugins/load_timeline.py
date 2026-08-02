"""
LoadTimelinePlugin — loads the previously-saved analysis region map for export.

Export jobs run after analysis already produced a TimelineRegion map (see
PersistTimelinePlugin in the ANALYSIS pipeline); this stage reloads it so
AssembleExportPlugin has something to work from without re-running
transcription/diarization/silence-detection.
"""
from __future__ import annotations

from src.application.pipeline.plugin import BasePlugin
from src.domain.dto import PipelineContext
from src.domain.errors import DomainError
from src.domain.ports.repositories import TimelineRepository


class LoadTimelinePlugin(BasePlugin):
    """Reads `context.regions` from the timeline repository."""

    name = "load_timeline"

    def __init__(self, timeline_repo: TimelineRepository) -> None:
        self._timeline = timeline_repo

    async def run(self, context: PipelineContext) -> PipelineContext:
        regions = await self._timeline.get_regions(context.media_id)
        if not regions:
            raise DomainError(
                f"No timeline regions found for media '{context.media_id}'. "
                "Run an ANALYSIS job before exporting."
            )
        context.regions = regions
        return context
