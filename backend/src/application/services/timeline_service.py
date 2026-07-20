"""TimelineService — read the analysis region map for a media file."""
from __future__ import annotations

from src.domain.entities import TimelineRegion
from src.domain.ports.repositories import TimelineRepository


class TimelineService:
    def __init__(self, timeline_repo: TimelineRepository) -> None:
        self._timeline = timeline_repo

    async def get_regions(self, media_id: str) -> list[TimelineRegion]:
        return await self._timeline.get_regions(media_id)
