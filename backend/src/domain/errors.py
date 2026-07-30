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


class UploadSessionNotFoundError(DomainError):
    pass


class UploadNotFinishedError(DomainError):
    """Client called complete but storage has no (or a partial) object."""


class UploadSizeMismatchError(DomainError):
    """Stored size disagrees with what the client declared at initiation."""


class UploadStateError(DomainError):
    """Operation is invalid for the session's current status."""


class StorageError(DomainError):
    """Object storage refused or failed an operation."""
