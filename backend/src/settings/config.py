"""
Application settings — composed from focused sub-settings via pydantic-settings.

Design
------
* Each concern is its own `BaseSettings` subclass sharing one config dict, and is
  instantiated into a module-level singleton. Consumers import the specific
  singleton they need (`from src.settings.config import db_settings`).
* Every "local vs remote" choice is a plain env-driven field: swap a provider
  enum and/or a URL, no code change. See `providers.py` for how these select
  concrete adapters.
* Secrets have NO usable defaults — pydantic raises if they're missing in a
  context that needs them, so we never ship a real-looking credential.
"""
from __future__ import annotations

from enum import Enum

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Shared across every sub-settings class: read from .env, ignore unknown keys.
_CONFIG = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


# --- Provider enums: the swap points ------------------------------------------------
class TranscriberProvider(str, Enum):
    LOCAL = "local"    # faster-whisper in-process
    REMOTE = "remote"  # external HTTP ASR service


class DiarizerProvider(str, Enum):
    OFF = "off"        # single-speaker; skip diarization
    STUB = "stub"      # port implemented, returns one speaker (default for now)
    PYANNOTE = "pyannote"


class LLMProvider(str, Enum):
    OFF = "off"        # bad-take detection falls back to string similarity only
    LOCAL = "local"
    REMOTE = "remote"


class StorageProvider(str, Enum):
    LOCAL = "local"
    S3 = "s3"


class BrokerProvider(str, Enum):
    REDIS = "redis"
    NATS = "nats"


# --- Sub-settings -------------------------------------------------------------------
class CoreSettings(BaseSettings):
    model_config = SettingsConfigDict(**_CONFIG, env_prefix="app_")

    name: str = "TakeFlow"
    debug: bool = False
    log_level: str = "INFO"
    cors_origins: str = "*"  # comma-separated; tighten in production

    # Uploads
    data_dir: str = "/data"
    # Ceiling for a declared upload size. 3 hours of 1080p lands around 10-20 GiB,
    # so this is generous by design; it is enforced before any byte moves and
    # re-checked against storage afterwards.
    max_upload_bytes: int = 32 * 1024 * 1024 * 1024  # 32 GiB


class DBSettings(BaseSettings):
    model_config = _CONFIG

    # Full URL wins if provided (remote DB "by link"); otherwise assembled from parts.
    database_url: str | None = None
    db_user: str = "postgres"
    db_password: str = Field(default="postgres")  # override in .env for real deploys
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
    # Stream/subject names for the analysis and export pipelines.
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
    model: str = "base"              # tiny|base|small|medium|large-v3
    device: str = "auto"             # auto|cpu|cuda
    compute_type: str = "int8"       # int8 (CPU) | float16 (GPU)
    cpu_threads: int = 0
    beam_size: int = 5
    model_cache_dir: str = "/models"
    # Remote
    remote_url: str = "http://whisper:9000/asr"


class DiarizationSettings(BaseSettings):
    model_config = SettingsConfigDict(**_CONFIG, env_prefix="diarizer_")

    provider: DiarizerProvider = DiarizerProvider.STUB
    hf_token: str | None = None       # required only for pyannote
    remote_url: str | None = None


class LLMSettings(BaseSettings):
    model_config = SettingsConfigDict(**_CONFIG, env_prefix="llm_")

    provider: LLMProvider = LLMProvider.OFF
    url: str | None = None
    api_key: str | None = None
    model: str = "local"
    # Similarity threshold for treating two phrases as the same take (0..1).
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

    # --- presigned direct upload ---
    # TTL of an upload ticket. Long enough for a slow client to finish one part,
    # short enough that a leaked URL expires quickly.
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
    # Public base URL the client can reach for local-adapter sink endpoints.
    local_public_url: str = "http://localhost:8000"
    # Abandoned INITIATED sessions are aborted after this long.
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
    """Tunables for the silence / bad-take detection plugins (Phase 2)."""

    model_config = SettingsConfigDict(**_CONFIG, env_prefix="analysis_")

    silence_min_duration: float = 0.6   # seconds below threshold to count as a cut
    silence_threshold_db: float = -35.0  # dBFS
    silence_keep_padding: float = 0.05   # keep a little air around kept speech


# --- Singletons ---------------------------------------------------------------------
core_settings = CoreSettings()
db_settings = DBSettings()
broker_settings = BrokerSettings()
outbox_settings = OutboxSettings()
transcription_settings = TranscriptionSettings()
diarization_settings = DiarizationSettings()
llm_settings = LLMSettings()
storage_settings = StorageSettings()
analysis_settings = AnalysisSettings()
