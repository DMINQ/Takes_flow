"""
IngestPlugin — materialize the media file locally and probe/preprocess it.

Runs first in every analysis/export pipeline: everything downstream (Whisper,
ffmpeg, pedalboard) needs a real path on disk, so this stage is the one place
that turns a storage key into a working file (see StoragePort.materialize).
"""
from __future__ import annotations

from pathlib import Path

from src.application.pipeline.plugin import BasePlugin
from src.domain.dto import PipelineContext
from src.domain.errors import AudioProcessingError, StorageError
from src.domain.ports.repositories import MediaRepository
from src.domain.ports.services import AudioEnginePort, StoragePort


class IngestPlugin(BasePlugin):
    """Materializes the source media and fills in duration/working_audio_path."""

    name = "ingest"

    def __init__(
        self,
        storage: StoragePort,
        audio_engine: AudioEnginePort,
        media_repo: MediaRepository,
        work_dir: Path,
    ) -> None:
        self._storage = storage
        self._audio_engine = audio_engine
        self._media = media_repo
        self._work_dir = work_dir

    async def run(self, context: PipelineContext) -> PipelineContext:
        media = await self._media.get(context.media_id)
        if media is None:
            raise AudioProcessingError(f"Media '{context.media_id}' not found for ingest.")

        dest_dir = self._work_dir / context.job_id
        dest_dir.mkdir(parents=True, exist_ok=True)
        try:
            source_path = await self._storage.materialize(media.storage_key, dest_dir)
        except StorageError as exc:
            raise AudioProcessingError(f"Could not materialize media: {exc}") from exc

        duration = self._audio_engine.probe_duration(source_path)
        preprocessed = self._audio_engine.preprocess(
            source_path, dest_dir / f"{source_path.stem}.preprocessed{source_path.suffix}"
        )

        context.input_path = str(source_path)
        context.working_audio_path = str(preprocessed)
        context.duration = duration
        if str(preprocessed) != str(source_path):
            context.temp_files.append(str(preprocessed))
        return context
