"""
Pipeline core tests — Runner + registry.

Uses trivial fake plugins/repos so the runner's sequencing, progress reporting,
error translation and temp-file cleanup are tested without any real I/O.
"""
from __future__ import annotations

import pytest

from src.application.pipeline.plugin import BasePlugin
from src.application.pipeline.registry import PipelineRegistry
from src.application.pipeline.runner import PipelineError, Runner
from src.domain.dto import PipelineContext
from src.domain.enums import JobKind
from src.domain.errors import TranscriptionError


def _context(job_id: str = "job-1") -> PipelineContext:
    return PipelineContext(
        job_id=job_id,
        project_id="project-1",
        media_id="media-1",
        input_path="/tmp/in.wav",
        original_filename="in.wav",
    )


class RecordingPlugin(BasePlugin):
    name = "recorder"

    def __init__(self, log: list[str], marker: str) -> None:
        self._log = log
        self._marker = marker

    async def run(self, context: PipelineContext) -> PipelineContext:
        self._log.append(self._marker)
        context.metadata[self._marker] = True
        return context


class FailingPlugin(BasePlugin):
    name = "boom"

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    async def run(self, context: PipelineContext) -> PipelineContext:
        raise self._exc


class FakeJobRepository:
    def __init__(self) -> None:
        self.progress: list[tuple[str, float]] = []
        self.stages: list[str | None] = []

    async def add(self, job):
        raise NotImplementedError

    async def get(self, job_id):
        raise NotImplementedError

    async def claim(self, job_id):
        raise NotImplementedError

    async def set_status(self, job_id, status, error=None):
        raise NotImplementedError

    async def set_progress(self, job_id: str, progress: float, stage: str | None = None) -> None:
        self.progress.append((job_id, progress))
        self.stages.append(stage)


class TestRunner:
    async def test_runs_plugins_in_order_and_reports_progress(self):
        log: list[str] = []
        jobs = FakeJobRepository()
        runner = Runner([RecordingPlugin(log, "a"), RecordingPlugin(log, "b")], jobs)

        result = await runner.run(_context())

        assert log == ["a", "b"]
        assert result.metadata == {"a": True, "b": True}
        # Runner reports progress before and after each stage (start-of-stage +
        # end-of-stage), using each plugin's progress_weight (default 1.0 here).
        assert jobs.progress == [
            ("job-1", 0.0),
            ("job-1", 0.5),
            ("job-1", 0.5),
            ("job-1", 1.0),
        ]
        assert jobs.stages == ["a", "a", "b", "b"]

    async def test_domain_error_propagates_unwrapped(self):
        runner = Runner([FailingPlugin(TranscriptionError("bad audio"))])

        with pytest.raises(TranscriptionError):
            await runner.run(_context())

    async def test_unexpected_error_wrapped_with_stage_name(self):
        runner = Runner([FailingPlugin(ValueError("boom"))])

        with pytest.raises(PipelineError) as exc_info:
            await runner.run(_context())

        assert exc_info.value.stage == "boom"

    async def test_cleans_up_temp_files_even_on_failure(self, tmp_path):
        leftover = tmp_path / "scratch.wav"
        leftover.write_bytes(b"data")

        class RegistersTempFile(BasePlugin):
            name = "register_temp"

            async def run(self, context: PipelineContext) -> PipelineContext:
                context.temp_files.append(str(leftover))
                raise ValueError("downstream failure")

        runner = Runner([RegistersTempFile()])

        with pytest.raises(PipelineError):
            await runner.run(_context())

        assert not leftover.exists()


class TestPipelineRegistry:
    async def test_build_returns_factory_result(self):
        registry = PipelineRegistry()
        plugin = RecordingPlugin([], "only")
        registry.register(JobKind.ANALYSIS, lambda: [plugin])

        plugins = registry.build(JobKind.ANALYSIS)

        assert plugins == [plugin]

    def test_build_raises_for_unregistered_kind(self):
        registry = PipelineRegistry()

        with pytest.raises(KeyError):
            registry.build(JobKind.EXPORT)
