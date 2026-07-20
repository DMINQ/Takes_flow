"""
MediaService — use-cases around uploaded source files.

Streams the upload through the StoragePort, then persists a Media row. The
media id and the storage file id are the same value, so `file_id` in URLs and
`media_id` in the DB refer to one artifact.
"""
from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.entities import Media
from src.domain.ports.repositories import MediaRepository
from src.domain.ports.services import StoragePort


class MediaService:
    def __init__(self, session: AsyncSession, media_repo: MediaRepository, storage: StoragePort) -> None:
        self._session = session
        self._media = media_repo
        self._storage = storage

    async def upload(
        self,
        filename: str,
        extension: str,
        content_type: str | None,
        chunks: AsyncIterator[bytes],
    ) -> Media:
        """Persist the stream to storage and record a Media row (one transaction)."""
        media_id = uuid.uuid4().hex
        path, size = await self._storage.save_stream(media_id, extension, chunks)

        media = Media(
            id=media_id,
            filename=filename,
            path=str(path),
            size_bytes=size,
            content_type=content_type,
        )
        saved = await self._media.add(media)
        await self._session.commit()
        return saved

    async def get(self, media_id: str) -> Media | None:
        return await self._media.get(media_id)
