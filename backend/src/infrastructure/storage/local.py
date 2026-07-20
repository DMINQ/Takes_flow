"""
Local filesystem storage adapter — implements StoragePort.

`data_dir` is a Docker volume, so uploads survive restarts. This is the single
seam to swap for S3 later (an S3Storage adapter satisfying the same port).
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

from src.domain.errors import FileTooLargeError, UnsupportedMediaError
from src.settings.config import CoreSettings

ALLOWED_EXTENSIONS = {
    ".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg",
    ".mp4", ".mov", ".mkv", ".webm",
}


class LocalStorage:
    """Filesystem-backed StoragePort implementation."""

    def __init__(self, settings: CoreSettings) -> None:
        self._settings = settings
        self._uploads = Path(settings.data_dir) / "uploads"

    def _ensure(self) -> None:
        self._uploads.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def validate_extension(filename: str) -> str:
        ext = Path(filename).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise UnsupportedMediaError(
                f"Unsupported file type '{ext or filename}'. "
                f"Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
            )
        return ext

    async def save_stream(
        self, file_id: str, extension: str, chunks: AsyncIterator[bytes]
    ) -> tuple[Path, int]:
        """Stream chunks to '<file_id><ext>', enforcing the size cap; cleans up on overflow."""
        self._ensure()
        dest = self._uploads / f"{file_id}{extension}"
        size = 0
        try:
            with dest.open("wb") as out:
                async for chunk in chunks:
                    if not chunk:
                        continue
                    size += len(chunk)
                    if size > self._settings.max_upload_bytes:
                        raise FileTooLargeError(
                            f"File exceeds the maximum of {self._settings.max_upload_bytes} bytes."
                        )
                    out.write(chunk)
        except FileTooLargeError:
            dest.unlink(missing_ok=True)
            raise
        return dest, size

    def resolve(self, file_id: str) -> Path | None:
        # Reject anything that isn't a clean hex id (path-traversal guard).
        if not file_id or not all(c in "0123456789abcdef" for c in file_id):
            return None
        matches = list(self._uploads.glob(f"{file_id}.*"))
        return matches[0] if matches else None
