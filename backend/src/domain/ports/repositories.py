"""
Repository ports — data-access interfaces the application layer depends on.

Concrete SQLAlchemy implementations live in infrastructure/repositories/. Both
the API and the worker use the same repositories, so data access is defined once.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from src.domain.entities import Job, Media, TimelineRegion
from src.domain.enums import JobStatus


@runtime_checkable
class MediaRepository(Protocol):
    async def add(self, media: Media) -> Media: ...
    async def get(self, media_id: str) -> Media | None: ...


@runtime_checkable
class JobRepository(Protocol):
    async def add(self, job: Job) -> Job: ...
    async def get(self, job_id: str) -> Job | None: ...
    async def claim(self, job_id: str) -> Job | None:
        """Atomically move a PENDING/QUEUED job to PROCESSING (SELECT ... FOR UPDATE)."""
        ...
    async def set_status(self, job_id: str, status: JobStatus, error: str | None = None) -> None: ...
    async def set_progress(self, job_id: str, progress: float) -> None: ...


@runtime_checkable
class TimelineRepository(Protocol):
    async def save_regions(self, job_id: str, media_id: str, regions: list[TimelineRegion]) -> None: ...
    async def get_regions(self, media_id: str) -> list[TimelineRegion]: ...


@runtime_checkable
class OutboxRepository(Protocol):
    """Transactional outbox: events written in the same tx as the job."""

    async def add(self, stream: str, payload: dict) -> None: ...
    async def fetch_pending(self, limit: int) -> list[dict]:
        """Return pending events (each dict includes its id, stream, payload)."""
        ...
    async def mark_published(self, event_id: str) -> None: ...
    async def mark_failed(self, event_id: str, attempts: int) -> None: ...
