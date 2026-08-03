"""HTTP schemas for job endpoints."""
from __future__ import annotations

from pydantic import BaseModel, Field

from src.domain.enums import JobKind, JobStatus


class CreateJobRequest(BaseModel):
    media_id: str = Field(..., description="Id returned from /media/upload.")
    kind: JobKind = Field(default=JobKind.ANALYSIS, description="Which pipeline to run.")
    params: dict = Field(
        default_factory=dict,
        description=(
            "Optional pipeline parameters. For kind=export, "
            "params.export_selection is a list of 'cut:<start>:<end>' strings "
            "naming which REVIEW (duplicate-take) regions to drop; every other "
            "KEEP region is exported unchanged."
        ),
    )


class JobResponse(BaseModel):
    id: str
    media_id: str
    kind: JobKind
    status: JobStatus
    progress: float
    stage: str | None = None
    error: str | None = None
