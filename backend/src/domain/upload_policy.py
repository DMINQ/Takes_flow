"""
Upload policy — domain rules for accepting a media upload.

Lives in the domain (not in a storage adapter) because "which files we accept"
and "how an upload is chunked" are business rules, identical whether bytes land
on a local disk or in S3. The API layer and every adapter share this one source
of truth.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath

from src.domain.enums import UploadMode
from src.domain.errors import FileTooLargeError, UnsupportedMediaError

ALLOWED_EXTENSIONS = frozenset(
    {
        ".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg",
        ".mp4", ".mov", ".mkv", ".webm",
    }
)

# Extension -> magic byte signatures, checked server-side after upload. A client
# can rename anything to .wav, so the declared type is treated as a hint only.
_CONTAINER_SIGNATURES: dict[str, tuple[bytes, ...]] = {
    ".wav": (b"RIFF",),
    ".mp3": (b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"),
    ".flac": (b"fLaC",),
    ".ogg": (b"OggS",),
    ".mp4": (b"ftyp",),
    ".m4a": (b"ftyp",),
    ".mov": (b"ftyp",),
    ".mkv": (b"\x1a\x45\xdf\xa3",),
    ".webm": (b"\x1a\x45\xdf\xa3",),
    ".aac": (b"\xff\xf1", b"\xff\xf9", b"ID3"),
}

# S3 requires every part except the last to be >= 5 MiB, and allows at most
# 10 000 parts. 16 MiB keeps a 3-hour, ~10 GiB video well inside that ceiling
# while staying small enough that a failed part is cheap to retry.
MIN_PART_SIZE = 5 * 1024 * 1024
DEFAULT_PART_SIZE = 16 * 1024 * 1024
MAX_PARTS = 10_000

# Below this, a single presigned PUT is simpler and one round-trip cheaper.
MULTIPART_THRESHOLD = 32 * 1024 * 1024


def validate_extension(filename: str) -> str:
    """Return the normalized extension or raise UnsupportedMediaError."""
    ext = PurePosixPath(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise UnsupportedMediaError(
            f"Unsupported file type '{ext or filename}'. "
            f"Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )
    return ext


def validate_declared_size(size: int, max_bytes: int) -> None:
    """
    Reject oversized uploads before any byte is transferred.

    The client declares the size at initiation, so the cheap rejection happens
    here; `verify_stored_size` re-checks against storage afterwards because a
    declaration is not trustworthy.
    """
    if size <= 0:
        raise FileTooLargeError("Declared size must be greater than zero.")
    if size > max_bytes:
        raise FileTooLargeError(
            f"File of {size} bytes exceeds the maximum of {max_bytes} bytes."
        )


def sniff_matches_extension(header: bytes, ext: str) -> bool:
    """
    Check magic bytes against the extension.

    ISO-BMFF containers (mp4/mov/m4a) carry 'ftyp' at offset 4, so the whole
    header window is searched rather than only its prefix.
    """
    signatures = _CONTAINER_SIGNATURES.get(ext)
    if not signatures:
        return True
    window = header[:16]
    return any(sig in window for sig in signatures)


def plan_upload(size: int, part_size: int = DEFAULT_PART_SIZE) -> tuple[UploadMode, int | None, int | None]:
    """
    Decide single vs multipart and how to split.

    Returns (mode, part_size, part_count). Part size grows if the file would
    otherwise exceed MAX_PARTS, which is what makes multi-hour video work.
    """
    if size < MULTIPART_THRESHOLD:
        return UploadMode.SINGLE, None, None

    effective = max(part_size, MIN_PART_SIZE)
    count = (size + effective - 1) // effective
    if count > MAX_PARTS:
        effective = (size + MAX_PARTS - 1) // MAX_PARTS
        # Round up to a MiB boundary so part offsets stay readable in logs.
        effective = ((effective + (1024 * 1024) - 1) // (1024 * 1024)) * 1024 * 1024
        count = (size + effective - 1) // effective
    return UploadMode.MULTIPART, effective, count


def build_storage_key(media_id: str, extension: str, *, now: datetime | None = None) -> str:
    """
    Object key for a source upload.

    Date-prefixed so lifecycle rules and partitioned analytics work naturally,
    and so no single prefix accumulates every object (which throttles on S3).
    """
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y/%m/%d")
    return f"uploads/{stamp}/{media_id}{extension}"


def new_media_id() -> str:
    return uuid.uuid4().hex


def ticket_expiry(seconds: int, *, now: datetime | None = None) -> datetime:
    return (now or datetime.now(timezone.utc)) + timedelta(seconds=seconds)
