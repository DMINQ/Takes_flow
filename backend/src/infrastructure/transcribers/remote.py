"""
Remote transcriber adapter — HTTP client for TRANSCRIBER_PROVIDER=remote.

Talks to an `onerahmet/openai-whisper-asr-webservice`-compatible ASR service
(https://github.com/ahmetoner/whisper-asr-webservice) over its `POST /asr`
multipart endpoint. That service wraps faster-whisper itself, so this adapter
stays a thin HTTP client: no whisper/torch dependency here, no GPU/CPU cost
in this process — only in the external `whisper` container.

Satisfies TranscriberPort; `transcribe()` is blocking (sync httpx.Client),
matching LocalTranscriber's blocking contract — callers already offload to a
thread (see application.pipeline.plugins.transcribe.TranscribePlugin).
"""
from __future__ import annotations

from pathlib import Path

import httpx

from src.domain.entities import Word
from src.domain.errors import TranscriptionError
from src.settings.config import TranscriptionSettings


class RemoteTranscriber:
    """HTTP adapter for a whisper-asr-webservice-compatible ASR endpoint."""

    def __init__(self, settings: TranscriptionSettings) -> None:
        self._settings = settings

    def warmup(self) -> None:
        """No local model to preload for a remote provider."""

    def transcribe(
        self, media_path: Path, language: str | None = None
    ) -> tuple[list[Word], str, float, float]:
        if not media_path.exists():
            raise TranscriptionError(f"Media file not found: {media_path}")

        params: dict[str, str] = {
            "encode": "true",
            "task": "transcribe",
            "output": "json",
            "word_timestamps": "true",
        }
        if language:
            params["language"] = language

        try:
            with media_path.open("rb") as f:
                files = {"audio_file": (media_path.name, f, "application/octet-stream")}
                with httpx.Client(timeout=self._settings.remote_timeout_seconds) as client:
                    response = client.post(self._settings.remote_url, params=params, files=files)
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise TranscriptionError(
                f"Remote transcriber timed out after {self._settings.remote_timeout_seconds}s "
                f"(remote_url={self._settings.remote_url}): {exc}"
            ) from exc
        except httpx.HTTPError as exc:
            raise TranscriptionError(
                f"Remote transcriber request failed (remote_url={self._settings.remote_url}): {exc}"
            ) from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise TranscriptionError(
                f"Remote transcriber returned a non-JSON response (remote_url={self._settings.remote_url})"
            ) from exc

        segments = payload.get("segments", payload if isinstance(payload, list) else [])
        if not isinstance(segments, list):
            raise TranscriptionError(
                f"Remote transcriber returned an unexpected payload shape: {type(segments)!r}"
            )

        words: list[Word] = []
        duration = 0.0
        for segment in segments:
            if not isinstance(segment, dict):
                continue
            duration = max(duration, float(segment.get("end", 0.0) or 0.0))
            segment_words = segment.get("words")
            if segment_words:
                for w in segment_words:
                    words.append(
                        Word(
                            text=str(w.get("word", "")).strip(),
                            start=round(float(w.get("start", 0.0)), 3),
                            end=round(float(w.get("end", 0.0)), 3),
                            probability=round(float(w.get("probability", 1.0)), 4),
                        )
                    )
            else:
                # ASR service didn't return word-level timestamps for this
                # segment (e.g. word_timestamps unsupported by its engine
                # config) — fall back to one Word spanning the whole segment
                # so downstream stages still get usable text/timing.
                text = str(segment.get("text", "")).strip()
                if text:
                    words.append(
                        Word(
                            text=text,
                            start=round(float(segment.get("start", 0.0)), 3),
                            end=round(float(segment.get("end", 0.0)), 3),
                            probability=1.0,
                        )
                    )

        detected_language = str(payload.get("language") or language or "")
        language_probability = float(payload.get("language_probability", 1.0) or 1.0)

        return words, detected_language, round(language_probability, 4), round(duration, 3)
