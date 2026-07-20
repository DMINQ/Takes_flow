"""
Job routes — create a background job and poll its status.

POST /jobs persists the job + an outbox event (atomically) and returns
immediately with a job_id. The relay publishes it and the worker processes it
(steps 3/4). This is the async entry point for long files, vs the synchronous
/media/transcribe used for quick single-file runs.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from src.api.deps import job_service
from src.api.schemas.jobs import CreateJobRequest, JobResponse
from src.application.services.job_service import JobService
from src.domain.errors import MediaNotFoundError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post(
    "",
    response_model=JobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Create a background job (analysis or export)",
)
async def create_job(
    body: CreateJobRequest,
    service: JobService = Depends(job_service),
) -> JobResponse:
    """Enqueue work via the transactional outbox; returns the pending job."""
    try:
        job = await service.create(body.media_id, body.kind, body.params)
    except MediaNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    logger.info("Created %s job %s for media %s", body.kind.value, job.id, body.media_id)
    return JobResponse(
        id=job.id, media_id=job.media_id, kind=job.kind,
        status=job.status, progress=job.progress, error=job.error,
    )


@router.get("/{job_id}", response_model=JobResponse, summary="Get job status")
async def get_job(
    job_id: str,
    service: JobService = Depends(job_service),
) -> JobResponse:
    job = await service.get(job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"No job '{job_id}'.")
    return JobResponse(
        id=job.id, media_id=job.media_id, kind=job.kind,
        status=job.status, progress=job.progress, error=job.error,
    )
