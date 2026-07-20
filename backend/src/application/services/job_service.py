"""
JobService — create and query background jobs.

`create` is the transactional-outbox producer: it inserts the Job and its
OutboxEvent in a single transaction, then commits. The event is published to the
broker later by the relay (step 3), so a crash between commit and publish can't
lose the job — the row is durably in the outbox.
"""
from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.entities import Job
from src.domain.enums import JobKind, JobStatus
from src.domain.errors import MediaNotFoundError
from src.domain.ports.repositories import JobRepository, MediaRepository, OutboxRepository
from src.settings.config import broker_settings


class JobService:
    def __init__(
        self,
        session: AsyncSession,
        job_repo: JobRepository,
        media_repo: MediaRepository,
        outbox_repo: OutboxRepository,
    ) -> None:
        self._session = session
        self._jobs = job_repo
        self._media = media_repo
        self._outbox = outbox_repo

    def _stream_for(self, kind: JobKind) -> str:
        return (
            broker_settings.analysis_stream
            if kind is JobKind.ANALYSIS
            else broker_settings.export_stream
        )

    async def create(self, media_id: str, kind: JobKind, params: dict | None = None) -> Job:
        """Validate media, persist Job + OutboxEvent atomically, return the job."""
        media = await self._media.get(media_id)
        if media is None:
            raise MediaNotFoundError(f"No media found for id '{media_id}'.")

        job = Job(id=uuid.uuid4().hex, media_id=media_id, kind=kind, status=JobStatus.PENDING)
        await self._jobs.add(job)

        # The event carries only ids/params; the worker reloads the row it needs.
        await self._outbox.add(
            stream=self._stream_for(kind),
            payload={
                "job_id": job.id,
                "media_id": media_id,
                "kind": kind.value,
                "params": params or {},
            },
        )

        # One commit -> job and outbox event land together.
        await self._session.commit()
        return job

    async def get(self, job_id: str) -> Job | None:
        return await self._jobs.get(job_id)
