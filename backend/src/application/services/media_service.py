"""
MediaService — use-cases around uploaded source files.

Upload negotiation lives in UploadService (bytes go client -> storage directly).
This service covers reads and derived-artifact registration.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.entities import Media
from src.domain.ports.repositories import MediaRepository
from src.domain.ports.services import StoragePort


class MediaService:
    def __init__(self, session: AsyncSession, media_repo: MediaRepository, storage: StoragePort) -> None:
        self._session = session
        self._media = media_repo
        self._storage = storage

    async def get(self, media_id: str) -> Media | None:
        return await self._media.get(media_id)
