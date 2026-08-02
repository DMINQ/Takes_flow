"""
Remote transcriber adapter — placeholder for TRANSCRIBER_PROVIDER=remote.

Satisfies TranscriberPort so `settings/providers.py` resolves regardless of
which provider is configured. Not implemented yet: no remote ASR service is
wired up. Swap in a real HTTP client here (see `httpx` in dependencies) when
one is available — the port contract (`transcribe`) will not need to change.
"""
from __future__ import annotations

from pathlib import Path

from src.domain.entities import Word
from src.domain.errors import TranscriptionError
from src.settings.config import TranscriptionSettings


class RemoteTranscriber:
    """Placeholder adapter. Satisfies domain.ports.services.TranscriberPort."""

    def __init__(self, settings: TranscriptionSettings) -> None:
        self._settings = settings

    def warmup(self) -> None:
        """No local model to preload for a remote provider."""

    def transcribe(
        self, media_path: Path, language: str | None = None
    ) -> tuple[list[Word], str, float, float]:
        raise TranscriptionError(
            f"TRANSCRIBER_PROVIDER=remote is not implemented yet "
            f"(remote_url={self._settings.remote_url})."
        )
