"""
Custom diarizer adapter — DIARIZER_PROVIDER=custom.

Hand-rolled VAD + speaker-embedding + HDBSCAN clustering pipeline, offered as
an alternative to the prebuilt pyannote.audio speaker-diarization pipeline
(DIARIZER_PROVIDER=pyannote). Both adapters satisfy the same DiarizerPort, so
switching between them is a single .env flag with no pipeline changes.

Unlike PyannoteDiarizer (which delegates min_speakers/max_speakers directly
to the prebuilt pipeline's clustering step), HDBSCAN doesn't take a target
cluster count. This adapter enforces max_speakers after the fact by merging
the closest clusters by centroid distance. min_speakers isn't force-split
(that would require guessing a valid sub-clustering) — a warning is logged
instead if HDBSCAN reports fewer clusters than requested.
"""
from __future__ import annotations

import logging
from pathlib import Path
from threading import Lock

import numpy as np

from src.domain.entities import SpeakerTurn
from src.domain.errors import DomainError, OutOfMemoryError
from src.settings.config import DiarizationSettings

logger = logging.getLogger(__name__)


def _is_oom(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "out of memory" in msg or ("cuda" in msg and "memory" in msg)


class CustomDiarizer:
    """VAD + embedding + HDBSCAN adapter. Satisfies domain.ports.services.DiarizerPort."""

    def __init__(self, settings: DiarizationSettings) -> None:
        self._settings = settings
        self._vad = None
        self._inference = None
        self._lock = Lock()

    def _resolve_device(self):
        import torch

        device = self._settings.device
        if device == "auto":
            return torch.device("cuda" if torch.cuda.is_available() else "cpu")
        return torch.device(device)

    def _get_models(self):
        if self._vad is not None:
            return self._vad, self._inference
        with self._lock:
            if self._vad is not None:
                return self._vad, self._inference

            import os

            import torch
            from pyannote.audio import Inference, Model
            from pyannote.audio.pipelines import VoiceActivityDetection

            if not self._settings.hf_token:
                raise DomainError(
                    "DIARIZER_PROVIDER=custom requires DIARIZER_HF_TOKEN — a Hugging "
                    "Face access token with the license accepted for "
                    f"'{self._settings.custom_segmentation_model}' and "
                    f"'{self._settings.custom_embedding_model}'."
                )

            # Route the HF cache to the shared /models volume, same as PyannoteDiarizer
            # and faster-whisper's model_cache_dir, so re-pulls survive restarts.
            os.environ.setdefault("HF_HOME", self._settings.model_cache_dir)

            try:
                segmentation_model = Model.from_pretrained(
                    self._settings.custom_segmentation_model,
                    use_auth_token=self._settings.hf_token,
                )
                vad = VoiceActivityDetection(segmentation=segmentation_model)
                vad.instantiate(
                    {
                        "onset": self._settings.custom_vad_threshold,
                        "offset": self._settings.custom_vad_threshold,
                        "min_duration_on": self._settings.custom_min_segment_duration,
                        "min_duration_off": self._settings.custom_min_segment_duration,
                    }
                )

                embedding_model = Model.from_pretrained(
                    self._settings.custom_embedding_model,
                    use_auth_token=self._settings.hf_token,
                )
                inference = Inference(embedding_model, window="whole")
            except Exception as exc:  # noqa: BLE001
                raise DomainError(f"Failed to load custom diarization models: {exc}") from exc

            device = self._resolve_device()
            if device.type == "cuda" and not torch.cuda.is_available():
                raise DomainError(
                    "DIARIZER_DEVICE=cuda but no CUDA device is available to this process."
                )
            segmentation_model.to(device)
            embedding_model.to(device)
            inference.to(device)

            self._vad = vad
            self._inference = inference
            return self._vad, self._inference

    def warmup(self) -> None:
        """Pay the model-load cost eagerly (called at worker startup)."""
        self._get_models()

    def diarize(self, media_path: Path) -> list[SpeakerTurn]:
        if not media_path.exists():
            raise DomainError(f"Media file not found: {media_path}")

        vad, inference = self._get_models()

        try:
            speech = vad(str(media_path))
        except Exception as exc:  # noqa: BLE001
            if _is_oom(exc):
                raise OutOfMemoryError(
                    "GPU ran out of memory during VAD. Try DIARIZER_DEVICE=cpu or a smaller "
                    "segmentation model."
                ) from exc
            raise DomainError(f"Custom diarizer VAD failed: {exc}") from exc

        segments = [
            (segment.start, segment.end)
            for segment in speech.get_timeline()
            if segment.end - segment.start >= self._settings.custom_min_segment_duration
        ]
        if not segments:
            return []

        from pyannote.core import Segment

        embeddings = []
        for start, end in segments:
            try:
                embedding = inference.crop(str(media_path), Segment(start, end))
            except Exception as exc:  # noqa: BLE001
                if _is_oom(exc):
                    raise OutOfMemoryError(
                        "GPU ran out of memory during embedding extraction. Try "
                        "DIARIZER_DEVICE=cpu or a smaller embedding model."
                    ) from exc
                raise DomainError(f"Custom diarizer embedding extraction failed: {exc}") from exc
            embeddings.append(np.asarray(embedding).reshape(-1))

        embeddings_matrix = np.vstack(embeddings)
        labels = self._cluster(embeddings_matrix)

        turns = [
            SpeakerTurn(start=round(start, 3), end=round(end, 3), speaker_id=str(label))
            for (start, end), label in zip(segments, labels)
        ]
        turns.sort(key=lambda t: t.start)
        return turns

    def _cluster(self, embeddings: np.ndarray) -> list[int]:
        import hdbscan

        # L2-normalize so euclidean distance approximates cosine distance,
        # the standard metric for speaker embeddings.
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        normalized = embeddings / norms

        clusterer = hdbscan.HDBSCAN(
            min_cluster_size=max(2, self._settings.custom_min_cluster_size),
            cluster_selection_epsilon=self._settings.custom_distance_threshold,
            metric="euclidean",
        )
        labels = clusterer.fit_predict(normalized)

        # HDBSCAN marks outliers as -1; fold each into its nearest real cluster
        # (or give it its own singleton cluster if there are none) rather than
        # dropping the turn entirely — every speech segment needs a speaker.
        labels = self._assign_noise(normalized, labels)

        max_speakers = self._settings.max_speakers
        n_clusters = len(set(labels.tolist()))
        if max_speakers is not None and n_clusters > max_speakers:
            labels = self._merge_to_max(normalized, labels, max_speakers)

        min_speakers = self._settings.min_speakers
        n_clusters = len(set(labels.tolist()))
        if min_speakers is not None and n_clusters < min_speakers:
            logger.warning(
                "Custom diarizer found %d speaker(s), fewer than min_speakers=%d; "
                "not force-splitting clusters.",
                n_clusters,
                min_speakers,
            )

        return labels.tolist()

    def _assign_noise(self, embeddings: np.ndarray, labels: np.ndarray) -> np.ndarray:
        labels = labels.copy()
        real = labels[labels != -1]
        if real.size == 0:
            # Nothing but noise: give every point its own cluster.
            return np.arange(len(labels))

        centroids = {label: embeddings[labels == label].mean(axis=0) for label in set(real.tolist())}
        for idx in np.where(labels == -1)[0]:
            point = embeddings[idx]
            best_label = min(centroids, key=lambda lbl: np.linalg.norm(point - centroids[lbl]))
            labels[idx] = best_label
        return labels

    def _merge_to_max(self, embeddings: np.ndarray, labels: np.ndarray, max_speakers: int) -> np.ndarray:
        labels = labels.copy()
        unique = sorted(set(labels.tolist()))
        centroids = {label: embeddings[labels == label].mean(axis=0) for label in unique}

        while len(centroids) > max_speakers:
            pairs = [
                (a, b, np.linalg.norm(centroids[a] - centroids[b]))
                for i, a in enumerate(centroids)
                for b in list(centroids)[i + 1 :]
            ]
            a, b, _ = min(pairs, key=lambda p: p[2])
            labels[labels == b] = a
            centroids[a] = embeddings[np.isin(labels, [a])].mean(axis=0)
            del centroids[b]

        return labels
