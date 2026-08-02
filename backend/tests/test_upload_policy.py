"""
Upload policy tests — the domain rules that make multi-hour media work.

These are pure functions, so they need no database, storage or event loop.
"""
from __future__ import annotations

import pytest

from src.domain import upload_policy as policy
from src.domain.enums import UploadMode
from src.domain.errors import FileTooLargeError, UnsupportedMediaError

GIB = 1024 * 1024 * 1024


class TestValidateExtension:
    def test_accepts_known_media(self):
        assert policy.validate_extension("take.WAV") == ".wav"
        assert policy.validate_extension("scene.mp4") == ".mp4"

    def test_rejects_unknown(self):
        with pytest.raises(UnsupportedMediaError):
            policy.validate_extension("payload.exe")

    def test_rejects_missing_extension(self):
        with pytest.raises(UnsupportedMediaError):
            policy.validate_extension("noext")


class TestDeclaredSize:
    def test_rejects_over_cap_before_any_transfer(self):
        with pytest.raises(FileTooLargeError):
            policy.validate_declared_size(11, max_bytes=10)

    def test_rejects_zero(self):
        with pytest.raises(FileTooLargeError):
            policy.validate_declared_size(0, max_bytes=10)

    def test_accepts_at_cap(self):
        policy.validate_declared_size(10, max_bytes=10)


class TestPlanUpload:
    def test_small_file_uses_single_put(self):
        mode, part_size, count = policy.plan_upload(5 * 1024 * 1024)
        assert mode is UploadMode.SINGLE
        assert part_size is None and count is None

    def test_large_file_uses_multipart(self):
        mode, part_size, count = policy.plan_upload(1 * GIB)
        assert mode is UploadMode.MULTIPART
        assert part_size == policy.DEFAULT_PART_SIZE
        assert count == 64

    def test_three_hour_video_stays_within_s3_part_limit(self):
        """A ~20 GiB file must not exceed 10 000 parts — this is the real constraint."""
        mode, part_size, count = policy.plan_upload(20 * GIB)
        assert mode is UploadMode.MULTIPART
        assert count <= policy.MAX_PARTS
        assert part_size >= policy.MIN_PART_SIZE
        assert part_size * count >= 20 * GIB

    def test_enormous_file_grows_part_size_instead_of_part_count(self):
        _, part_size, count = policy.plan_upload(500 * GIB)
        assert count <= policy.MAX_PARTS
        assert part_size > policy.DEFAULT_PART_SIZE

    def test_parts_always_cover_the_whole_file(self):
        for size in (33 * 1024 * 1024, 700 * 1024 * 1024, 9 * GIB):
            _, part_size, count = policy.plan_upload(size)
            assert part_size * count >= size


class TestSniff:
    def test_wav_header_matches(self):
        assert policy.sniff_matches_extension(b"RIFF\x00\x00\x00\x00WAVE", ".wav")

    def test_renamed_file_is_rejected(self):
        """An .exe renamed to .wav must not pass."""
        assert not policy.sniff_matches_extension(b"MZ\x90\x00", ".wav")

    def test_mp4_ftyp_at_offset_four(self):
        assert policy.sniff_matches_extension(b"\x00\x00\x00 ftypisom", ".mp4")

    def test_matroska_magic(self):
        assert policy.sniff_matches_extension(b"\x1a\x45\xdf\xa3\x01\x00", ".mkv")


class TestStorageKey:
    def test_is_project_scoped_and_date_partitioned(self):
        key = policy.build_storage_key("proj1", "abc123", ".wav")
        assert key.startswith("projects/proj1/uploads/")
        assert key.endswith("abc123.wav")
        assert key.count("/") == 6  # projects/<id>/uploads/YYYY/MM/DD/file


class TestArtifactKey:
    def test_is_project_and_media_scoped(self):
        from src.domain.enums import ArtifactKind

        key = policy.build_artifact_key("proj1", "media1", ArtifactKind.TRANSCRIPT, ".json")
        assert key == "projects/proj1/artifacts/media1/transcript.json"
