"""
Pyannote diarizer adapter — placeholder for DIARIZER_PROVIDER=pyannote.

Satisfies DiarizerPort so `settings/providers.py` resolves regardless of which
provider is configured. Not implemented yet: pyannote.audio is not a declared
dependency and no model download/HF-token flow is wired up. When implemented,
this should return real speaker turns (see `DiarizationSettings.hf_token`) —
the port contract (`diarize`) will not need to change.
"""
from __future__ import annotations

from pathlib import Path

from src.domain.entities import SpeakerTurn
from src.domain.errors import DomainError
from src.settings.config import DiarizationSettings


class PyannoteDiarizer:
    """Placeholder adapter. Satisfies domain.ports.services.DiarizerPort."""

    def __init__(self, settings: DiarizationSettings) -> None:
        self._settings = settings

    def diarize(self, media_path: Path) -> list[SpeakerTurn]:
        raise DomainError(
            "DIARIZER_PROVIDER=pyannote is not implemented yet "
            "(pyannote.audio is not a declared dependency)."
        )
