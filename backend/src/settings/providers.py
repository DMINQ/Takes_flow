"""
Provider factories — resolve settings into concrete adapters.

This is the one place that knows which implementation backs each port. Switching
local↔remote, fs↔s3, stub↔pyannote is a settings change here; the rest of the app
depends only on the port Protocols. Adapters are cached (built once per process).
"""
from __future__ import annotations

from functools import lru_cache

from src.domain.ports.services import (
    AudioEnginePort,
    DiarizerPort,
    StoragePort,
    TranscriberPort,
)
from src.settings.config import (
    DiarizerProvider,
    StorageProvider,
    TranscriberProvider,
    core_settings,
    diarization_settings,
    storage_settings,
    transcription_settings,
)


@lru_cache
def get_transcriber() -> TranscriberPort:
    if transcription_settings.provider is TranscriberProvider.LOCAL:
        from src.infrastructure.transcribers.local import LocalTranscriber

        return LocalTranscriber(transcription_settings)
    # provider == REMOTE
    from src.infrastructure.transcribers.remote import RemoteTranscriber

    return RemoteTranscriber(transcription_settings)


@lru_cache
def get_diarizer() -> DiarizerPort:
    provider = diarization_settings.provider
    if provider is DiarizerProvider.PYANNOTE:
        # Imported lazily so the heavy dependency isn't required unless enabled.
        from src.infrastructure.diarizers.pyannote import PyannoteDiarizer

        return PyannoteDiarizer(diarization_settings)
    # OFF and STUB both use the single-speaker stub for now.
    from src.infrastructure.diarizers.stub import StubDiarizer

    return StubDiarizer()


@lru_cache
def get_storage() -> StoragePort:
    if storage_settings.provider is StorageProvider.S3:
        from src.infrastructure.storage.s3 import S3Storage

        return S3Storage(storage_settings)
    from src.infrastructure.storage.local import LocalStorage

    return LocalStorage(core_settings)


@lru_cache
def get_audio_engine() -> AudioEnginePort:
    # Single implementation for now (ffmpeg + pedalboard); kept behind the factory
    # so a remote/worker-pool variant can be swapped in later.
    from src.infrastructure.audio.engine import FfmpegPedalboardEngine

    return FfmpegPedalboardEngine()
