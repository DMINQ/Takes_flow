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
from src.application.pipeline.plugins.assemble_export import AssembleExportPlugin
from src.application.pipeline.plugins.bad_take import BadTakePlugin
from src.application.pipeline.plugins.cut_silence import CutSilencePlugin
from src.application.pipeline.plugins.denoise import DenoisePlugin
from src.application.pipeline.plugins.diarize import DiarizePlugin
from src.application.pipeline.plugins.ingest import IngestPlugin
from src.application.pipeline.plugins.load_timeline import LoadTimelinePlugin
from src.application.pipeline.plugins.master import MasterPlugin
from src.application.pipeline.plugins.persist_export import PersistExportPlugin
from src.application.pipeline.plugins.persist_timeline import PersistTimelinePlugin
from src.application.pipeline.plugins.persist_transcript import PersistTranscriptPlugin
from src.application.pipeline.plugins.transcribe import TranscribePlugin
from src.application.pipeline.registry import registry
from src.domain.enums import JobKind
from src.infrastructure.repositories.artifact import SqlArtifactRepository
from src.infrastructure.repositories.media import SqlMediaRepository
from src.infrastructure.repositories.timeline import SqlTimelineRepository
from src.settings.config import analysis_settings, core_settings
from src.settings.providers import get_audio_engine, get_diarizer, get_storage, get_transcriber


def _work_dir() -> Path:
    """Scratch directory for materialized/preprocessed files, cleaned up per job."""
    path = Path(core_settings.data_dir) / "work"
    path.mkdir(parents=True, exist_ok=True)
    return path


def build_analysis_plugins(session: AsyncSession) -> list[BasePlugin]:
    """Ingest -> Denoise -> Diarize -> CutSilence -> Transcribe -> BadTake -> PersistTranscript -> PersistTimeline.

    Diarization runs before silence-cutting because speech turns are the
    source of truth for what counts as non-speech (see
    `application.pipeline.silence`); transcription then only sees the audio
    that survived the cut, avoiding a second VAD pass. BadTakePlugin runs
    after transcription (it needs `context.words`) and only adds REVIEW
    regions on top of what CutSilence already built — it never removes or
    reclassifies a KEEP/AUTO_CUT region, so ordering with PersistTimeline is
    the only constraint (bad-take must run before it).
    """
    storage = get_storage()
    media_repo = SqlMediaRepository(session)
    artifact_repo = SqlArtifactRepository(session)
    return [
        IngestPlugin(storage, get_audio_engine(), media_repo, _work_dir()),
        DenoisePlugin(get_audio_engine(), storage, artifact_repo),
        DiarizePlugin(get_diarizer(), storage, artifact_repo),
        CutSilencePlugin(get_audio_engine(), storage, artifact_repo, analysis_settings),
        TranscribePlugin(get_transcriber()),
        BadTakePlugin(analysis_settings),
        PersistTranscriptPlugin(storage, artifact_repo),
        PersistTimelinePlugin(SqlTimelineRepository(session)),
    ]


def build_export_plugins(session: AsyncSession) -> list[BasePlugin]:
    """Ingest -> Denoise -> LoadTimeline -> AssembleExport -> Master -> PersistExport.

    Reuses the same Ingest/Denoise stages as analysis (materialize + probe
    duration + ffmpeg denoise) so the exported file actually reflects the
    noise reduction applied during analysis, instead of re-cutting the raw
    upload — export only additionally needs the region map an ANALYSIS job
    already produced (LoadTimelinePlugin) plus the user's take choices
    (PipelineContext.export_selection) to know what to assemble and master.
    Diarize/CutSilence/Transcribe are still skipped: those regions are already
    persisted from the ANALYSIS run.
    """
    storage = get_storage()
    media_repo = SqlMediaRepository(session)
    artifact_repo = SqlArtifactRepository(session)
    audio_engine = get_audio_engine()
    return [
        IngestPlugin(storage, audio_engine, media_repo, _work_dir()),
        DenoisePlugin(audio_engine, storage, artifact_repo),
        LoadTimelinePlugin(SqlTimelineRepository(session)),
        AssembleExportPlugin(audio_engine),
        MasterPlugin(audio_engine),
        PersistExportPlugin(storage, artifact_repo),
    ]


def register_pipelines(session: AsyncSession) -> None:
    """Register plugin-list factories bound to `session`. Call once per job run."""
    registry.register(JobKind.ANALYSIS, lambda: build_analysis_plugins(session))
    registry.register(JobKind.EXPORT, lambda: build_export_plugins(session))
