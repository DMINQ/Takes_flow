"""SqlAlchemy TimelineRepository — persists/reads the analysis region map."""
from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.entities import TimelineRegion
from src.domain.enums import CutReason, RegionKind
from src.infrastructure.models import TimelineRegionModel


def _to_entity(row: TimelineRegionModel) -> TimelineRegion:
    return TimelineRegion(
        start=row.start,
        end=row.end,
        kind=RegionKind(row.kind),
        reason=CutReason(row.reason) if row.reason else None,
        take_group=row.take_group,
        text=row.text,
        speaker=row.speaker,
    )


class SqlTimelineRepository:
    """Satisfies domain.ports.repositories.TimelineRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def save_regions(self, job_id: str, media_id: str, regions: list[TimelineRegion]) -> None:
        # Replace any previous regions for this media (re-analysis overwrites).
        await self._s.execute(
            delete(TimelineRegionModel).where(TimelineRegionModel.media_id == media_id)
        )
        for r in regions:
            self._s.add(
                TimelineRegionModel(
                    media_id=media_id,
                    job_id=job_id,
                    start=r.start,
                    end=r.end,
                    kind=r.kind.value,
                    reason=r.reason.value if r.reason else None,
                    take_group=r.take_group,
                    text=r.text,
                    speaker=r.speaker,
                )
            )
        await self._s.flush()

    async def get_regions(self, media_id: str) -> list[TimelineRegion]:
        stmt = (
            select(TimelineRegionModel)
            .where(TimelineRegionModel.media_id == media_id)
            .order_by(TimelineRegionModel.start)
        )
        rows = (await self._s.execute(stmt)).scalars().all()
        return [_to_entity(r) for r in rows]
