"""Shared fixtures. Settings are pinned so tests never read a developer's .env."""
from __future__ import annotations

import pytest

from src.settings.config import CoreSettings, StorageSettings


@pytest.fixture
def core_settings(tmp_path) -> CoreSettings:
    return CoreSettings(data_dir=str(tmp_path), max_upload_bytes=64 * 1024 * 1024)


@pytest.fixture
def storage_settings() -> StorageSettings:
    return StorageSettings(
        presign_secret="test-secret",
        local_public_url="http://testserver",
        presign_ttl_seconds=60,
    )
