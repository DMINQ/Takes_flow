"""Domain enums — shared vocabulary across every layer. No external dependencies."""
from __future__ import annotations

from enum import Enum


class JobStatus(str, Enum):
    """Lifecycle of an analysis or export job."""

    PENDING = "pending"        # persisted, event in outbox, not yet picked up
    QUEUED = "queued"          # published to broker
    PROCESSING = "processing"  # worker claimed it
    COMPLETED = "completed"
    FAILED = "failed"


class JobKind(str, Enum):
    """Which pipeline a job runs."""

    ANALYSIS = "analysis"  # transcribe + detect silence/bad-takes -> timeline
    EXPORT = "export"      # assemble kept segments + master -> final file


class RegionKind(str, Enum):
    """
    Timeline region classification — drives the red/yellow/green UI.

    KEEP     -> green:  audio to retain.
    AUTO_CUT -> red:    silence or bad take, removed automatically.
    REVIEW   -> yellow: ambiguous duplicate takes; user listens and decides.
    """

    KEEP = "keep"
    AUTO_CUT = "auto_cut"
    REVIEW = "review"


class CutReason(str, Enum):
    """Why a region was marked AUTO_CUT / REVIEW — surfaced to the user."""

    SILENCE = "silence"
    BAD_TAKE = "bad_take"          # earlier duplicate of a later, better take
    ALTERNATE_TAKE = "alternate"   # ambiguous duplicate -> needs review


class OutboxStatus(str, Enum):
    PENDING = "pending"
    PUBLISHED = "published"
    FAILED = "failed"
