"""
FastAPI dependency providers.

Routers depend on services (which depend on ports), never on concrete adapters.
Repositories are session-scoped: one AsyncSession per request, injected via
`get_db`. Concrete adapters (storage/transcriber) come from settings/providers.py.
"""
from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.job_service import JobService
from src.application.services.media_service import MediaService
from src.application.services.project_service import ProjectService
from src.application.services.timeline_service import TimelineService
from src.application.services.upload_service import UploadService
from src.domain.ports.services import StoragePort, TranscriberPort
from src.infrastructure.db import get_db
from src.infrastructure.repositories.artifact import SqlArtifactRepository
from src.infrastructure.repositories.job import SqlJobRepository
from src.infrastructure.repositories.media import SqlMediaRepository
from src.infrastructure.repositories.outbox import SqlOutboxRepository
from src.infrastructure.repositories.project import SqlProjectRepository
from src.infrastructure.repositories.timeline import SqlTimelineRepository
from src.infrastructure.repositories.upload_session import SqlUploadSessionRepository
from src.settings.config import core_settings, storage_settings
from src.settings.providers import get_storage, get_transcriber


# --- Adapter providers (process-wide singletons via settings.providers) ---
def storage_provider() -> StoragePort:
    return get_storage()


def transcriber_provider() -> TranscriberPort:
    return get_transcriber()


# --- Service providers (request-scoped; build repos over the request's session) ---
def media_service(
    session: AsyncSession = Depends(get_db),
    storage: StoragePort = Depends(storage_provider),
) -> MediaService:
    return MediaService(session, SqlMediaRepository(session), storage, SqlArtifactRepository(session))


def job_service(session: AsyncSession = Depends(get_db)) -> JobService:
    return JobService(
        session,
        SqlJobRepository(session),
        SqlMediaRepository(session),
        SqlOutboxRepository(session),
    )


def timeline_service(session: AsyncSession = Depends(get_db)) -> TimelineService:
    return TimelineService(SqlTimelineRepository(session))


def project_service(session: AsyncSession = Depends(get_db)) -> ProjectService:
    return ProjectService(
        SqlProjectRepository(session),
        SqlMediaRepository(session),
        SqlJobRepository(session),
    )


def upload_service(
    session: AsyncSession = Depends(get_db),
    storage: StoragePort = Depends(storage_provider),
) -> UploadService:
    return UploadService(
        session,
        SqlUploadSessionRepository(session),
        SqlMediaRepository(session),
        storage,
        core_settings,
        storage_settings,
        SqlProjectRepository(session),
    )
