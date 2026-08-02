"""
Artifact persistence helpers — upload a pipeline stage's output to storage and
record it as an `Artifact` row.

Centralized here so every plugin persists the same way (object key layout,
Artifact bookkeeping) without repeating the storage/repo wiring.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

from src.domain import upload_policy as policy
from src.domain.entities import Artifact
from src.domain.enums import ArtifactKind
from src.domain.ports.repositories import ArtifactRepository
from src.domain.ports.services import StoragePort

_CHUNK_SIZE = 1024 * 1024


async def _stream_file(path: Path):
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(_CHUNK_SIZE)
            if not chunk:
                break
            yield chunk


async def persist_file_artifact(
    storage: StoragePort,
    artifacts: ArtifactRepository,
    *,
    project_id: str,
    media_id: str,
    job_id: str,
    kind: ArtifactKind,
    file_path: Path,
    content_type: str | None = None,
) -> Artifact:
    """Upload a local file to storage and record it as an Artifact."""
    key = policy.build_artifact_key(project_id, media_id, kind, file_path.suffix)
    await storage.save_stream(key, _stream_file(file_path))
    artifact = Artifact(
        id=uuid.uuid4().hex,
        media_id=media_id,
        job_id=job_id,
        kind=kind,
        storage_key=key,
        content_type=content_type,
    )
    return await artifacts.add(artifact)


async def persist_json_artifact(
    storage: StoragePort,
    artifacts: ArtifactRepository,
    *,
    project_id: str,
    media_id: str,
    job_id: str,
    kind: ArtifactKind,
    payload: object,
) -> Artifact:
    """Serialize `payload` as JSON and record it as an Artifact."""
    key = policy.build_artifact_key(project_id, media_id, kind, ".json")
    data = json.dumps(payload).encode("utf-8")

    async def _chunks():
        yield data

    await storage.save_stream(key, _chunks())
    artifact = Artifact(
        id=uuid.uuid4().hex,
        media_id=media_id,
        job_id=job_id,
        kind=kind,
        storage_key=key,
        content_type="application/json",
    )
    return await artifacts.add(artifact)
