"""
PersistExportPlugin — uploads the final mastered file as an EXPORT artifact.

Terminal stage of the EXPORT pipeline. Kept separate from MasterPlugin so
persistence follows the same artifact-helper pattern as every other stage
(see `application.pipeline.artifacts`).
"""
from __future__ import annotations

from pathlib import Path

from src.application.pipeline.artifacts import persist_file_artifact
from src.application.pipeline.plugin import BasePlugin
from src.domain.dto import PipelineContext
from src.domain.enums import ArtifactKind
from src.domain.ports.repositories import ArtifactRepository
from src.domain.ports.services import StoragePort


class PersistExportPlugin(BasePlugin):
    """Uploads `context.output_path` to storage and records it as an EXPORT artifact."""

    name = "persist_export"

    def __init__(self, storage: StoragePort, artifacts: ArtifactRepository) -> None:
        self._storage = storage
        self._artifacts = artifacts

    async def run(self, context: PipelineContext) -> PipelineContext:
        if not context.output_path:
            raise ValueError("MasterPlugin must run before PersistExportPlugin.")

        artifact = await persist_file_artifact(
            self._storage,
            self._artifacts,
            project_id=context.project_id,
            media_id=context.media_id,
            job_id=context.job_id,
            kind=ArtifactKind.EXPORT,
            file_path=Path(context.output_path),
            content_type="audio/wav",
        )
        context.metadata["export_artifact_id"] = artifact.id
        context.metadata["export_storage_key"] = artifact.storage_key
        return context
