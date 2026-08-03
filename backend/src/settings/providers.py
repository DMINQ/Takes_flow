from __future__ import annotations

from functools import lru_cache

from src.domain.ports.services import (
    AudioEnginePort,
    DiarizerPort,
    LLMPort,
    StoragePort,
    TranscriberPort,
)
from src.settings.config import (
    DiarizerProvider,
    LLMProvider,
    StorageProvider,
    TranscriberProvider,
    core_settings,
    diarization_settings,
    llm_settings,
    mastering_settings,
    storage_settings,
    transcription_settings,
)


@lru_cache
def get_transcriber() -> TranscriberPort:
    if transcription_settings.provider is TranscriberProvider.LOCAL:
        from src.infrastructure.transcribers.local import LocalTranscriber

        return LocalTranscriber(transcription_settings)
    from src.infrastructure.transcribers.remote import RemoteTranscriber

    return RemoteTranscriber(transcription_settings)


@lru_cache
def get_diarizer() -> DiarizerPort:
    provider = diarization_settings.provider
    if provider is DiarizerProvider.PYANNOTE:
        from src.infrastructure.diarizers.pyannote import PyannoteDiarizer

        return PyannoteDiarizer(diarization_settings)
    if provider is DiarizerProvider.CUSTOM:
        from src.infrastructure.diarizers.custom import CustomDiarizer

        return CustomDiarizer(diarization_settings)
    from src.infrastructure.diarizers.stub import StubDiarizer

    return StubDiarizer(get_audio_engine())


@lru_cache
def get_storage() -> StoragePort:
    if storage_settings.provider is StorageProvider.S3:
        from src.infrastructure.storage.s3 import S3Storage

        return S3Storage(storage_settings)
    from src.infrastructure.storage.local import LocalStorage

    return LocalStorage(core_settings, storage_settings)


@lru_cache
def get_audio_engine() -> AudioEnginePort:
    from src.infrastructure.audio.engine import FfmpegPedalboardEngine

    return FfmpegPedalboardEngine(mastering_settings)


@lru_cache
def get_llm() -> LLMPort | None:
    """Returns None when LLM_PROVIDER=off — callers must handle the no-op case."""
    if llm_settings.provider is LLMProvider.GROQ:
        from src.infrastructure.llm.groq import GroqLLM

        return GroqLLM(llm_settings)
    return None
