"""SqlAlchemy ProjectRepository — maps ProjectModel <-> Project entity."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.entities import Project
from src.infrastructure.models import ProjectModel


def _to_entity(row: ProjectModel) -> Project:
    return Project(id=row.id, name=row.name, created_at=row.created_at)


class SqlProjectRepository:
    """Satisfies domain.ports.repositories.ProjectRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, project: Project) -> Project:
        row = ProjectModel(id=project.id, name=project.name)
        self._s.add(row)
        await self._s.flush()
        return _to_entity(row)

    async def get(self, project_id: str) -> Project | None:
        row = await self._s.get(ProjectModel, project_id)
        return _to_entity(row) if row else None

    async def get_or_create(self, project_id: str, name: str) -> Project:
        existing = await self.get(project_id)
        if existing is not None:
            return existing
        row = ProjectModel(id=project_id, name=name)
        self._s.add(row)
        await self._s.flush()
        return _to_entity(row)
