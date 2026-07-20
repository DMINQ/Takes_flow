"""Domain-level exceptions — raised by adapters, mapped to HTTP in the API layer."""
from __future__ import annotations


class DomainError(Exception):
    """Base for all expected, surfaced errors."""


class MediaNotFoundError(DomainError):
    pass


class UnsupportedMediaError(DomainError):
    pass


class FileTooLargeError(DomainError):
    pass


class TranscriptionError(DomainError):
    pass


class OutOfMemoryError(TranscriptionError):
    """CUDA/host OOM during transcription — API maps to 507 with guidance."""


class AudioProcessingError(DomainError):
    pass
