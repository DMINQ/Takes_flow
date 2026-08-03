"""
CutSilencePlugin — removes non-speech gaps found by diarization, before transcription.

Builds the KEEP/AUTO_CUT region map from `context.speaker_turns` (see
`application.pipeline.silence.build_regions`), assembles the KEEP ranges into a
new working audio file via AudioEnginePort.assemble, and persists that file as
a CUT_AUDIO artifact. Runs before TranscribePlugin so Whisper only sees the
speech that survives the cut — cheaper and avoids double VAD.
"""
from __future__ import annotations

from pathlib import Path

from src.application.pipeline.artifacts import persist_file_artifact
from src.application.pipeline.plugin import BasePlugin
from src.application.pipeline.silence import build_regions, keep_ranges
from src.domain.dto import PipelineContext
from src.domain.enums import ArtifactKind
from src.domain.ports.repositories import ArtifactRepository
from src.domain.ports.services import AudioEnginePort, StoragePort
from src.settings.config import AnalysisSettings


class CutSilencePlugin(BasePlugin):
    """Cuts silence out of the working audio using diarized speech turns."""

    name = "cut_silence"
    progress_weight = 1.0

    def __init__(
        self,
        audio_engine: AudioEnginePort,
        storage: StoragePort,
        artifacts: ArtifactRepository,
        settings: AnalysisSettings,
    ) -> None:
        self._audio_engine = audio_engine
        self._storage = storage
        self._artifacts = artifacts
        self._settings = settings

    async def run(self, context: PipelineContext) -> PipelineContext:
        source_path = Path(context.working_audio_path or context.input_path)
        duration = context.duration or self._audio_engine.probe_duration(source_path)

        regions = build_regions(
            context.speaker_turns,
            duration,
            min_silence=self._settings.silence_min_duration,
            padding=self._settings.silence_keep_padding,
        )
        context.regions = regions

        ranges = keep_ranges(regions)
        if not ranges:
            # Nothing survived the cut (e.g. a silent file) — leave audio untouched
            # rather than raising, so downstream stages still get a valid path.
            return context

        cut_path = source_path.with_name(f"{source_path.stem}.cut{source_path.suffix}")
        result = self._audio_engine.assemble(source_path, ranges, cut_path)

        context.working_audio_path = str(result)
        context.temp_files.append(str(result))

        await persist_file_artifact(
            self._storage,
            self._artifacts,
            project_id=context.project_id,
            media_id=context.media_id,
            job_id=context.job_id,
            kind=ArtifactKind.CUT_AUDIO,
            file_path=result,
        )
        return context
