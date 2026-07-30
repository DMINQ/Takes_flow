"""
Integration test for the uploads router — the full client-visible cycle.

Exercises init -> PUT to the local sink -> complete through real HTTP calls
against the ASGI app (httpx.ASGITransport), using the real LocalStorage
adapter so the presign/verify contract is tested end to end. The DB layer is
faked via dependency_overrides (see FakeSession/FakeSessions/FakeMedia in
test_upload_service.py) — this test's job is the router + HTTP + storage
wiring, not persistence, which is already covered by test_upload_service.py.
"""
from __future__ import annotations

import httpx
import pytest

from src.api.deps import storage_provider, upload_service
from src.api.main import app
from src.application.services.upload_service import UploadService
from src.domain.entities import Media
from src.domain.enums import UploadStatus
from src.infrastructure.storage.local import LocalStorage
from src.settings.config import CoreSettings, StorageSettings


class _FakeSession:
    async def commit(self) -> None:
        pass


class _FakeSessions:
    def __init__(self) -> None:
        self.rows: dict = {}

    async def add(self, session):
        self.rows[session.id] = session
        return session

    async def get(self, session_id: str):
        return self.rows.get(session_id)

    async def set_status(self, session_id, status, *, media_id=None):
        row = self.rows[session_id]
        row.status = status
        if media_id is not None:
            row.media_id = media_id

    async def fetch_stale(self, limit):
        return [r for r in self.rows.values() if r.status is UploadStatus.INITIATED][:limit]


class _FakeMedia:
    def __init__(self) -> None:
        self.rows: dict[str, Media] = {}

    async def add(self, media: Media) -> Media:
        self.rows[media.id] = media
        return media

    async def get(self, media_id: str) -> Media | None:
        return self.rows.get(media_id)


@pytest.fixture
async def client(tmp_path):
    core = CoreSettings(data_dir=str(tmp_path), max_upload_bytes=64 * 1024 * 1024)
    storage_cfg = StorageSettings(
        presign_secret="test-secret",
        local_public_url="http://testserver",
        presign_ttl_seconds=60,
    )
    storage = LocalStorage(core, storage_cfg)
    sessions, media = _FakeSessions(), _FakeMedia()

    def _storage_override():
        return storage

    def _upload_service_override():
        return UploadService(_FakeSession(), sessions, media, storage, core, storage_cfg)

    app.dependency_overrides[storage_provider] = _storage_override
    app.dependency_overrides[upload_service] = _upload_service_override
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
    app.dependency_overrides.clear()


class TestSingleUploadCycle:
    async def test_full_cycle_init_put_complete(self, client):
        init_resp = await client.post(
            "/api/v1/uploads",
            json={"filename": "take.wav", "size_bytes": 8, "content_type": "audio/wav"},
        )
        assert init_resp.status_code == 201
        body = init_resp.json()
        assert body["mode"] == "single"
        assert body["single"] is not None

        put_url = body["single"]["url"]
        put_path = put_url.replace("http://testserver", "")
        put_resp = await client.put(put_path, content=b"RIFFdata")
        assert put_resp.status_code == 200

        complete_resp = await client.post(
            f"/api/v1/uploads/{body['session_id']}/complete", json={"parts": []}
        )
        assert complete_resp.status_code == 200
        media = complete_resp.json()
        assert media["size_bytes"] == 8
        assert media["filename"] == "take.wav"

    async def test_complete_before_put_is_a_conflict(self, client):
        init_resp = await client.post(
            "/api/v1/uploads",
            json={"filename": "take.wav", "size_bytes": 8, "content_type": "audio/wav"},
        )
        session_id = init_resp.json()["session_id"]

        complete_resp = await client.post(
            f"/api/v1/uploads/{session_id}/complete", json={"parts": []}
        )
        assert complete_resp.status_code == 409

    async def test_sink_rejects_bad_signature(self, client):
        init_resp = await client.post(
            "/api/v1/uploads",
            json={"filename": "take.wav", "size_bytes": 8, "content_type": "audio/wav"},
        )
        put_url = init_resp.json()["single"]["url"]
        tampered = put_url.replace("http://testserver", "").replace("signature=", "signature=deadbeef")
        put_resp = await client.put(tampered, content=b"RIFFdata")
        assert put_resp.status_code == 403


class TestAbort:
    async def test_abort_then_complete_is_not_found_after_expiry_window(self, client):
        init_resp = await client.post(
            "/api/v1/uploads",
            json={"filename": "take.wav", "size_bytes": 8, "content_type": "audio/wav"},
        )
        session_id = init_resp.json()["session_id"]

        abort_resp = await client.delete(f"/api/v1/uploads/{session_id}")
        assert abort_resp.status_code == 204
        assert abort_resp.content == b""

        # A second abort on an already-aborted session is still a no-op, not an error.
        second = await client.delete(f"/api/v1/uploads/{session_id}")
        assert second.status_code == 204

    async def test_abort_unknown_session_is_not_found(self, client):
        resp = await client.delete("/api/v1/uploads/does-not-exist")
        assert resp.status_code == 404


class TestMultipartUploadCycle:
    async def test_full_cycle_with_two_parts(self, client):
        size = 40 * 1024 * 1024
        init_resp = await client.post(
            "/api/v1/uploads",
            json={"filename": "scene.mp4", "size_bytes": size, "content_type": "video/mp4"},
        )
        assert init_resp.status_code == 201
        body = init_resp.json()
        assert body["mode"] == "multipart"
        assert body["single"] is None
        parts = body["parts"]
        assert len(parts) == body["part_count"]

        part_size = body["part_size"]
        remaining = size
        completed_parts = []
        for part in parts:
            chunk_len = min(part_size, remaining)
            filler = bytes([part["part_number"] % 256])
            if part["part_number"] == 1:
                # ISO-BMFF 'ftyp' box at offset 4 — required for the mp4 sniff check.
                header = b"\x00\x00\x00\x18ftypmp42"
                payload = header + filler * (chunk_len - len(header))
            else:
                payload = filler * chunk_len
            put_path = part["url"].replace("http://testserver", "")
            put_resp = await client.put(put_path, content=payload)
            assert put_resp.status_code == 200
            completed_parts.append({"part_number": part["part_number"], "etag": put_resp.json()["etag"]})
            remaining -= chunk_len

        complete_resp = await client.post(
            f"/api/v1/uploads/{body['session_id']}/complete", json={"parts": completed_parts}
        )
        assert complete_resp.status_code == 200, complete_resp.json()
        media = complete_resp.json()
        assert media["size_bytes"] == size
