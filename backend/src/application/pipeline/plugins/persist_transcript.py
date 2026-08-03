"""
PersistTranscriptPlugin — saves the transcription result as a TRANSCRIPT artifact.

Runs after TranscribePlugin. Keeping this separate from TranscribePlugin keeps
that stage focused on running the model; persistence is a cross-cutting
concern shared with the other stages (see `application.pipeline.artifacts`).
"""
from __future__ import annotations

from src.application.pipeline.artifacts import persist_json_artifact
from src.application.pipeline.plugin import BasePlugin
from src.domain.dto import PipelineContext
from src.domain.enums import ArtifactKind
from src.domain.ports.repositories import ArtifactRepository
from src.domain.ports.services import StoragePort


class PersistTranscriptPlugin(BasePlugin):
    """Writes `context.words` (+ detected language) to storage as an artifact."""

    name = "persist_transcript"
    progress_weight = 0.3

    def __init__(self, storage: StoragePort, artifacts: ArtifactRepository) -> None:
        self._storage = storage
        self._artifacts = artifacts

    async def run(self, context: PipelineContext) -> PipelineContext:
        payload = {
            "language": context.detected_language,
            "language_probability": context.language_probability,
            "words": [
                {
                    "text": w.text,
                    "start": w.start,
                    "end": w.end,
                    "probability": w.probability,
                    "speaker": w.speaker,
                }
                for w in context.words
            ],
        }
        await persist_json_artifact(
            self._storage,
            self._artifacts,
            project_id=context.project_id,
            media_id=context.media_id,
            job_id=context.job_id,
            kind=ArtifactKind.TRANSCRIPT,
            payload=payload,
        )
        return context
