"""HTTP schemas for project endpoints."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from src.domain.enums import JobStatus


class ProjectOut(BaseModel):
    id: str
    name: str
    created_at: datetime | None = None
    media_count: int = 0


class ProjectMediaOut(BaseModel):
    """One Media row inside a project, with its most recent job's status.

    `latest_job_id`/`latest_job_status`/`latest_job_progress`/`latest_job_stage`
    are None when no job has ever run for this media (upload only, not
    analyzed yet) — the frontend uses that to route to Analysis vs Timeline.
    """

    id: str
    filename: str
    duration: float | None = None
    created_at: datetime | None = None
    latest_job_id: str | None = None
    latest_job_kind: str | None = None
    latest_job_status: JobStatus | None = None
    latest_job_progress: float | None = None
    latest_job_stage: str | None = None
