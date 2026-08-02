"""
S3 / MinIO storage adapter — implements StoragePort.

Bytes never pass through this process for uploads: the adapter only mints
presigned URLs and asks S3 for the truth afterwards. The same code targets AWS
S3 and MinIO (endpoint + path-style addressing), so local dev and production run
the identical upload path.

aioboto3 creates clients as async context managers, so every call opens one from
a shared session. That is cheap (connections are pooled by botocore) and avoids
holding a client across event-loop restarts.
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from src.domain.entities import PartUploadTicket, StoredObject, UploadTicket
from src.domain.errors import StorageError
from src.domain.upload_policy import ticket_expiry
from src.settings.config import StorageSettings

logger = logging.getLogger(__name__)


class S3Storage:
    """Presigned-upload object storage over S3-compatible APIs."""

    def __init__(self, settings: StorageSettings) -> None:
        self._settings = settings
        self._bucket = settings.s3_bucket
        # Imported lazily so the S3 dependency is only required when enabled.
        import aioboto3

        self._session = aioboto3.Session(
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name=settings.s3_region,
        )

    @asynccontextmanager
    async def _client(self):
        from botocore.config import Config

        config = Config(
            signature_version="s3v4",
            # MinIO and other S3-compatibles need path-style addressing.
            s3={"addressing_style": "path" if self._settings.s3_endpoint else "auto"},
            retries={"max_attempts": 3, "mode": "standard"},
        )
        async with self._session.client(
            "s3", endpoint_url=self._settings.s3_endpoint, config=config
        ) as client:
            yield client

    # --- single-request upload -------------------------------------------------------
    async def presign_put(
        self, key: str, *, content_type: str | None, expires_in: int
    ) -> UploadTicket:
        params: dict[str, object] = {"Bucket": self._bucket, "Key": key}
        if content_type:
            params["ContentType"] = content_type
        async with self._client() as client:
            url = await client.generate_presigned_url(
                "put_object", Params=params, ExpiresIn=expires_in
            )
        # The signature covers Content-Type, so the client must send it verbatim.
        headers = {"Content-Type": content_type} if content_type else {}
        return UploadTicket(url=url, method="PUT", headers=headers, expires_at=ticket_expiry(expires_in))

    async def presign_get(self, key: str, *, expires_in: int) -> UploadTicket:
        async with self._client() as client:
            url = await client.generate_presigned_url(
                "get_object", Params={"Bucket": self._bucket, "Key": key}, ExpiresIn=expires_in
            )
        return UploadTicket(url=url, method="GET", expires_at=ticket_expiry(expires_in))

    # --- multipart upload ------------------------------------------------------------
    async def create_multipart(self, key: str, *, content_type: str | None) -> str:
        params: dict[str, object] = {"Bucket": self._bucket, "Key": key}
        if content_type:
            params["ContentType"] = content_type
        try:
            async with self._client() as client:
                result = await client.create_multipart_upload(**params)
        except Exception as exc:  # botocore raises a wide surface; normalize it
            raise StorageError(f"Could not start multipart upload for '{key}': {exc}") from exc
        return result["UploadId"]

    async def presign_parts(
        self, key: str, upload_id: str, *, part_numbers: list[int], expires_in: int
    ) -> list[PartUploadTicket]:
        tickets: list[PartUploadTicket] = []
        async with self._client() as client:
            for number in part_numbers:
                url = await client.generate_presigned_url(
                    "upload_part",
                    Params={
                        "Bucket": self._bucket,
                        "Key": key,
                        "UploadId": upload_id,
                        "PartNumber": number,
                    },
                    ExpiresIn=expires_in,
                )
                tickets.append(PartUploadTicket(part_number=number, url=url))
        return tickets

    async def complete_multipart(
        self, key: str, upload_id: str, parts: list[tuple[int, str]]
    ) -> StoredObject:
        # S3 rejects an out-of-order or gapped part list, so sort defensively.
        payload = {
            "Parts": [
                {"PartNumber": number, "ETag": etag}
                for number, etag in sorted(parts, key=lambda p: p[0])
            ]
        }
        try:
            async with self._client() as client:
                await client.complete_multipart_upload(
                    Bucket=self._bucket, Key=key, UploadId=upload_id, MultipartUpload=payload
                )
        except Exception as exc:
            raise StorageError(f"Could not complete multipart upload for '{key}': {exc}") from exc

        stored = await self.stat(key)
        if stored is None:
            raise StorageError(f"Object '{key}' missing after completing multipart upload.")
        return stored

    async def abort_multipart(self, key: str, upload_id: str) -> None:
        try:
            async with self._client() as client:
                await client.abort_multipart_upload(
                    Bucket=self._bucket, Key=key, UploadId=upload_id
                )
        except Exception:
            # Abort is best-effort cleanup; a bucket lifecycle rule is the backstop.
            logger.warning("Failed to abort multipart upload %s for %s", upload_id, key, exc_info=True)

    # --- verification and access -----------------------------------------------------
    async def stat(self, key: str) -> StoredObject | None:
        async with self._client() as client:
            try:
                head = await client.head_object(Bucket=self._bucket, Key=key)
            except Exception:
                return None
        return StoredObject(
            key=key,
            size_bytes=head["ContentLength"],
            etag=head.get("ETag", "").strip('"') or None,
            content_type=head.get("ContentType"),
        )

    async def open_range(self, key: str, *, start: int, length: int) -> bytes:
        end = start + length - 1
        async with self._client() as client:
            response = await client.get_object(
                Bucket=self._bucket, Key=key, Range=f"bytes={start}-{end}"
            )
            async with response["Body"] as stream:
                return await stream.read()

    async def materialize(self, key: str, dest_dir: Path) -> Path:
        """Download the object so ffmpeg/Whisper can work on a real file."""
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / Path(key).name
        async with self._client() as client:
            response = await client.get_object(Bucket=self._bucket, Key=key)
            async with response["Body"] as stream:
                with dest.open("wb") as out:
                    while chunk := await stream.read(1024 * 1024):
                        out.write(chunk)
        return dest

    async def save_stream(self, key: str, chunks: AsyncIterator[bytes]) -> StoredObject:
        """
        Server-side write for derived artifacts (exports, previews).

        Buffers to a multipart upload so a long export never holds the whole
        file in memory.
        """
        upload_id = await self.create_multipart(key, content_type=None)
        parts: list[tuple[int, str]] = []
        buffer = bytearray()
        number = 1
        chunk_target = 8 * 1024 * 1024
        try:
            async with self._client() as client:
                async for chunk in chunks:
                    buffer.extend(chunk)
                    if len(buffer) >= chunk_target:
                        result = await client.upload_part(
                            Bucket=self._bucket, Key=key, UploadId=upload_id,
                            PartNumber=number, Body=bytes(buffer),
                        )
                        parts.append((number, result["ETag"].strip('"')))
                        buffer.clear()
                        number += 1
                if buffer or not parts:
                    result = await client.upload_part(
                        Bucket=self._bucket, Key=key, UploadId=upload_id,
                        PartNumber=number, Body=bytes(buffer),
                    )
                    parts.append((number, result["ETag"].strip('"')))
        except Exception:
            await self.abort_multipart(key, upload_id)
            raise
        return await self.complete_multipart(key, upload_id, parts)

    async def delete(self, key: str) -> None:
        async with self._client() as client:
            await client.delete_object(Bucket=self._bucket, Key=key)
