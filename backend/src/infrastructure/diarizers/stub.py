"""
Stub diarizer — implements DiarizerPort with a single speaker.

This keeps the pipeline's Diarize stage functional now. A PyannoteDiarizer
satisfying the same port is dropped in later (DIARIZER_PROVIDER=pyannote) with no
change to the pipeline or callers.
"""
from __future__ import annotations

from pathlib import Path

from src.domain.entities import Speaker


class StubDiarizer:
    """Returns one speaker — correct for single-voice voiceovers."""

    def diarize(self, media_path: Path) -> list[Speaker]:
        return [Speaker(id="0", label="SPEAKER_00")]
