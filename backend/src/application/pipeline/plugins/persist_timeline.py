"""
PersistTimelinePlugin — saves the analysis result (regions) to the timeline repo.

Terminal stage of the ANALYSIS pipeline. Step 5/6 populate `context.regions`
(silence/bad-take detection); today it persists whatever is there (possibly
empty) so the end-to-end path is exercised before those detectors land.
"""
from __future__ import annotations

from src.application.pipeline.plugin import BasePlugin
from src.domain.dto import PipelineContext
from src.domain.ports.repositories import TimelineRepository


class PersistTimelinePlugin(BasePlugin):
    """Writes `context.regions` to the timeline repository, keyed by media."""

    name = "persist_timeline"

    def __init__(self, timeline_repo: TimelineRepository) -> None:
        self._timeline = timeline_repo

    async def run(self, context: PipelineContext) -> PipelineContext:
        await self._timeline.save_regions(context.job_id, context.media_id, context.regions)
        return context
