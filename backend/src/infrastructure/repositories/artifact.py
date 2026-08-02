"""SqlAlchemy ArtifactRepository — maps ArtifactModel <-> Artifact entity."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.entities import Artifact
from src.domain.enums import ArtifactKind
from src.infrastructure.models import ArtifactModel


def _to_entity(row: ArtifactModel) -> Artifact:
    return Artifact(
        id=row.id,
        media_id=row.media_id,
        job_id=row.job_id,
        kind=ArtifactKind(row.kind),
        storage_key=row.storage_key,
        content_type=row.content_type,
        metadata=row.artifact_metadata or {},
        created_at=row.created_at,
    )


class SqlArtifactRepository:
    """Satisfies domain.ports.repositories.ArtifactRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, artifact: Artifact) -> Artifact:
        row = ArtifactModel(
            id=artifact.id,
            media_id=artifact.media_id,
            job_id=artifact.job_id,
            kind=artifact.kind.value,
            storage_key=artifact.storage_key,
            content_type=artifact.content_type,
            artifact_metadata=artifact.metadata,
        )
        self._s.add(row)
        await self._s.flush()
        return _to_entity(row)

    async def get(self, media_id: str, kind: ArtifactKind) -> Artifact | None:
        stmt = (
            select(ArtifactModel)
            .where(ArtifactModel.media_id == media_id, ArtifactModel.kind == kind.value)
            .order_by(ArtifactModel.created_at.desc())
            .limit(1)
        )
        row = (await self._s.execute(stmt)).scalars().first()
        return _to_entity(row) if row else None
