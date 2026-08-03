"""
Repository ports — data-access interfaces the application layer depends on.

Concrete SQLAlchemy implementations live in infrastructure/repositories/. Both
the API and the worker use the same repositories, so data access is defined once.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from src.domain.entities import Artifact, Job, Media, Project, TimelineRegion, UploadSession
from src.domain.enums import ArtifactKind, JobStatus, UploadStatus


@runtime_checkable
class ProjectRepository(Protocol):
    async def add(self, project: Project) -> Project: ...
    async def get(self, project_id: str) -> Project | None: ...
    async def get_or_create(self, project_id: str, name: str) -> Project:
        """Idempotently ensure a project row exists (uploads reference it eagerly)."""
        ...
    async def list_all(self) -> list[Project]:
        """All projects, newest first — backs GET /projects."""
        ...


@runtime_checkable
class MediaRepository(Protocol):
    async def add(self, media: Media) -> Media: ...
    async def get(self, media_id: str) -> Media | None: ...
    async def list_by_project(self, project_id: str) -> list[Media]:
        """Every Media row in `project_id`, oldest first — backs GET /projects/{id}/media."""
        ...


@runtime_checkable
class ArtifactRepository(Protocol):
    """Tracks derived, storage-persisted outputs of each pipeline stage."""

    async def add(self, artifact: Artifact) -> Artifact: ...
    async def get(self, media_id: str, kind: ArtifactKind) -> Artifact | None:
        """Latest artifact of `kind` for `media_id`, or None if the stage never ran."""
        ...


@runtime_checkable
class UploadSessionRepository(Protocol):
    """Tracks client-direct uploads the API mediates but never carries."""

    async def add(self, session: UploadSession) -> UploadSession: ...
    async def get(self, session_id: str) -> UploadSession | None: ...
    async def set_status(
        self, session_id: str, status: UploadStatus, *, media_id: str | None = None
    ) -> None: ...
    async def fetch_stale(self, limit: int) -> list[UploadSession]:
        """INITIATED sessions past their expiry — the sweeper aborts these."""
        ...


@runtime_checkable
class JobRepository(Protocol):
    async def add(self, job: Job) -> Job: ...
    async def get(self, job_id: str) -> Job | None: ...
    async def claim(self, job_id: str) -> Job | None:
        """Atomically move a PENDING/QUEUED job to PROCESSING (SELECT ... FOR UPDATE)."""
        ...
    async def set_status(self, job_id: str, status: JobStatus, error: str | None = None) -> None: ...
    async def set_progress(self, job_id: str, progress: float, stage: str | None = None) -> None: ...
    async def get_latest_for_media(self, media_id: str) -> Job | None:
        """Most recently created job for `media_id`, or None if it never had one."""
        ...


@runtime_checkable
class TimelineRepository(Protocol):
    async def save_regions(self, job_id: str, media_id: str, regions: list[TimelineRegion]) -> None: ...
    async def get_regions(self, media_id: str) -> list[TimelineRegion]: ...


@runtime_checkable
class OutboxRepository(Protocol):
    """Transactional outbox: events written in the same tx as the job."""

    async def add(self, stream: str, payload: dict) -> None: ...
    async def fetch_pending(self, limit: int, max_attempts: int) -> list[dict]:
        """Return pending events (each dict includes its id, stream, payload).

        Events with `attempts >= max_attempts` are excluded so a poisoned
        event can't block the relay forever once it's exhausted retries.
        """
        ...
    async def mark_published(self, event_id: str) -> None: ...
    async def mark_failed(self, event_id: str, attempts: int, max_attempts: int) -> None:
        """Record a failed publish attempt.

        Stays `pending` (retryable on the next poll) while `attempts <
        max_attempts`; becomes terminally `failed` once attempts are
        exhausted, so `fetch_pending` stops returning it.
        """
        ...
