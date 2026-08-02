"""
Export pipeline plugin tests — AssembleExport, Master, PersistExport, LoadTimeline.

Fakes stand in for AudioEnginePort/StoragePort/ArtifactRepository/TimelineRepository
so each plugin's context mutation and side effects are tested without ffmpeg,
pedalboard, or Postgres/S3.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.application.pipeline.plugins.assemble_export import AssembleExportPlugin
from src.application.pipeline.plugins.load_timeline import LoadTimelinePlugin
from src.application.pipeline.plugins.master import MasterPlugin
from src.application.pipeline.plugins.persist_export import PersistExportPlugin
from src.domain.dto import PipelineContext
from src.domain.entities import Artifact, TimelineRegion
from src.domain.enums import ArtifactKind, RegionKind
from src.domain.errors import DomainError


def _context(tmp_path: Path, **overrides) -> PipelineContext:
    audio = tmp_path / "in.wav"
    audio.write_bytes(b"RIFFdata")
    base = dict(
        job_id="job-1",
        project_id="project-1",
        media_id="media-1",
        input_path=str(audio),
        original_filename="in.wav",
    )
    base.update(overrides)
    return PipelineContext(**base)


class FakeAudioEngine:
    def __init__(self) -> None:
        self.assembled: list[tuple[Path, list[tuple[float, float]], Path]] = []
        self.mastered: list[tuple[Path, Path]] = []

    def probe_duration(self, media_path: Path) -> float:
        return 10.0

    def preprocess(self, media_path: Path, out_path: Path) -> Path:
        raise NotImplementedError

    def assemble(self, media_path: Path, keep_ranges, out_path: Path) -> Path:
        self.assembled.append((media_path, keep_ranges, out_path))
        out_path.write_bytes(b"assembled")
        return out_path

    def master(self, media_path: Path, out_path: Path) -> Path:
        self.mastered.append((media_path, out_path))
        out_path.write_bytes(b"mastered")
        return out_path


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


class FakeTimelineRepository:
    def __init__(self, regions: list[TimelineRegion]) -> None:
        self._regions = regions

    async def save_regions(self, job_id, media_id, regions):
        raise NotImplementedError

    async def get_regions(self, media_id: str) -> list[TimelineRegion]:
        return self._regions


class TestAssembleExportPlugin:
    async def test_assembles_keep_ranges_from_regions(self, tmp_path):
        engine = FakeAudioEngine()
        plugin = AssembleExportPlugin(engine)
        regions = [TimelineRegion(start=0.0, end=5.0, kind=RegionKind.KEEP)]
        context = _context(tmp_path, regions=regions)

        result = await plugin.run(context)

        assert engine.assembled
        _, ranges, _ = engine.assembled[0]
        assert ranges == [(0.0, 5.0)]
        assert result.working_audio_path.endswith(".assembled.wav")

    async def test_raises_when_nothing_survives_selection(self, tmp_path):
        engine = FakeAudioEngine()
        plugin = AssembleExportPlugin(engine)
        regions = [TimelineRegion(start=0.0, end=5.0, kind=RegionKind.AUTO_CUT)]
        context = _context(tmp_path, regions=regions)

        with pytest.raises(DomainError):
            await plugin.run(context)


class TestMasterPlugin:
    async def test_applies_mastering_and_sets_output_path(self, tmp_path):
        engine = FakeAudioEngine()
        plugin = MasterPlugin(engine)
        context = _context(tmp_path)

        result = await plugin.run(context)

        assert engine.mastered
        assert result.output_path == result.working_audio_path
        assert result.output_path.endswith(".mastered.wav")


class TestPersistExportPlugin:
    async def test_persists_output_as_export_artifact(self, tmp_path):
        storage, artifacts = FakeStorage(), FakeArtifactRepository()
        plugin = PersistExportPlugin(storage, artifacts)

        output = tmp_path / "final.wav"
        output.write_bytes(b"final")
        context = _context(tmp_path, output_path=str(output))

        result = await plugin.run(context)

        assert len(artifacts.added) == 1
        assert artifacts.added[0].kind is ArtifactKind.EXPORT
        assert "export_artifact_id" in result.metadata

    async def test_raises_without_output_path(self, tmp_path):
        storage, artifacts = FakeStorage(), FakeArtifactRepository()
        plugin = PersistExportPlugin(storage, artifacts)
        context = _context(tmp_path)

        with pytest.raises(ValueError):
            await plugin.run(context)


class TestLoadTimelinePlugin:
    async def test_loads_regions_into_context(self, tmp_path):
        regions = [TimelineRegion(start=0.0, end=5.0, kind=RegionKind.KEEP)]
        plugin = LoadTimelinePlugin(FakeTimelineRepository(regions))
        context = _context(tmp_path)

        result = await plugin.run(context)

        assert result.regions == regions

    async def test_raises_when_no_regions_exist(self, tmp_path):
        plugin = LoadTimelinePlugin(FakeTimelineRepository([]))
        context = _context(tmp_path)

        with pytest.raises(DomainError):
            await plugin.run(context)
