"""
Stub diarizer — implements DiarizerPort with a single speaker turn.

This keeps the pipeline's Diarize stage functional now. A PyannoteDiarizer
satisfying the same port is dropped in later (DIARIZER_PROVIDER=pyannote) with no
change to the pipeline or callers.
"""
from __future__ import annotations

from pathlib import Path

from src.domain.entities import SpeakerTurn
from src.domain.ports.services import AudioEnginePort


class StubDiarizer:
    """Returns one turn spanning the whole file — correct for single-voice voiceovers."""

    def __init__(self, audio_engine: AudioEnginePort) -> None:
        self._audio_engine = audio_engine

    def diarize(self, media_path: Path) -> list[SpeakerTurn]:
        duration = self._audio_engine.probe_duration(media_path)
        return [SpeakerTurn(start=0.0, end=duration, speaker_id="0")]
