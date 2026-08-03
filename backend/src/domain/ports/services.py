"""
Ports — the interfaces the domain/application layers depend on.

Infrastructure provides concrete adapters (local vs remote, fs vs s3). Because
callers depend on these Protocols and never on the adapters, swapping an
implementation is a settings change (see settings/providers.py). This is the
Dependency Inversion boundary of the app.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Protocol, runtime_checkable

from src.domain.entities import (
    PartUploadTicket,
    SpeakerTurn,
    StoredObject,
    UploadTicket,
    Word,
)


@runtime_checkable
class TranscriberPort(Protocol):
    """Turns a media file into word-level-timestamped text."""

    def transcribe(
        self, media_path: Path, language: str | None = None
    ) -> tuple[list[Word], str, float, float]:
        """
        Returns (words, detected_language, language_probability, duration).

        Implementations may be blocking (CPU/GPU-bound) — callers offload to a
        thread. Raise TranscriptionError / OutOfMemoryError (domain.errors) on
        failure so the API can map them to clean HTTP responses.
        """
        ...


@runtime_checkable
class DiarizerPort(Protocol):
    """Splits audio into speaker turns (podcasts / multi-voice)."""

    def diarize(self, media_path: Path) -> list[SpeakerTurn]:
        """Return speech turns in chronological order.

        The stub adapter returns a single turn spanning the whole file, which
        keeps downstream stages (silence cutting) working with one speaker.
        """
        ...


@runtime_checkable
class AudioEnginePort(Protocol):
    """FFmpeg + pedalboard operations: probe, pre-clean, concat, master."""

    def probe_duration(self, media_path: Path) -> float: ...

    def preprocess(self, media_path: Path, out_path: Path) -> Path:
        """Denoise + normalize a copy for more accurate transcription."""
        ...

    def assemble(self, media_path: Path, keep_ranges: list[tuple[float, float]], out_path: Path) -> Path:
        """Concatenate the kept time ranges into one file (export)."""
        ...

    def master(self, media_path: Path, out_path: Path) -> Path:
        """Apply noise reduction -> EQ -> compressor -> LUFS normalization."""
        ...


@runtime_checkable
class StoragePort(Protocol):
    """
    Object storage for media and artifacts (filesystem, S3, MinIO).

    Deliberately object-oriented rather than path-oriented: bytes never travel
    through the API process. Clients upload straight to storage using
    short-lived presigned URLs, and the API only mints tickets and verifies the
    result. `materialize` exists because ffmpeg/Whisper need a real local file;
    it is the single, explicit place where an object becomes a path.
    """

    # --- direct upload (single request; for files under the multipart threshold) ---
    async def presign_put(self, key: str, *, content_type: str | None, expires_in: int) -> UploadTicket:
        """Mint a short-lived URL the client PUTs the whole object to."""
        ...

    # --- direct download (e.g. the finished export) ---
    async def presign_get(self, key: str, *, expires_in: int) -> UploadTicket:
        """Mint a short-lived URL the client GETs the object from."""
        ...

    # --- multipart upload (large files: parallel parts, per-part retry) ---
    async def create_multipart(self, key: str, *, content_type: str | None) -> str:
        """Begin a multipart upload; returns the storage-assigned upload id."""
        ...

    async def presign_parts(
        self, key: str, upload_id: str, *, part_numbers: list[int], expires_in: int
    ) -> list[PartUploadTicket]:
        """Mint one URL per part. Parts may be uploaded in parallel and retried."""
        ...

    async def complete_multipart(self, key: str, upload_id: str, parts: list[tuple[int, str]]) -> StoredObject:
        """Assemble the parts (list of (part_number, etag)) into one object."""
        ...

    async def abort_multipart(self, key: str, upload_id: str) -> None:
        """Discard an unfinished upload so partial parts are not billed/kept."""
        ...

    # --- verification and access ---
    async def stat(self, key: str) -> StoredObject | None:
        """Server-side truth about a stored object; None when absent."""
        ...

    async def open_range(self, key: str, *, start: int, length: int) -> bytes:
        """Read a byte range — used to sniff the real media type after upload."""
        ...

    async def materialize(self, key: str, dest_dir: Path) -> Path:
        """Make the object available as a local file (no-op for the fs adapter)."""
        ...

    async def save_stream(self, key: str, chunks: AsyncIterator[bytes]) -> StoredObject:
        """Server-side write — used by the worker for derived artifacts, not uploads."""
        ...

    async def delete(self, key: str) -> None: ...


@runtime_checkable
class LLMPort(Protocol):
    """Optional semantic similarity/embeddings for bad-take detection, plus
    transcript clean-up (filler words, hesitations, stutters)."""

    def similarity(self, a: str, b: str) -> float:
        """Return semantic similarity in 0..1. Off-provider adapters may raise."""
        ...

    def clean_transcript(self, raw_text: str) -> str:
        """Return `raw_text` stripped of filler words/hesitations/stutters.

        Must preserve meaning, sentence structure and punctuation — this is a
        copy-edit pass, not a rewrite. Implementations should be deterministic
        (temperature=0) so re-runs on the same input are stable.
        """
        ...
