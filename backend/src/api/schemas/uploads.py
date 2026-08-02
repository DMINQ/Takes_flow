"""
HTTP schemas for the direct-upload negotiation — the client contract.

The flow is deliberately explicit rather than a single POST: the client learns
where to send bytes, sends them itself, then reports back. These models are what
a frontend or the CLI codes against.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from src.domain.enums import UploadMode


class UploadInitRequest(BaseModel):
    """Declaration made before any byte moves, so rejection is cheap."""

    filename: str = Field(..., max_length=512, description="Used for the extension check.")
    size_bytes: int = Field(..., gt=0, description="Exact byte size; re-verified against storage.")
    content_type: str | None = Field(default=None, max_length=128)
    project_id: str | None = Field(
        default=None,
        max_length=32,
        description="Group this upload with an existing project (e.g. another take). "
        "Omit to start a new project.",
    )


class PartTicketOut(BaseModel):
    part_number: int
    url: str
    method: str = "PUT"
    headers: dict[str, str] = Field(default_factory=dict)


class TicketOut(BaseModel):
    url: str
    method: str = "PUT"
    headers: dict[str, str] = Field(default_factory=dict)
    expires_at: datetime | None = None


class UploadInitResponse(BaseModel):
    """
    Everything the client needs to upload without touching the API again.

    `single` is set for small files; `parts` for large ones. Parts may be sent in
    parallel and retried individually — that is the point of multipart for
    multi-hour media.
    """

    session_id: str
    project_id: str
    mode: UploadMode
    storage_key: str
    part_size: int | None = None
    part_count: int | None = None
    single: TicketOut | None = None
    parts: list[PartTicketOut] = Field(default_factory=list)
    expires_at: datetime | None = None


class CompletedPart(BaseModel):
    part_number: int = Field(..., ge=1)
    etag: str = Field(..., description="ETag returned by storage for this part.")


class UploadCompleteRequest(BaseModel):
    """Multipart uploads must report their parts; single uploads send nothing."""

    parts: list[CompletedPart] = Field(default_factory=list)


class MediaOut(BaseModel):
    file_id: str
    project_id: str
    filename: str
    size_bytes: int
    content_type: str | None = None
    checksum: str | None = None
