"""
Timeline route — the region map for a media file.

Populated by the analysis pipeline (Phase 2). Returns whatever regions have been
saved; an empty list means analysis hasn't produced a map yet.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from src.api.deps import timeline_service
from src.api.schemas.timeline import RegionOut, TimelineResponse
from src.application.services.timeline_service import TimelineService

router = APIRouter(prefix="/timeline", tags=["timeline"])


@router.get("/{media_id}", response_model=TimelineResponse, summary="Get the timeline region map")
async def get_timeline(
    media_id: str,
    service: TimelineService = Depends(timeline_service),
) -> TimelineResponse:
    regions = await service.get_regions(media_id)
    return TimelineResponse(
        media_id=media_id,
        regions=[
            RegionOut(
                start=r.start, end=r.end, kind=r.kind, reason=r.reason,
                take_group=r.take_group, text=r.text, speaker=r.speaker,
            )
            for r in regions
        ],
    )
