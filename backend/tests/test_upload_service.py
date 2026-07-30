"""
UploadService tests — the trust boundary.

Focused on what the service must never take on faith: the declared size, the
declared type, and the client's claim that it finished. Storage and repositories
are in-memory fakes so the rules are tested without Postgres or S3.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.application.services.upload_service import UploadService
from src.domain.entities import (
    Media,
    PartUploadTicket,
    StoredObject,
    UploadSession,
    UploadTicket,
)
from src.domain.enums import UploadMode, UploadStatus
from src.domain.errors import (
    FileTooLargeError,
    UnsupportedMediaError,
    UploadNotFinishedError,
    UploadSessionNotFoundError,
    UploadSizeMismatchError,
    UploadStateError,
)

WAV_HEADER = b"RIFF\x00\x00\x00\x00WAVE"


class FakeSession:
    """Stands in for AsyncSession — only commit() is exercised here."""

    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


class FakeStorage:
    def __init__(self) -> None:
        self.objects: dict[str, StoredObject] = {}
        self.headers: dict[str, bytes] = {}
        self.multiparts: dict[str, str] = {}
        self.aborted: list[str] = []
        self.deleted: list[str] = []

    async def presign_put(self, key, *, content_type, expires_in):
        return UploadTicket(url=f"https://storage.test/{key}", headers={})

    async def create_multipart(self, key, *, content_type):
        self.multiparts[key] = "upload-1"
        return "upload-1"

    async def presign_parts(self, key, upload_id, *, part_numbers, expires_in):
        return [PartUploadTicket(part_number=n, url=f"https://storage.test/{key}?p={n}") for n in part_numbers]

    async def complete_multipart(self, key, upload_id, parts):
        stored = self.objects.get(key)
        if stored is None:
            raise AssertionError("test must stage the assembled object")
        return stored

    async def abort_multipart(self, key, upload_id):
        self.aborted.append(key)

    async def stat(self, key):
        return self.objects.get(key)

    async def open_range(self, key, *, start, length):
        return self.headers.get(key, WAV_HEADER)[start : start + length]

    async def materialize(self, key, dest_dir: Path) -> Path:
        return dest_dir / key

    async def save_stream(self, key, chunks):
        raise NotImplementedError

    async def delete(self, key):
        self.deleted.append(key)
        self.objects.pop(key, None)


class FakeSessions:
    def __init__(self) -> None:
        self.rows: dict[str, UploadSession] = {}

    async def add(self, session: UploadSession) -> UploadSession:
        self.rows[session.id] = session
        return session

    async def get(self, session_id: str) -> UploadSession | None:
        return self.rows.get(session_id)

    async def set_status(self, session_id, status, *, media_id=None):
        row = self.rows[session_id]
        row.status = status
        if media_id is not None:
            row.media_id = media_id

    async def fetch_stale(self, limit):
        return [r for r in self.rows.values() if r.status is UploadStatus.INITIATED][:limit]


class FakeMedia:
    def __init__(self) -> None:
        self.rows: dict[str, Media] = {}

    async def add(self, media: Media) -> Media:
        self.rows[media.id] = media
        return media

    async def get(self, media_id: str) -> Media | None:
        return self.rows.get(media_id)


@pytest.fixture
def ctx(core_settings, storage_settings):
    session, sessions, media, storage = FakeSession(), FakeSessions(), FakeMedia(), FakeStorage()
    service = UploadService(session, sessions, media, storage, core_settings, storage_settings)
    return service, storage, sessions, media


class TestInit:
    async def test_small_file_gets_a_single_ticket(self, ctx):
        service, *_ = ctx
        session, single, parts = await service.init(
            filename="take.wav", declared_size=1024, content_type="audio/wav"
        )
        assert session.mode is UploadMode.SINGLE
        assert single is not None and parts == []

    async def test_large_file_gets_part_tickets(self, ctx):
        service, *_ = ctx
        session, single, parts = await service.init(
            filename="scene.mp4", declared_size=40 * 1024 * 1024, content_type="video/mp4"
        )
        assert session.mode is UploadMode.MULTIPART
        assert single is None
        assert len(parts) == session.part_count
        assert session.upload_id == "upload-1"

    async def test_rejects_bad_extension_before_touching_storage(self, ctx):
        service, storage, *_ = ctx
        with pytest.raises(UnsupportedMediaError):
            await service.init(filename="virus.exe", declared_size=10, content_type=None)
        assert storage.multiparts == {}

    async def test_rejects_oversize_declaration(self, ctx):
        service, storage, *_ = ctx
        with pytest.raises(FileTooLargeError):
            await service.init(filename="huge.wav", declared_size=999 * 1024 * 1024 * 1024, content_type=None)
        assert storage.multiparts == {}


class TestComplete:
    async def test_single_upload_creates_media(self, ctx):
        service, storage, _, media_repo = ctx
        session, *_ = await service.init(filename="take.wav", declared_size=9, content_type="audio/wav")
        storage.objects[session.storage_key] = StoredObject(key=session.storage_key, size_bytes=9)

        media = await service.complete(session.id)
        assert media.size_bytes == 9
        assert media.storage_key == session.storage_key
        assert await media_repo.get(media.id) is not None

    async def test_missing_object_is_a_conflict(self, ctx):
        service, *_ = ctx
        session, *_ = await service.init(filename="take.wav", declared_size=9, content_type=None)
        with pytest.raises(UploadNotFinishedError):
            await service.complete(session.id)

    async def test_size_mismatch_aborts_and_raises(self, ctx):
        """Storage is the authority; a lying client loses the object."""
        service, storage, sessions, _ = ctx
        session, *_ = await service.init(filename="take.wav", declared_size=9, content_type=None)
        storage.objects[session.storage_key] = StoredObject(key=session.storage_key, size_bytes=5)

        with pytest.raises(UploadSizeMismatchError):
            await service.complete(session.id)
        assert sessions.rows[session.id].status is UploadStatus.ABORTED
        assert session.storage_key in storage.deleted

    async def test_renamed_file_is_rejected_by_sniffing(self, ctx):
        service, storage, sessions, _ = ctx
        session, *_ = await service.init(filename="take.wav", declared_size=4, content_type=None)
        storage.objects[session.storage_key] = StoredObject(key=session.storage_key, size_bytes=4)
        storage.headers[session.storage_key] = b"MZ\x90\x00"  # a PE executable

        with pytest.raises(UnsupportedMediaError):
            await service.complete(session.id)
        assert sessions.rows[session.id].status is UploadStatus.ABORTED

    async def test_is_idempotent(self, ctx):
        """A client retrying after a dropped response must not get two media rows."""
        service, storage, _, media_repo = ctx
        session, *_ = await service.init(filename="take.wav", declared_size=9, content_type=None)
        storage.objects[session.storage_key] = StoredObject(key=session.storage_key, size_bytes=9)

        first = await service.complete(session.id)
        second = await service.complete(session.id)
        assert first.id == second.id
        assert len(media_repo.rows) == 1

    async def test_multipart_requires_the_part_list(self, ctx):
        service, storage, *_ = ctx
        session, *_ = await service.init(
            filename="scene.mp4", declared_size=40 * 1024 * 1024, content_type=None
        )
        with pytest.raises(UploadNotFinishedError):
            await service.complete(session.id, [])

    async def test_multipart_rejects_a_short_part_list(self, ctx):
        service, storage, *_ = ctx
        session, *_ = await service.init(
            filename="scene.mp4", declared_size=40 * 1024 * 1024, content_type=None
        )
        with pytest.raises(UploadNotFinishedError):
            await service.complete(session.id, [(1, "etag")])

    async def test_unknown_session_is_not_found(self, ctx):
        service, *_ = ctx
        with pytest.raises(UploadSessionNotFoundError):
            await service.complete("nope")

    async def test_aborted_session_cannot_be_completed(self, ctx):
        service, storage, sessions, _ = ctx
        session, *_ = await service.init(filename="take.wav", declared_size=9, content_type=None)
        await service.abort(session.id)
        storage.objects[session.storage_key] = StoredObject(key=session.storage_key, size_bytes=9)
        with pytest.raises(UploadStateError):
            await service.complete(session.id)


class TestAbortAndReap:
    async def test_abort_discards_multipart_parts(self, ctx):
        service, storage, sessions, _ = ctx
        session, *_ = await service.init(
            filename="scene.mp4", declared_size=40 * 1024 * 1024, content_type=None
        )
        await service.abort(session.id)
        assert session.storage_key in storage.aborted
        assert sessions.rows[session.id].status is UploadStatus.ABORTED

    async def test_abort_is_a_noop_for_finished_sessions(self, ctx):
        service, storage, _, _ = ctx
        session, *_ = await service.init(filename="take.wav", declared_size=9, content_type=None)
        storage.objects[session.storage_key] = StoredObject(key=session.storage_key, size_bytes=9)
        await service.complete(session.id)
        await service.abort(session.id)  # must not delete the completed object
        assert session.storage_key not in storage.deleted

    async def test_reaper_expires_abandoned_sessions(self, ctx):
        """Without this, multipart parts sit in the bucket and are billed forever."""
        service, storage, sessions, _ = ctx
        session, *_ = await service.init(
            filename="scene.mp4", declared_size=40 * 1024 * 1024, content_type=None
        )
        reaped = await service.reap_stale()
        assert reaped == 1
        assert sessions.rows[session.id].status is UploadStatus.EXPIRED
        assert session.storage_key in storage.aborted
