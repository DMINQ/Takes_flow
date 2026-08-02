"""
Local filesystem storage adapter — implements StoragePort.

Mirrors the S3 adapter's contract rather than short-circuiting it: it mints
HMAC-signed URLs pointing at this app's own upload-sink endpoints, so the client
follows the exact same "PUT straight to storage" flow in local dev as it does in
production. Bugs in the upload path therefore surface without MinIO running.

Parts are written as sibling `.part-NNNNN` files and concatenated on complete,
which is the filesystem analogue of a multipart upload.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import shutil
import time
from collections.abc import AsyncIterator
from pathlib import Path
from urllib.parse import quote, urlencode

from src.domain.entities import PartUploadTicket, StoredObject, UploadTicket
from src.domain.errors import StorageError
from src.domain.upload_policy import ticket_expiry
from src.settings.config import CoreSettings, StorageSettings

logger = logging.getLogger(__name__)


class LocalStorage:
    """Filesystem-backed StoragePort with presign parity."""

    def __init__(self, core: CoreSettings, storage: StorageSettings) -> None:
        self._core = core
        self._storage = storage
        self._root = Path(core.data_dir) / "objects"
        self._secret = storage.presign_secret.encode()
        self._base_url = storage.local_public_url.rstrip("/")

    # --- signing -------------------------------------------------------------------
    def _sign(self, key: str, expires: int, part: int | None) -> str:
        payload = f"{key}:{expires}:{part if part is not None else ''}"
        return hmac.new(self._secret, payload.encode(), hashlib.sha256).hexdigest()

    def verify(self, key: str, expires: int, signature: str, part: int | None = None) -> bool:
        """Constant-time check used by the upload-sink endpoints."""
        if expires < int(time.time()):
            return False
        return hmac.compare_digest(self._sign(key, expires, part), signature)

    def _ticket_url(self, key: str, expires_in: int, part: int | None = None) -> str:
        expires = int(time.time()) + expires_in
        query = {"expires": expires, "signature": self._sign(key, expires, part)}
        if part is not None:
            query["part"] = part
        return f"{self._base_url}/api/v1/uploads/sink/{quote(key)}?{urlencode(query)}"

    def _download_ticket_url(self, key: str, expires_in: int) -> str:
        expires = int(time.time()) + expires_in
        query = {"expires": expires, "signature": self._sign(key, expires, None)}
        return f"{self._base_url}/api/v1/uploads/source/{quote(key)}?{urlencode(query)}"

    # --- key/path mapping ----------------------------------------------------------
    def _path_for(self, key: str) -> Path:
        """
        Resolve a key under the object root, refusing traversal.

        `Path.resolve` collapses any '..' before the containment check, so a key
        like 'uploads/../../etc/passwd' cannot escape the root.
        """
        candidate = (self._root / key).resolve()
        root = self._root.resolve()
        if not candidate.is_relative_to(root):
            raise StorageError(f"Refusing to resolve key outside the object root: '{key}'")
        return candidate

    def _part_path(self, key: str, part_number: int) -> Path:
        base = self._path_for(key)
        return base.with_name(f"{base.name}.part-{part_number:05d}")

    # --- single-request upload -----------------------------------------------------
    async def presign_put(
        self, key: str, *, content_type: str | None, expires_in: int
    ) -> UploadTicket:
        headers = {"Content-Type": content_type} if content_type else {}
        return UploadTicket(
            url=self._ticket_url(key, expires_in),
            method="PUT",
            headers=headers,
            expires_at=ticket_expiry(expires_in),
        )

    # --- direct download -------------------------------------------------------------
    async def presign_get(self, key: str, *, expires_in: int) -> UploadTicket:
        return UploadTicket(
            url=self._download_ticket_url(key, expires_in),
            method="GET",
            expires_at=ticket_expiry(expires_in),
        )

    # --- multipart upload ----------------------------------------------------------
    async def create_multipart(self, key: str, *, content_type: str | None) -> str:
        self._path_for(key).parent.mkdir(parents=True, exist_ok=True)
        # No server-side session to track; the key itself identifies the upload.
        return f"local-{int(time.time())}"

    async def presign_parts(
        self, key: str, upload_id: str, *, part_numbers: list[int], expires_in: int
    ) -> list[PartUploadTicket]:
        return [
            PartUploadTicket(part_number=n, url=self._ticket_url(key, expires_in, part=n))
            for n in part_numbers
        ]

    async def complete_multipart(
        self, key: str, upload_id: str, parts: list[tuple[int, str]]
    ) -> StoredObject:
        dest = self._path_for(key)
        expected = sorted(number for number, _ in parts)
        with dest.open("wb") as out:
            for number in expected:
                part = self._part_path(key, number)
                if not part.exists():
                    raise StorageError(f"Part {number} of '{key}' was never uploaded.")
                with part.open("rb") as src:
                    shutil.copyfileobj(src, out, length=1024 * 1024)
        for number in expected:
            self._part_path(key, number).unlink(missing_ok=True)

        stored = await self.stat(key)
        if stored is None:
            raise StorageError(f"Object '{key}' missing after assembling parts.")
        return stored

    async def abort_multipart(self, key: str, upload_id: str) -> None:
        base = self._path_for(key)
        for leftover in base.parent.glob(f"{base.name}.part-*"):
            leftover.unlink(missing_ok=True)

    # --- sink writes (called by the presigned endpoints) ---------------------------
    async def write_object(self, key: str, chunks: AsyncIterator[bytes], *, part: int | None = None) -> int:
        """Persist an incoming presigned PUT; returns bytes written."""
        dest = self._path_for(key) if part is None else self._part_path(key, part)
        dest.parent.mkdir(parents=True, exist_ok=True)
        size = 0
        with dest.open("wb") as out:
            async for chunk in chunks:
                if chunk:
                    size += len(chunk)
                    out.write(chunk)
        return size

    # --- verification and access ---------------------------------------------------
    async def stat(self, key: str) -> StoredObject | None:
        path = self._path_for(key)
        if not path.is_file():
            return None
        return StoredObject(key=key, size_bytes=path.stat().st_size)

    async def open_range(self, key: str, *, start: int, length: int) -> bytes:
        path = self._path_for(key)
        if not path.is_file():
            return b""
        with path.open("rb") as handle:
            handle.seek(start)
            return handle.read(length)

    async def materialize(self, key: str, dest_dir: Path) -> Path:
        """Already local — return the path without copying."""
        path = self._path_for(key)
        if not path.is_file():
            raise StorageError(f"Object '{key}' not found.")
        return path

    async def save_stream(self, key: str, chunks: AsyncIterator[bytes]) -> StoredObject:
        size = await self.write_object(key, chunks)
        return StoredObject(key=key, size_bytes=size)

    async def read_object(self, key: str, *, chunk_size: int = 1024 * 1024) -> AsyncIterator[bytes]:
        """Stream a stored object back — used by the local download-sink endpoint."""
        path = self._path_for(key)
        if not path.is_file():
            raise StorageError(f"Object '{key}' not found.")
        with path.open("rb") as handle:
            while chunk := handle.read(chunk_size):
                yield chunk

    async def delete(self, key: str) -> None:
        self._path_for(key).unlink(missing_ok=True)
