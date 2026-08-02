"""SqlAlchemy UploadSessionRepository — maps UploadSessionModel <-> UploadSession."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.entities import UploadSession
from src.domain.enums import UploadMode, UploadStatus
from src.infrastructure.models import UploadSessionModel


def _to_entity(row: UploadSessionModel) -> UploadSession:
    return UploadSession(
        id=row.id,
        project_id=row.project_id,
        storage_key=row.storage_key,
        filename=row.filename,
        declared_size=row.declared_size,
        mode=UploadMode(row.mode),
        status=UploadStatus(row.status),
        upload_id=row.upload_id,
        part_size=row.part_size,
        part_count=row.part_count,
        content_type=row.content_type,
        media_id=row.media_id,
        expires_at=row.expires_at,
        created_at=row.created_at,
    )


class SqlUploadSessionRepository:
    """Satisfies domain.ports.repositories.UploadSessionRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, session: UploadSession) -> UploadSession:
        row = UploadSessionModel(
            id=session.id,
            project_id=session.project_id,
            storage_key=session.storage_key,
            filename=session.filename,
            declared_size=session.declared_size,
            mode=session.mode.value,
            status=session.status.value,
            upload_id=session.upload_id,
            part_size=session.part_size,
            part_count=session.part_count,
            content_type=session.content_type,
            media_id=session.media_id,
            expires_at=session.expires_at,
        )
        self._s.add(row)
        await self._s.flush()
        return _to_entity(row)

    async def get(self, session_id: str) -> UploadSession | None:
        row = await self._s.get(UploadSessionModel, session_id)
        return _to_entity(row) if row else None

    async def set_status(
        self, session_id: str, status: UploadStatus, *, media_id: str | None = None
    ) -> None:
        values: dict[str, object] = {"status": status.value}
        if media_id is not None:
            values["media_id"] = media_id
        await self._s.execute(
            update(UploadSessionModel).where(UploadSessionModel.id == session_id).values(**values)
        )

    async def fetch_stale(self, limit: int) -> list[UploadSession]:
        """
        Expired INITIATED sessions, locked so concurrent sweepers don't collide.

        SKIP LOCKED mirrors the job/outbox claim pattern: several API or worker
        instances can sweep at once without fighting over the same rows.
        """
        stmt = (
            select(UploadSessionModel)
            .where(
                UploadSessionModel.status == UploadStatus.INITIATED.value,
                UploadSessionModel.expires_at.is_not(None),
                UploadSessionModel.expires_at < datetime.now(timezone.utc),
            )
            .order_by(UploadSessionModel.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        rows = (await self._s.execute(stmt)).scalars().all()
        return [_to_entity(row) for row in rows]
