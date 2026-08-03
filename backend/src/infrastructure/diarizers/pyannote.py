"""
Pyannote diarizer adapter — DIARIZER_PROVIDER=pyannote.

Uses pyannote.audio's prebuilt `speaker-diarization` pipeline, which already
chains VAD (segmentation) + speaker embeddings + clustering internally — no
need to hand-roll that chain (unlike a from-scratch VAD+embedding+HDBSCAN
approach). This also means min_speakers/max_speakers are honored directly by
the pipeline's clustering step, rather than being accepted but ignored.

Requires a Hugging Face token with access to the gated pyannote model repos
(`pyannote/speaker-diarization-3.1` and its dependencies `pyannote/segmentation-3.0`,
`pyannote/embedding`) — accept their license terms at https://huggingface.co
before use, or model download fails with a 401.
"""
from __future__ import annotations

from pathlib import Path
from threading import Lock

from src.domain.entities import SpeakerTurn
from src.domain.errors import DomainError
from src.settings.config import DiarizationSettings


class PyannoteDiarizer:
    """pyannote.audio adapter. Satisfies domain.ports.services.DiarizerPort."""

    def __init__(self, settings: DiarizationSettings) -> None:
        self._settings = settings
        self._pipeline = None
        self._lock = Lock()

    def _resolve_device(self):
        import torch

        device = self._settings.device
        if device == "auto":
            return torch.device("cuda" if torch.cuda.is_available() else "cpu")
        return torch.device(device)

    def _get_pipeline(self):
        if self._pipeline is not None:
            return self._pipeline
        with self._lock:
            if self._pipeline is not None:
                return self._pipeline

            import os

            import torch
            from pyannote.audio import Pipeline

            if not self._settings.hf_token:
                raise DomainError(
                    "DIARIZER_PROVIDER=pyannote requires DIARIZER_HF_TOKEN — a Hugging "
                    "Face access token with the license accepted for "
                    "'pyannote/speaker-diarization-3.1' and its dependent model repos."
                )

            # Route the HF cache to the shared /models volume, same as faster-whisper's
            # model_cache_dir, so re-pulls survive container restarts.
            os.environ.setdefault("HF_HOME", self._settings.model_cache_dir)

            try:
                pipeline = Pipeline.from_pretrained(
                    self._settings.model,
                    use_auth_token=self._settings.hf_token,
                )
            except Exception as exc:  # noqa: BLE001
                raise DomainError(
                    f"Failed to load pyannote pipeline '{self._settings.model}': {exc}"
                ) from exc

            device = self._resolve_device()
            if device.type == "cuda" and not torch.cuda.is_available():
                raise DomainError(
                    "DIARIZER_DEVICE=cuda but no CUDA device is available to this process."
                )
            pipeline.to(device)

            self._pipeline = pipeline
            return self._pipeline

    def warmup(self) -> None:
        """Pay the model-load cost eagerly (called at worker startup)."""
        self._get_pipeline()

    def diarize(self, media_path: Path) -> list[SpeakerTurn]:
        if not media_path.exists():
            raise DomainError(f"Media file not found: {media_path}")

        pipeline = self._get_pipeline()

        kwargs: dict[str, int] = {}
        if self._settings.min_speakers is not None:
            kwargs["min_speakers"] = self._settings.min_speakers
        if self._settings.max_speakers is not None:
            kwargs["max_speakers"] = self._settings.max_speakers

        try:
            annotation = pipeline(str(media_path), **kwargs)
        except Exception as exc:  # noqa: BLE001
            raise DomainError(f"Pyannote diarization failed: {exc}") from exc

        turns = [
            SpeakerTurn(start=round(segment.start, 3), end=round(segment.end, 3), speaker_id=str(speaker))
            for segment, _, speaker in annotation.itertracks(yield_label=True)
        ]
        turns.sort(key=lambda t: t.start)
        return turns
