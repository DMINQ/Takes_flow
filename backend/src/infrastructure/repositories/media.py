"""SqlAlchemy MediaRepository — maps MediaModel <-> Media entity."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.entities import Media
from src.infrastructure.models import MediaModel


def _to_entity(row: MediaModel) -> Media:
    return Media(
        id=row.id,
        filename=row.filename,
        path=row.path,
        size_bytes=row.size_bytes,
        content_type=row.content_type,
        duration=row.duration,
        created_at=row.created_at,
    )


class SqlMediaRepository:
    """Satisfies domain.ports.repositories.MediaRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, media: Media) -> Media:
        row = MediaModel(
            id=media.id,
            filename=media.filename,
            path=media.path,
            size_bytes=media.size_bytes,
            content_type=media.content_type,
            duration=media.duration,
        )
        self._s.add(row)
        await self._s.flush()  # populate server defaults (created_at) without committing
        return _to_entity(row)

    async def get(self, media_id: str) -> Media | None:
        row = await self._s.get(MediaModel, media_id)
        return _to_entity(row) if row else None
