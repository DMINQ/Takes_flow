"""
Local transcriber adapter — faster-whisper, implementing TranscriberPort.

The model is large and expensive to load, so it's a lazy, thread-safe singleton
reused across calls. `transcribe` is blocking (CPU/GPU-bound); callers offload it
to a worker thread. Weights are cached in `model_cache_dir` (a Docker volume) so
they download once.
"""
from __future__ import annotations

import logging
from pathlib import Path
from threading import Lock

from faster_whisper import WhisperModel

from src.domain.entities import Word
from src.domain.errors import OutOfMemoryError, TranscriptionError
from src.settings.config import TranscriptionSettings

logger = logging.getLogger(__name__)


class LocalTranscriber:
    """faster-whisper adapter. Satisfies domain.ports.services.TranscriberPort."""

    def __init__(self, settings: TranscriptionSettings) -> None:
        self._settings = settings
        self._model: WhisperModel | None = None
        self._lock = Lock()

    def _get_model(self) -> WhisperModel:
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is not None:
                return self._model
            s = self._settings
            logger.info(
                "Loading Whisper '%s' (device=%s, compute=%s, cache=%s)",
                s.model, s.device, s.compute_type, s.model_cache_dir,
            )
            try:
                self._model = WhisperModel(
                    s.model,
                    device=s.device,
                    compute_type=s.compute_type,
                    cpu_threads=s.cpu_threads,
                    download_root=s.model_cache_dir,
                )
            except Exception as exc:  # noqa: BLE001
                raise TranscriptionError(f"Failed to load Whisper model: {exc}") from exc
            return self._model

    def warmup(self) -> None:
        """Pay the load cost eagerly (called at worker startup)."""
        self._get_model()

    def transcribe(
        self, media_path: Path, language: str | None = None
    ) -> tuple[list[Word], str, float, float]:
        if not media_path.exists():
            raise TranscriptionError(f"Media file not found: {media_path}")

        model = self._get_model()
        try:
            segments_iter, info = model.transcribe(
                str(media_path),
                language=language,
                beam_size=self._settings.beam_size,
                word_timestamps=True,
                vad_filter=True,
            )
        except RuntimeError as exc:
            msg = str(exc).lower()
            if "out of memory" in msg or ("cuda" in msg and "memory" in msg):
                raise OutOfMemoryError(
                    "GPU ran out of memory during transcription. Use a smaller model "
                    "(TRANSCRIBER_MODEL=base/small), TRANSCRIBER_COMPUTE_TYPE=int8, "
                    "or TRANSCRIBER_DEVICE=cpu."
                ) from exc
            raise TranscriptionError(f"Transcription failed: {exc}") from exc

        words: list[Word] = []
        # Iterating the generator is what actually runs the model.
        for seg in segments_iter:
            for w in (seg.words or []):
                words.append(
                    Word(
                        text=w.word,
                        start=round(w.start, 3),
                        end=round(w.end, 3),
                        probability=round(w.probability, 4),
                    )
                )

        return words, info.language, round(info.language_probability, 4), round(info.duration, 3)
