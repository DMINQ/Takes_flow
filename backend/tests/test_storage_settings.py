"""
StorageSettings.require_secure_presign_secret — the startup guard against
shipping the placeholder presign secret.

Constructor-time validation was rejected: `StorageSettings` is instantiated
eagerly as a module-level singleton on import, so it must always be
constructible even without a real secret configured. The guard runs once at
process startup instead (API lifespan, worker main).
"""
from __future__ import annotations

import pytest

from src.settings.config import StorageProvider, StorageSettings


def test_insecure_default_rejected_outside_debug() -> None:
    settings = StorageSettings(provider=StorageProvider.LOCAL)
    with pytest.raises(RuntimeError, match="insecure default"):
        settings.require_secure_presign_secret(debug=False)


def test_insecure_default_allowed_in_debug() -> None:
    settings = StorageSettings(provider=StorageProvider.LOCAL)
    settings.require_secure_presign_secret(debug=True)  # no raise


def test_real_secret_allowed_outside_debug() -> None:
    settings = StorageSettings(provider=StorageProvider.LOCAL, presign_secret="a-real-secret")
    settings.require_secure_presign_secret(debug=False)  # no raise


def test_s3_provider_never_checked() -> None:
    # The local sink is the thing being protected; s3 doesn't expose it.
    settings = StorageSettings(provider=StorageProvider.S3)
    settings.require_secure_presign_secret(debug=False)  # no raise
