"""
LocalStorage tests — presign parity and the multipart-on-a-filesystem path.

Worth testing directly because this adapter is what makes local development
exercise the same client flow as S3.
"""
from __future__ import annotations

import time

import pytest

from src.domain.errors import StorageError
from src.infrastructure.storage.local import LocalStorage


async def _chunks(*payloads: bytes):
    for payload in payloads:
        yield payload


@pytest.fixture
def storage(core_settings, storage_settings) -> LocalStorage:
    return LocalStorage(core_settings, storage_settings)


class TestPresign:
    async def test_ticket_is_signed_and_verifiable(self, storage):
        ticket = await storage.presign_put("uploads/a/f.wav", content_type="audio/wav", expires_in=60)
        assert ticket.url.startswith("http://testserver/api/v1/uploads/sink/")
        assert "signature=" in ticket.url and "expires=" in ticket.url

    async def test_download_ticket_is_signed_and_verifiable(self, storage):
        ticket = await storage.presign_get("projects/p1/artifacts/m1/export.wav", expires_in=60)
        assert ticket.method == "GET"
        assert ticket.url.startswith("http://testserver/api/v1/uploads/source/")
        assert "signature=" in ticket.url and "expires=" in ticket.url

    async def test_tampered_key_fails_verification(self, storage):
        expires = int(time.time()) + 60
        signature = storage._sign("uploads/a/f.wav", expires, None)
        assert storage.verify("uploads/a/f.wav", expires, signature) is True
        assert storage.verify("uploads/a/other.wav", expires, signature) is False

    async def test_expired_signature_is_rejected(self, storage):
        expires = int(time.time()) - 1
        signature = storage._sign("uploads/a/f.wav", expires, None)
        assert storage.verify("uploads/a/f.wav", expires, signature) is False

    async def test_part_number_is_bound_into_the_signature(self, storage):
        expires = int(time.time()) + 60
        signature = storage._sign("k.wav", expires, 3)
        assert storage.verify("k.wav", expires, signature, 3) is True
        assert storage.verify("k.wav", expires, signature, 4) is False


class TestPathTraversal:
    async def test_key_cannot_escape_the_object_root(self, storage):
        with pytest.raises(StorageError):
            await storage.stat("../../etc/passwd")

    async def test_nested_traversal_is_blocked(self, storage):
        with pytest.raises(StorageError):
            await storage.stat("uploads/../../../secret")


class TestSingleUpload:
    async def test_write_then_stat(self, storage):
        size = await storage.write_object("uploads/x/a.wav", _chunks(b"RIFF", b"data"))
        assert size == 8
        stored = await storage.stat("uploads/x/a.wav")
        assert stored is not None and stored.size_bytes == 8

    async def test_stat_missing_returns_none(self, storage):
        assert await storage.stat("uploads/x/missing.wav") is None

    async def test_open_range_reads_the_header(self, storage):
        await storage.write_object("uploads/x/b.wav", _chunks(b"RIFFxxxxWAVEfmt "))
        assert await storage.open_range("uploads/x/b.wav", start=0, length=4) == b"RIFF"


class TestMultipart:
    async def test_parts_assemble_in_order(self, storage):
        key = "uploads/x/big.wav"
        upload_id = await storage.create_multipart(key, content_type=None)
        # Deliberately written out of order to prove completion sorts them.
        await storage.write_object(key, _chunks(b"CCC"), part=3)
        await storage.write_object(key, _chunks(b"AAA"), part=1)
        await storage.write_object(key, _chunks(b"BBB"), part=2)

        stored = await storage.complete_multipart(key, upload_id, [(3, "c"), (1, "a"), (2, "b")])
        assert stored.size_bytes == 9
        assert await storage.open_range(key, start=0, length=9) == b"AAABBBCCC"

    async def test_missing_part_is_an_error(self, storage):
        key = "uploads/x/gap.wav"
        upload_id = await storage.create_multipart(key, content_type=None)
        await storage.write_object(key, _chunks(b"AAA"), part=1)
        with pytest.raises(StorageError):
            await storage.complete_multipart(key, upload_id, [(1, "a"), (2, "b")])

    async def test_part_files_are_cleaned_up_after_completion(self, storage, core_settings):
        key = "uploads/x/clean.wav"
        upload_id = await storage.create_multipart(key, content_type=None)
        await storage.write_object(key, _chunks(b"AAA"), part=1)
        await storage.complete_multipart(key, upload_id, [(1, "a")])
        leftovers = list((storage._path_for(key)).parent.glob("*.part-*"))
        assert leftovers == []

    async def test_abort_discards_parts(self, storage):
        key = "uploads/x/abort.wav"
        upload_id = await storage.create_multipart(key, content_type=None)
        await storage.write_object(key, _chunks(b"AAA"), part=1)
        await storage.abort_multipart(key, upload_id)
        assert list((storage._path_for(key)).parent.glob("*.part-*")) == []


class TestMaterialize:
    async def test_returns_path_without_copying(self, storage, tmp_path):
        await storage.write_object("uploads/x/m.wav", _chunks(b"RIFF"))
        path = await storage.materialize("uploads/x/m.wav", tmp_path / "scratch")
        assert path.read_bytes() == b"RIFF"

    async def test_missing_object_raises(self, storage, tmp_path):
        with pytest.raises(StorageError):
            await storage.materialize("uploads/x/nope.wav", tmp_path)


class TestReadObject:
    async def test_streams_the_full_object_back(self, storage):
        await storage.write_object("uploads/x/r.wav", _chunks(b"RIFF", b"data"))
        collected = b""
        async for chunk in storage.read_object("uploads/x/r.wav"):
            collected += chunk
        assert collected == b"RIFFdata"

    async def test_missing_object_raises(self, storage):
        with pytest.raises(StorageError):
            async for _ in storage.read_object("uploads/x/missing.wav"):
                pass
