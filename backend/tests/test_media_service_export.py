"""
MediaService export-download tests — `get_export_download`.

Fakes stand in for MediaRepository/ArtifactRepository/StoragePort so the
"mint a presigned GET for the latest EXPORT artifact" logic is tested without
Postgres or S3.
"""
from __future__ import annotations

import pytest

from src.application.services.media_service import MediaService
from src.domain.entities import Artifact, Media, UploadTicket
from src.domain.enums import ArtifactKind
from src.domain.errors import MediaNotFoundError


class FakeSession:
    async def commit(self) -> None:
        pass


class FakeMediaRepository:
    def __init__(self, media: Media | None) -> None:
        self._media = media

    async def add(self, media):
        raise NotImplementedError

    async def get(self, media_id: str) -> Media | None:
        return self._media


class FakeArtifactRepository:
    def __init__(self, artifact: Artifact | None) -> None:
        self._artifact = artifact

    async def add(self, artifact):
        raise NotImplementedError

    async def get(self, media_id, kind):
        return self._artifact


class FakeStorage:
    async def presign_get(self, key: str, *, expires_in: int) -> UploadTicket:
        return UploadTicket(url=f"https://storage.test/{key}", method="GET")


def _media() -> Media:
    return Media(id="media-1", project_id="project-1", filename="in.wav", storage_key="k", size_bytes=10)


def _artifact() -> Artifact:
    return Artifact(
        id="art-1", media_id="media-1", job_id="job-1", kind=ArtifactKind.EXPORT,
        storage_key="projects/project-1/artifacts/media-1/export.wav",
    )


class TestGetExportDownload:
    async def test_returns_presigned_ticket_for_latest_export(self):
        service = MediaService(FakeSession(), FakeMediaRepository(_media()), FakeStorage(), FakeArtifactRepository(_artifact()))

        ticket = await service.get_export_download("media-1")

        assert ticket.method == "GET"
        assert "export.wav" in ticket.url

    async def test_missing_media_raises(self):
        service = MediaService(FakeSession(), FakeMediaRepository(None), FakeStorage(), FakeArtifactRepository(None))

        with pytest.raises(MediaNotFoundError):
            await service.get_export_download("media-1")

    async def test_no_export_artifact_yet_raises(self):
        service = MediaService(FakeSession(), FakeMediaRepository(_media()), FakeStorage(), FakeArtifactRepository(None))

        with pytest.raises(MediaNotFoundError):
            await service.get_export_download("media-1")

    async def test_missing_artifact_repo_raises(self):
        service = MediaService(FakeSession(), FakeMediaRepository(_media()), FakeStorage())

        with pytest.raises(MediaNotFoundError):
            await service.get_export_download("media-1")
