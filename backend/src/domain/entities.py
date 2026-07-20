"""
Domain entities — plain dataclasses, framework-agnostic.

These model the business concepts. ORM models (infrastructure/models.py) and API
schemas (api/schemas/) are separate representations that map to/from these.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from src.domain.enums import CutReason, JobKind, JobStatus, RegionKind


@dataclass(slots=True)
class Media:
    """An uploaded source file."""

    id: str
    filename: str
    path: str
    size_bytes: int
    content_type: str | None = None
    duration: float | None = None
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
