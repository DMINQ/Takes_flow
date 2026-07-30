"""
Domain entities — plain dataclasses, framework-agnostic.

These model the business concepts. ORM models (infrastructure/models.py) and API
schemas (api/schemas/) are separate representations that map to/from these.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from src.domain.enums import (
    CutReason,
    JobKind,
    JobStatus,
    RegionKind,
    UploadMode,
    UploadStatus,
)


@dataclass(slots=True)
class Media:
    """
    An uploaded source file.

    `storage_key` is the object key — the only handle the domain keeps. There is
    no local path here on purpose: with S3 the file may never touch this host's
    disk, and StoragePort.materialize is the explicit seam when a real path is
    required (ffmpeg/Whisper).
    """

    id: str
    filename: str
    storage_key: str
    size_bytes: int
    content_type: str | None = None
    duration: float | None = None
    checksum: str | None = None
    created_at: datetime | None = None


@dataclass(slots=True)
class StoredObject:
    """Server-side truth about an object in storage."""

    key: str
    size_bytes: int
    etag: str | None = None
    content_type: str | None = None


@dataclass(slots=True)
class UploadTicket:
    """A short-lived presigned URL for a single-request upload."""

    url: str
    method: str = "PUT"
    headers: dict[str, str] = field(default_factory=dict)
    expires_at: datetime | None = None


@dataclass(slots=True)
class PartUploadTicket:
    """A presigned URL for one part of a multipart upload."""

    part_number: int
    url: str
    method: str = "PUT"
    headers: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class UploadSession:
    """
    A negotiated, client-direct upload.

    Created before any bytes move: the client declares filename and size, the
    API validates the declaration, reserves an object key and hands back
    presigned tickets. Nothing is trusted until `complete` verifies the object
    against storage.
    """

    id: str
    storage_key: str
    filename: str
    declared_size: int
    mode: UploadMode
    status: UploadStatus = UploadStatus.INITIATED
    upload_id: str | None = None      # storage-assigned, multipart only
    part_size: int | None = None
    part_count: int | None = None
    content_type: str | None = None
    media_id: str | None = None       # set once completed
    expires_at: datetime | None = None
    created_at: datetime | None = None


@dataclass(slots=True)
class Word:
    """A transcribed word with precise timing (seconds) and optional speaker."""

    text: str
    start: float
    end: float
    probability: float = 1.0
    speaker: str | None = None


@dataclass(slots=True)
class Phrase:
    """A logical phrase/sentence — the unit compared for bad-take detection."""

    text: str
    start: float
    end: float
    words: list[Word] = field(default_factory=list)
    speaker: str | None = None


@dataclass(slots=True)
class Speaker:
    """A diarized speaker (podcast / multi-voice)."""

    id: str
    label: str  # e.g. "SPEAKER_00"


@dataclass(slots=True)
class TimelineRegion:
    """One contiguous span on the timeline with a keep/cut/review classification."""

    start: float
    end: float
    kind: RegionKind
    reason: CutReason | None = None
    # For duplicate takes: links regions that are alternatives of one another.
    take_group: str | None = None
    text: str | None = None
    speaker: str | None = None


@dataclass(slots=True)
class Job:
    """A unit of background work over a Media file."""

    id: str
    media_id: str
    kind: JobKind
    status: JobStatus = JobStatus.PENDING
    progress: float = 0.0
    error: str | None = None
    created_at: datetime | None = None
