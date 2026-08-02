"""
Job processor — glue between a broker message and the pipeline `Runner`.

Shared by both FastStream subscribers (analysis/export streams): claims the
job, builds a fresh PipelineContext from the event payload, builds the
JobKind's plugin list against a new DB session, runs it, and finalizes the
job status. One session per job run mirrors the API's one-session-per-request
pattern and keeps the transaction scoped to a single job.
"""
from __future__ import annotations

import logging

from src.application.pipeline.pipelines import register_pipelines
from src.application.pipeline.registry import registry
from src.application.pipeline.runner import PipelineError, Runner
from src.domain.dto import PipelineContext
from src.domain.entities import Media
from src.domain.enums import JobKind, JobStatus
from src.domain.errors import DomainError
from src.infrastructure.db import AsyncSessionLocal
from src.infrastructure.repositories.job import SqlJobRepository
from src.infrastructure.repositories.media import SqlMediaRepository

logger = logging.getLogger("takeflow.worker.processor")


async def process_job_event(payload: dict) -> None:
    """Claim the job named in `payload` and run its pipeline to completion.

    Swallows/logs all failures rather than raising: FastStream would otherwise
    retry-redeliver a message whose job is already durably marked FAILED,
    which would just re-attempt (and re-fail) the same work forever.
    """
    job_id = payload.get("job_id")
    media_id = payload.get("media_id")
    kind_value = payload.get("kind")
    if not job_id or not media_id or not kind_value:
        logger.error("Malformed job event, ignoring: %r", payload)
        return

    async with AsyncSessionLocal() as session:
        job_repo = SqlJobRepository(session)
        media_repo = SqlMediaRepository(session)

        job = await job_repo.claim(job_id)
        if job is None:
            logger.info("Job %s already claimed or missing; skipping.", job_id)
            return
        await session.commit()

        try:
            kind = JobKind(kind_value)
        except ValueError:
            logger.error("Job %s has unknown kind '%s'; marking failed.", job_id, kind_value)
            await job_repo.set_status(job_id, JobStatus.FAILED, error=f"Unknown job kind '{kind_value}'.")
            await session.commit()
            return

        media: Media | None = await media_repo.get(media_id)
        if media is None:
            logger.error("Job %s references missing media %s; marking failed.", job_id, media_id)
            await job_repo.set_status(job_id, JobStatus.FAILED, error=f"Media '{media_id}' not found.")
            await session.commit()
            return

        register_pipelines(session)
        try:
            plugins = registry.build(kind)
        except KeyError as exc:
            logger.error("Job %s: %s", job_id, exc)
            await job_repo.set_status(job_id, JobStatus.FAILED, error=str(exc))
            await session.commit()
            return

        context = PipelineContext(
            job_id=job_id,
            project_id=media.project_id,
            media_id=media_id,
            input_path="",
            original_filename=media.filename,
            language=(payload.get("params") or {}).get("language"),
        )

        runner = Runner(plugins, job_repo)
        try:
            await runner.run(context)
        except (PipelineError, DomainError) as exc:
            logger.exception("Job %s failed", job_id)
            await job_repo.set_status(job_id, JobStatus.FAILED, error=str(exc))
            await session.commit()
            return
        except Exception as exc:  # noqa: BLE001 - last-resort guard, never crash the consumer
            logger.exception("Job %s failed with an unexpected error", job_id)
            await job_repo.set_status(job_id, JobStatus.FAILED, error=f"Unexpected error: {exc}")
            await session.commit()
            return

        await job_repo.set_status(job_id, JobStatus.COMPLETED)
        await session.commit()
        logger.info("Job %s completed", job_id)
