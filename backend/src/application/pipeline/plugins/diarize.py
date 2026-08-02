"""
DiarizePlugin — splits speech into speaker turns and persists the result.

Turns are the source of truth silence-cutting works from (see
`application.pipeline.silence`), so this stage runs before CutSilencePlugin.
The turn list is also persisted as a DIARIZATION artifact for later stages
(bad-take detection, review UI) to read without re-running the diarizer.
"""
from __future__ import annotations

from pathlib import Path

from src.application.pipeline.artifacts import persist_json_artifact
from src.application.pipeline.plugin import BasePlugin
from src.domain.dto import PipelineContext
from src.domain.enums import ArtifactKind
from src.domain.ports.repositories import ArtifactRepository
from src.domain.ports.services import DiarizerPort, StoragePort


class DiarizePlugin(BasePlugin):
    """Detects speaker turns over the working audio and records them."""

    name = "diarize"

    def __init__(self, diarizer: DiarizerPort, storage: StoragePort, artifacts: ArtifactRepository) -> None:
        self._diarizer = diarizer
        self._storage = storage
        self._artifacts = artifacts

    async def run(self, context: PipelineContext) -> PipelineContext:
        audio_path = context.working_audio_path or context.input_path
        turns = self._diarizer.diarize(Path(audio_path))
        context.speaker_turns = turns

        await persist_json_artifact(
            self._storage,
            self._artifacts,
            project_id=context.project_id,
            media_id=context.media_id,
            job_id=context.job_id,
            kind=ArtifactKind.DIARIZATION,
            payload=[
                {"start": t.start, "end": t.end, "speaker_id": t.speaker_id} for t in turns
            ],
        )
        return context
