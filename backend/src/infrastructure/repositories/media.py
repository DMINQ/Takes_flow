"""SqlAlchemy MediaRepository — maps MediaModel <-> Media entity."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.entities import Media
from src.infrastructure.models import MediaModel


def _to_entity(row: MediaModel) -> Media:
    return Media(
        id=row.id,
        project_id=row.project_id,
        filename=row.filename,
        storage_key=row.storage_key,
        size_bytes=row.size_bytes,
        content_type=row.content_type,
        duration=row.duration,
        checksum=row.checksum,
        created_at=row.created_at,
    )


class SqlMediaRepository:
    """Satisfies domain.ports.repositories.MediaRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, media: Media) -> Media:
        row = MediaModel(
            id=media.id,
            project_id=media.project_id,
            filename=media.filename,
            storage_key=media.storage_key,
            size_bytes=media.size_bytes,
            content_type=media.content_type,
            duration=media.duration,
            checksum=media.checksum,
        )
        self._s.add(row)
        await self._s.flush()  # populate server defaults (created_at) without committing
        return _to_entity(row)

    async def get(self, media_id: str) -> Media | None:
        row = await self._s.get(MediaModel, media_id)
        return _to_entity(row) if row else None

    async def list_by_project(self, project_id: str) -> list[Media]:
        stmt = (
            select(MediaModel)
            .where(MediaModel.project_id == project_id)
            .order_by(MediaModel.created_at.asc())
        )
        rows = (await self._s.execute(stmt)).scalars().all()
        return [_to_entity(row) for row in rows]
