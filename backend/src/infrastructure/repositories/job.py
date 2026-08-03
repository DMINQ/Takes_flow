"""
SqlAlchemy JobRepository — maps JobModel <-> Job entity.

`claim` is the concurrency-safe transition a worker uses to take a job: it locks
the row (`SELECT ... FOR UPDATE SKIP LOCKED`) so two workers never grab the same
job, and only claims jobs that are still PENDING/QUEUED.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.entities import Job
from src.domain.enums import JobKind, JobStatus
from src.infrastructure.models import JobModel


def _to_entity(row: JobModel) -> Job:
    return Job(
        id=row.id,
        media_id=row.media_id,
        kind=JobKind(row.kind),
        status=JobStatus(row.status),
        progress=row.progress,
        stage=row.stage,
        error=row.error,
        created_at=row.created_at,
    )


class SqlJobRepository:
    """Satisfies domain.ports.repositories.JobRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, job: Job) -> Job:
        row = JobModel(
            id=job.id,
            media_id=job.media_id,
            kind=job.kind.value,
            status=job.status.value,
            progress=job.progress,
            error=job.error,
        )
        self._s.add(row)
        await self._s.flush()
        return _to_entity(row)

    async def get(self, job_id: str) -> Job | None:
        row = await self._s.get(JobModel, job_id)
        return _to_entity(row) if row else None

    async def claim(self, job_id: str) -> Job | None:
        """Atomically move a PENDING/QUEUED job to PROCESSING; None if already taken/missing."""
        stmt = (
            select(JobModel)
            .where(
                JobModel.id == job_id,
                JobModel.status.in_([JobStatus.PENDING.value, JobStatus.QUEUED.value]),
            )
            .with_for_update(skip_locked=True)
        )
        row = (await self._s.execute(stmt)).scalar_one_or_none()
        if row is None:
            return None
        row.status = JobStatus.PROCESSING.value
        await self._s.flush()
        return _to_entity(row)

    async def set_status(self, job_id: str, status: JobStatus, error: str | None = None) -> None:
        row = await self._s.get(JobModel, job_id)
        if row is None:
            return
        row.status = status.value
        if error is not None:
            row.error = error
        await self._s.flush()

    async def get_latest_for_media(self, media_id: str) -> Job | None:
        stmt = (
            select(JobModel)
            .where(JobModel.media_id == media_id)
            .order_by(JobModel.created_at.desc())
            .limit(1)
        )
        row = (await self._s.execute(stmt)).scalar_one_or_none()
        return _to_entity(row) if row else None

    async def set_progress(self, job_id: str, progress: float, stage: str | None = None) -> None:
        """Persist progress/stage and commit immediately (not just flush).

        Progress is polled by GET /jobs/{id} from a *different* HTTP request's
        transaction, so a flush-only update is invisible until this whole job
        finishes — the commit here is what makes intra-job progress observable
        while the job is still running.
        """
        row = await self._s.get(JobModel, job_id)
        if row is None:
            return
        row.progress = progress
        if stage is not None:
            row.stage = stage
        await self._s.commit()
