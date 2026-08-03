"""
MediaService — use-cases around uploaded source files.

Upload negotiation lives in UploadService (bytes go client -> storage directly).
This service covers reads and derived-artifact registration.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.entities import Media, UploadTicket
from src.domain.enums import ArtifactKind
from src.domain.errors import MediaNotFoundError
from src.domain.ports.repositories import ArtifactRepository, MediaRepository
from src.domain.ports.services import StoragePort


class MediaService:
    def __init__(
        self,
        session: AsyncSession,
        media_repo: MediaRepository,
        storage: StoragePort,
        artifact_repo: ArtifactRepository | None = None,
    ) -> None:
        self._session = session
        self._media = media_repo
        self._storage = storage
        self._artifacts = artifact_repo

    async def get(self, media_id: str) -> Media | None:
        return await self._media.get(media_id)

    async def get_source_download(self, media_id: str, *, expires_in: int = 3600) -> UploadTicket:
        """Mint a presigned GET for the original uploaded source file of `media_id`."""
        media = await self._media.get(media_id)
        if media is None:
            raise MediaNotFoundError(f"No media found for id '{media_id}'.")
        return await self._storage.presign_get(media.storage_key, expires_in=expires_in)

    async def get_export_download(self, media_id: str, *, expires_in: int = 3600) -> UploadTicket:
        """Mint a presigned GET for the most recent EXPORT artifact of `media_id`."""
        if self._artifacts is None:
            raise MediaNotFoundError("Artifact lookup is not configured.")

        media = await self._media.get(media_id)
        if media is None:
            raise MediaNotFoundError(f"No media found for id '{media_id}'.")

        artifact = await self._artifacts.get(media_id, ArtifactKind.EXPORT)
        if artifact is None:
            raise MediaNotFoundError(
                f"No export artifact for media '{media_id}'. Run an EXPORT job first."
            )
        return await self._storage.presign_get(artifact.storage_key, expires_in=expires_in)
