"""
Pipeline compositions — wires plugins into ordered lists per JobKind and
registers them in the process-wide `registry`.

Imported once (worker startup) so building an ANALYSIS/EXPORT job later is just
`registry.build(job.kind)`. Adapters come from settings/providers so the same
composition works whether the transcriber is local/remote, storage is fs/S3, etc.
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from src.application.pipeline.plugin import BasePlugin
from src.application.pipeline.plugins.diarize import DiarizePlugin
from src.application.pipeline.plugins.ingest import IngestPlugin
from src.application.pipeline.plugins.persist_timeline import PersistTimelinePlugin
from src.application.pipeline.plugins.transcribe import TranscribePlugin
from src.application.pipeline.registry import registry
from src.domain.enums import JobKind
from src.infrastructure.repositories.media import SqlMediaRepository
from src.infrastructure.repositories.timeline import SqlTimelineRepository
from src.settings.config import core_settings
from src.settings.providers import get_audio_engine, get_diarizer, get_storage, get_transcriber


def _work_dir() -> Path:
    """Scratch directory for materialized/preprocessed files, cleaned up per job."""
    path = Path(core_settings.data_dir) / "work"
    path.mkdir(parents=True, exist_ok=True)
    return path


def build_analysis_plugins(session: AsyncSession) -> list[BasePlugin]:
    """Ingest -> Transcribe -> Diarize -> PersistTimeline.

    Silence/bad-take detection (Step 5/6) insert between Diarize and
    PersistTimeline without changing this list's shape.
    """
    media_repo = SqlMediaRepository(session)
    return [
        IngestPlugin(get_storage(), get_audio_engine(), media_repo, _work_dir()),
        TranscribePlugin(get_transcriber()),
        DiarizePlugin(get_diarizer()),
        PersistTimelinePlugin(SqlTimelineRepository(session)),
    ]


def register_pipelines(session: AsyncSession) -> None:
    """Register plugin-list factories bound to `session`. Call once per job run."""
    registry.register(JobKind.ANALYSIS, lambda: build_analysis_plugins(session))
