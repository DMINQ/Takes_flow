"""
DenoisePlugin — cleans the ingested audio via AudioEnginePort.preprocess, then
persists the result as a DENOISED_AUDIO artifact.

Runs right after Ingest so every later stage (diarization, transcription) works
from the cleaned copy, and the artifact is kept around for reuse/inspection
instead of being thrown away as a scratch file.
"""
from __future__ import annotations

from pathlib import Path

from src.application.pipeline.artifacts import persist_file_artifact
from src.application.pipeline.plugin import BasePlugin
from src.domain.dto import PipelineContext
from src.domain.enums import ArtifactKind
from src.domain.ports.repositories import ArtifactRepository
from src.domain.ports.services import AudioEnginePort, StoragePort


class DenoisePlugin(BasePlugin):
    """Denoises/normalizes the working audio and records it as an artifact."""

    name = "denoise"

    def __init__(
        self, audio_engine: AudioEnginePort, storage: StoragePort, artifacts: ArtifactRepository
    ) -> None:
        self._audio_engine = audio_engine
        self._storage = storage
        self._artifacts = artifacts

    async def run(self, context: PipelineContext) -> PipelineContext:
        source_path = Path(context.working_audio_path or context.input_path)
        denoised_path = source_path.with_name(f"{source_path.stem}.denoised{source_path.suffix}")
        result = self._audio_engine.preprocess(source_path, denoised_path)

        context.working_audio_path = str(result)
        if str(result) != str(source_path):
            context.temp_files.append(str(result))

        await persist_file_artifact(
            self._storage,
            self._artifacts,
            project_id=context.project_id,
            media_id=context.media_id,
            job_id=context.job_id,
            kind=ArtifactKind.DENOISED_AUDIO,
            file_path=result,
        )
        return context
