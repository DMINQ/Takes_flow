"""HTTP schemas for the timeline endpoint — the region map the frontend renders."""
from __future__ import annotations

from pydantic import BaseModel

from src.domain.enums import CutReason, RegionKind


class RegionOut(BaseModel):
    start: float
    end: float
    kind: RegionKind                # keep(green) | auto_cut(red) | review(yellow)
    reason: CutReason | None = None
    take_group: str | None = None
    text: str | None = None
    speaker: str | None = None


class TimelineResponse(BaseModel):
    media_id: str
    regions: list[RegionOut]
