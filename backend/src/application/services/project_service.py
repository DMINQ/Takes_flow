"""
ProjectService — read-side use-cases for listing projects and their media.

Projects are already created implicitly by UploadService (get_or_create on
init); this service only adds the read paths the "My projects" screen needs:
list all projects, list media within one, and each media's latest job status
so the frontend knows whether to route to Analysis (still running) or
Timeline (already has a completed run).
"""
from __future__ import annotations

from dataclasses import dataclass

from src.domain.entities import Job, Media, Project
from src.domain.errors import DomainError
from src.domain.ports.repositories import JobRepository, MediaRepository, ProjectRepository


class ProjectNotFoundError(DomainError):
    pass


@dataclass(slots=True)
class ProjectMediaEntry:
    media: Media
    latest_job: Job | None


class ProjectService:
    def __init__(
        self,
        projects: ProjectRepository,
        media: MediaRepository,
        jobs: JobRepository,
    ) -> None:
        self._projects = projects
        self._media = media
        self._jobs = jobs

    async def list_projects(self) -> list[tuple[Project, int]]:
        """Every project with its media count, newest first."""
        projects = await self._projects.list_all()
        result: list[tuple[Project, int]] = []
        for project in projects:
            media = await self._media.list_by_project(project.id)
            result.append((project, len(media)))
        return result

    async def list_media(self, project_id: str) -> list[ProjectMediaEntry]:
        """Every media in `project_id` with its latest job, oldest first."""
        project = await self._projects.get(project_id)
        if project is None:
            raise ProjectNotFoundError(f"No project '{project_id}'.")

        media_rows = await self._media.list_by_project(project_id)
        entries: list[ProjectMediaEntry] = []
        for media in media_rows:
            latest_job = await self._jobs.get_latest_for_media(media.id)
            entries.append(ProjectMediaEntry(media=media, latest_job=latest_job))
        return entries
