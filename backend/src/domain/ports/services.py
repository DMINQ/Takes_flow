"""
Ports — the interfaces the domain/application layers depend on.

Infrastructure provides concrete adapters (local vs remote, fs vs s3). Because
callers depend on these Protocols and never on the adapters, swapping an
implementation is a settings change (see settings/providers.py). This is the
Dependency Inversion boundary of the app.
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from src.domain.entities import Speaker, Word


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
    """Assigns speaker labels to time ranges (podcasts / multi-voice)."""

    def diarize(self, media_path: Path) -> list[Speaker]:
        """Return detected speakers. The stub adapter returns a single speaker."""
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
    """Persist and resolve media/output artifacts (local fs or S3)."""

    async def save_stream(self, file_id: str, extension: str, chunks) -> tuple[Path, int]:
        """Stream chunks to storage; return (path, size_bytes)."""
        ...

    def resolve(self, file_id: str) -> Path | None: ...


@runtime_checkable
class LLMPort(Protocol):
    """Optional semantic similarity/embeddings for bad-take detection."""

    def similarity(self, a: str, b: str) -> float:
        """Return semantic similarity in 0..1. Off-provider adapters may raise."""
        ...
