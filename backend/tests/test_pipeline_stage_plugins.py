"""
Pipeline stage-plugin tests: Denoise, Diarize, CutSilence, PersistTranscript.

Fakes stand in for AudioEnginePort/DiarizerPort/StoragePort/ArtifactRepository
so each plugin's context mutation and artifact-persistence call are tested
without ffmpeg, a real diarizer, or Postgres/S3.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.application.pipeline.plugins.cut_silence import CutSilencePlugin
from src.application.pipeline.plugins.denoise import DenoisePlugin
from src.application.pipeline.plugins.diarize import DiarizePlugin
from src.application.pipeline.plugins.persist_transcript import PersistTranscriptPlugin
from src.domain.dto import PipelineContext
from src.domain.entities import Artifact, SpeakerTurn, Word
from src.domain.enums import ArtifactKind
from src.settings.config import AnalysisSettings


def _context(tmp_path: Path, **overrides) -> PipelineContext:
    audio = tmp_path / "in.wav"
    audio.write_bytes(b"RIFFdata")
    base = dict(
        job_id="job-1",
        project_id="project-1",
        media_id="media-1",
        input_path=str(audio),
        working_audio_path=str(audio),
        original_filename="in.wav",
    )
    base.update(overrides)
    return PipelineContext(**base)


class FakeStorage:
    def __init__(self) -> None:
        self.saved: dict[str, bytes] = {}

    async def save_stream(self, key, chunks):
        data = b""
        async for chunk in chunks:
            data += chunk
        self.saved[key] = data
        from src.domain.entities import StoredObject

        return StoredObject(key=key, size_bytes=len(data))


class FakeArtifactRepository:
    def __init__(self) -> None:
        self.added: list[Artifact] = []

    async def add(self, artifact: Artifact) -> Artifact:
        self.added.append(artifact)
        return artifact

    async def get(self, media_id, kind):
        for a in reversed(self.added):
            if a.media_id == media_id and a.kind == kind:
                return a
        return None


class FakeAudioEngine:
    def __init__(self, duration: float = 10.0) -> None:
        self.duration = duration
        self.assembled: list[tuple[Path, list[tuple[float, float]], Path]] = []

    def probe_duration(self, media_path: Path) -> float:
        return self.duration

    def preprocess(self, media_path: Path, out_path: Path) -> Path:
        out_path.write_bytes(media_path.read_bytes())
        return out_path

    def assemble(self, media_path: Path, keep_ranges, out_path: Path) -> Path:
        self.assembled.append((media_path, keep_ranges, out_path))
        out_path.write_bytes(b"assembled")
        return out_path

    def master(self, media_path: Path, out_path: Path) -> Path:
        raise NotImplementedError


class FakeDiarizer:
    def __init__(self, turns: list[SpeakerTurn]) -> None:
        self._turns = turns

    def diarize(self, media_path: Path) -> list[SpeakerTurn]:
        return self._turns


class TestDenoisePlugin:
    async def test_updates_working_audio_and_persists_artifact(self, tmp_path):
        storage, artifacts = FakeStorage(), FakeArtifactRepository()
        plugin = DenoisePlugin(FakeAudioEngine(), storage, artifacts)
        context = _context(tmp_path)

        result = await plugin.run(context)

        assert result.working_audio_path != str(tmp_path / "in.wav")
        assert Path(result.working_audio_path).name == "in.denoised.wav"
        assert len(artifacts.added) == 1
        assert artifacts.added[0].kind is ArtifactKind.DENOISED_AUDIO
        assert result.temp_files == [result.working_audio_path]


class TestDiarizePlugin:
    async def test_populates_speaker_turns_and_persists_json_artifact(self, tmp_path):
        storage, artifacts = FakeStorage(), FakeArtifactRepository()
        turns = [SpeakerTurn(start=0.0, end=5.0, speaker_id="0")]
        plugin = DiarizePlugin(FakeDiarizer(turns), storage, artifacts)
        context = _context(tmp_path)

        result = await plugin.run(context)

        assert result.speaker_turns == turns
        assert len(artifacts.added) == 1
        assert artifacts.added[0].kind is ArtifactKind.DIARIZATION
        saved_key = artifacts.added[0].storage_key
        assert saved_key in storage.saved


class TestCutSilencePlugin:
    async def test_builds_regions_and_assembles_kept_ranges(self, tmp_path):
        storage, artifacts = FakeStorage(), FakeArtifactRepository()
        engine = FakeAudioEngine(duration=6.0)
        settings = AnalysisSettings(silence_min_duration=0.6, silence_keep_padding=0.0)
        plugin = CutSilencePlugin(engine, storage, artifacts, settings)

        turns = [
            SpeakerTurn(start=0.0, end=2.0, speaker_id="0"),
            SpeakerTurn(start=4.0, end=6.0, speaker_id="0"),
        ]
        context = _context(tmp_path, speaker_turns=turns, duration=6.0)

        result = await plugin.run(context)

        assert len(result.regions) == 3  # keep, cut, keep
        assert engine.assembled  # assemble was called
        _, ranges, _ = engine.assembled[0]
        assert ranges == [(0.0, 2.0), (4.0, 6.0)]
        assert len(artifacts.added) == 1
        assert artifacts.added[0].kind is ArtifactKind.CUT_AUDIO

    async def test_no_speech_at_all_skips_assembly(self, tmp_path):
        storage, artifacts = FakeStorage(), FakeArtifactRepository()
        engine = FakeAudioEngine(duration=3.0)
        settings = AnalysisSettings(silence_min_duration=0.6, silence_keep_padding=0.0)
        plugin = CutSilencePlugin(engine, storage, artifacts, settings)

        context = _context(tmp_path, speaker_turns=[], duration=3.0)

        result = await plugin.run(context)

        assert not engine.assembled
        assert artifacts.added == []
        assert len(result.regions) == 1


class TestPersistTranscriptPlugin:
    async def test_persists_words_as_json_artifact(self, tmp_path):
        storage, artifacts = FakeStorage(), FakeArtifactRepository()
        plugin = PersistTranscriptPlugin(storage, artifacts)

        context = _context(
            tmp_path,
            words=[Word(text="hi", start=0.0, end=0.5, probability=0.9)],
            detected_language="en",
            language_probability=0.99,
        )

        await plugin.run(context)

        assert len(artifacts.added) == 1
        assert artifacts.added[0].kind is ArtifactKind.TRANSCRIPT
