from __future__ import annotations

from enum import Enum
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Single .env lives at the repo root (one file for docker compose and local
# `uv run` alike) — resolved absolutely so it's found regardless of cwd.
_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"
_CONFIG = SettingsConfigDict(env_file=_ENV_FILE, env_file_encoding="utf-8", extra="ignore")


class TranscriberProvider(str, Enum):
    LOCAL = "local"
    REMOTE = "remote"


class DiarizerProvider(str, Enum):
    OFF = "off"
    STUB = "stub"
    PYANNOTE = "pyannote"


class LLMProvider(str, Enum):
    OFF = "off"
    LOCAL = "local"
    REMOTE = "remote"


class StorageProvider(str, Enum):
    LOCAL = "local"
    S3 = "s3"


class BrokerProvider(str, Enum):
    REDIS = "redis"
    NATS = "nats"


class CoreSettings(BaseSettings):
    model_config = SettingsConfigDict(**_CONFIG, env_prefix="app_")

    name: str = "TakeFlow"
    debug: bool = False
    log_level: str = "INFO"
    cors_origins: str = "*"

    # Uploads
    data_dir: str = "/data"
    max_upload_bytes: int = 32 * 1024 * 1024 * 1024  # 32 GiB


class DBSettings(BaseSettings):
    model_config = _CONFIG

    database_url: str | None = None
    db_user: str = "postgres"
    db_password: str = Field(default="postgres")
    db_host: str = "db"
    db_port: int = 5432
    db_name: str = "takeflow"

    @property
    def url(self) -> str:
        if self.database_url:
            return self.database_url
        return (
            f"postgresql+psycopg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


class BrokerSettings(BaseSettings):
    model_config = SettingsConfigDict(**_CONFIG, env_prefix="broker_")

    provider: BrokerProvider = BrokerProvider.REDIS
    url: str = "redis://redis:6379"
    analysis_stream: str = "takeflow.analysis"
    export_stream: str = "takeflow.export"
    consumer_group: str = "takeflow-workers"


class OutboxSettings(BaseSettings):
    model_config = SettingsConfigDict(**_CONFIG, env_prefix="outbox_")

    poll_interval_seconds: float = 1.0
    batch_size: int = 50
    max_publish_attempts: int = 5


class TranscriptionSettings(BaseSettings):
    model_config = SettingsConfigDict(**_CONFIG, env_prefix="transcriber_")

    provider: TranscriberProvider = TranscriberProvider.LOCAL
    # Local (faster-whisper)
    model: str = "base"
    device: str = "auto"
    compute_type: str = "int8"
    cpu_threads: int = 0
    beam_size: int = 5
    model_cache_dir: str = "/models"
    # Remote
    remote_url: str = "http://whisper:9000/asr"


class DiarizationSettings(BaseSettings):
    model_config = SettingsConfigDict(**_CONFIG, env_prefix="diarizer_")

    provider: DiarizerProvider = DiarizerProvider.STUB
    hf_token: str | None = None
    remote_url: str | None = None


class LLMSettings(BaseSettings):
    model_config = SettingsConfigDict(**_CONFIG, env_prefix="llm_")

    provider: LLMProvider = LLMProvider.OFF
    url: str | None = None
    api_key: str | None = None
    model: str = "local"
    similarity_threshold: float = 0.75


_INSECURE_PRESIGN_SECRET = "dev-only-insecure-presign-secret"


class StorageSettings(BaseSettings):
    model_config = SettingsConfigDict(**_CONFIG, env_prefix="storage_")

    provider: StorageProvider = StorageProvider.LOCAL
    # S3/MinIO (used when provider=s3)
    s3_endpoint: str | None = None
    s3_bucket: str = "takeflow"
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    s3_region: str = "us-east-1"

    presign_ttl_seconds: int = 3600
    # Signing key for the local adapter's presign parity. MUST be overridden in
    # any deployment where the local adapter is reachable outside debug mode.
    # Not validated here: this class is instantiated eagerly as a module-level
    # singleton on import (including by tests), so a constructor-time check
    # would break every import that doesn't already have a real secret. The
    # check that matters — "are we actually about to serve traffic with the
    # placeholder?" — belongs at process startup instead; see
    # `require_secure_presign_secret` below, called from the API lifespan and
    # worker entrypoints.
    presign_secret: str = _INSECURE_PRESIGN_SECRET
    local_public_url: str = "http://localhost:8000"
    session_reap_after_seconds: int = 24 * 3600

    def require_secure_presign_secret(self, debug: bool) -> None:
        """
        Refuse to run with the placeholder presign secret outside debug mode.

        The local sink endpoint trusts this key to authenticate presigned
        PUTs; shipping the default in a reachable deployment lets anyone
        write to storage. Call this once at process startup (API lifespan,
        worker main) — not at settings construction time.
        """
        if self.provider is not StorageProvider.LOCAL:
            return
        if self.presign_secret != _INSECURE_PRESIGN_SECRET:
            return
        if debug:
            return
        raise RuntimeError(
            "storage_presign_secret must be set to a real secret when "
            "STORAGE_PROVIDER=local and APP_DEBUG=false. Refusing to start "
            "with the insecure default outside debug mode."
        )


class AnalysisSettings(BaseSettings):
    model_config = SettingsConfigDict(**_CONFIG, env_prefix="analysis_")

    silence_min_duration: float = 0.6
    silence_threshold_db: float = -35.0
    silence_keep_padding: float = 0.05
    # Bad-take (duplicate phrase) detection — fuzzy text match, no LLM.
    bad_take_similarity_threshold: int = 85
    bad_take_min_words: int = 3


class MasteringSettings(BaseSettings):
    """Export mastering chain: noise gate -> highpass -> EQ -> compressor -> LUFS."""

    model_config = SettingsConfigDict(**_CONFIG, env_prefix="mastering_")

    noise_gate_threshold_db: float = -40.0
    highpass_hz: float = 80.0
    eq_frequency_hz: float = 3000.0
    eq_gain_db: float = 2.0
    eq_q: float = 0.7
    compressor_threshold_db: float = -18.0
    compressor_ratio: float = 3.0
    # -16 LUFS is the common streaming/podcast target (vs -23 LUFS broadcast).
    target_lufs: float = -16.0


core_settings = CoreSettings()
db_settings = DBSettings()
broker_settings = BrokerSettings()
outbox_settings = OutboxSettings()
transcription_settings = TranscriptionSettings()
diarization_settings = DiarizationSettings()
llm_settings = LLMSettings()
storage_settings = StorageSettings()
analysis_settings = AnalysisSettings()
mastering_settings = MasteringSettings()
