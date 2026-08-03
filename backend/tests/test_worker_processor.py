"""
Job processor tests — `process_job_event`.

Fakes stand in for the DB session, repositories, and pipeline registry so the
claim/build/run/finalize flow is tested without Postgres or a real pipeline,
matching the fake pattern in test_outbox_relay.py.
"""
from __future__ import annotations

import pytest

from src.domain.entities import Job, Media
from src.domain.enums import JobKind, JobStatus
from src.domain.errors import TranscriptionError
from src.worker import processor


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0

    async def __aenter__(self) -> "FakeSession":
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1


class FakeJobRepository:
    def __init__(self, job: Job | None) -> None:
        self._job = job
        self.statuses: list[tuple[str, JobStatus, str | None]] = []
        self.progress: list[tuple[str, float]] = []
        self.claim_calls = 0

    async def add(self, job):
        raise NotImplementedError

    async def get(self, job_id):
        return self._job

    async def claim(self, job_id: str) -> Job | None:
        self.claim_calls += 1
        return self._job

    async def set_status(self, job_id: str, status: JobStatus, error: str | None = None) -> None:
        self.statuses.append((job_id, status, error))

    async def set_progress(self, job_id: str, progress: float, stage: str | None = None) -> None:
        self.progress.append((job_id, progress))


class FakeMediaRepository:
    def __init__(self, media: Media | None) -> None:
        self._media = media

    async def add(self, media):
        raise NotImplementedError

    async def get(self, media_id: str) -> Media | None:
        return self._media


class FakePlugin:
    name = "fake"

    def __init__(self, fail_with: Exception | None = None) -> None:
        self._fail_with = fail_with

    async def run(self, context):
        if self._fail_with is not None:
            raise self._fail_with
        context.metadata["ran"] = True
        return context


def _job(job_id: str = "job-1") -> Job:
    return Job(id=job_id, media_id="media-1", kind=JobKind.ANALYSIS, status=JobStatus.PENDING)


def _media(media_id: str = "media-1") -> Media:
    return Media(
        id=media_id, project_id="project-1", filename="in.wav", storage_key="objects/in.wav", size_bytes=100
    )


@pytest.fixture
def patch_processor(monkeypatch):
    """Wire processor's hardcoded session/repos/registry to fakes."""

    def _patch(*, job: Job | None, media: Media | None, plugins: list | None = None):
        session = FakeSession()
        job_repo = FakeJobRepository(job)
        media_repo = FakeMediaRepository(media)

        monkeypatch.setattr(processor, "AsyncSessionLocal", lambda: session)
        monkeypatch.setattr(processor, "SqlJobRepository", lambda s: job_repo)
        monkeypatch.setattr(processor, "SqlMediaRepository", lambda s: media_repo)
        monkeypatch.setattr(processor, "register_pipelines", lambda s: None)
        if plugins is not None:
            monkeypatch.setattr(processor.registry, "build", lambda kind: plugins)

        return session, job_repo, media_repo

    return _patch


def _payload(job_id: str = "job-1", media_id: str = "media-1", kind: str = "analysis") -> dict:
    return {"job_id": job_id, "media_id": media_id, "kind": kind, "params": {}}


class TestProcessJobEvent:
    async def test_completes_job_on_successful_run(self, patch_processor):
        session, job_repo, _ = patch_processor(job=_job(), media=_media(), plugins=[FakePlugin()])

        await processor.process_job_event(_payload())

        assert job_repo.statuses == [("job-1", JobStatus.COMPLETED, None)]
        assert session.commits == 2  # claim commit + final commit

    async def test_marks_failed_on_plugin_domain_error(self, patch_processor):
        session, job_repo, _ = patch_processor(
            job=_job(), media=_media(), plugins=[FakePlugin(fail_with=TranscriptionError("bad audio"))]
        )

        await processor.process_job_event(_payload())

        assert len(job_repo.statuses) == 1
        job_id, status, error = job_repo.statuses[0]
        assert job_id == "job-1"
        assert status is JobStatus.FAILED
        assert "bad audio" in error

    async def test_marks_failed_on_unexpected_plugin_error(self, patch_processor):
        session, job_repo, _ = patch_processor(
            job=_job(), media=_media(), plugins=[FakePlugin(fail_with=ValueError("boom"))]
        )

        await processor.process_job_event(_payload())

        assert len(job_repo.statuses) == 1
        assert job_repo.statuses[0][1] is JobStatus.FAILED

    async def test_skips_when_job_cannot_be_claimed(self, patch_processor):
        session, job_repo, _ = patch_processor(job=None, media=_media())

        await processor.process_job_event(_payload())

        assert job_repo.statuses == []
        assert session.commits == 0

    async def test_marks_failed_when_media_missing(self, patch_processor):
        session, job_repo, _ = patch_processor(job=_job(), media=None)

        await processor.process_job_event(_payload())

        assert len(job_repo.statuses) == 1
        assert job_repo.statuses[0][1] is JobStatus.FAILED

    async def test_marks_failed_for_unknown_job_kind(self, patch_processor):
        session, job_repo, _ = patch_processor(job=_job(), media=_media())

        await processor.process_job_event(_payload(kind="not-a-kind"))

        assert len(job_repo.statuses) == 1
        assert job_repo.statuses[0][1] is JobStatus.FAILED

    async def test_ignores_malformed_payload(self, patch_processor):
        session, job_repo, _ = patch_processor(job=_job(), media=_media())

        await processor.process_job_event({"job_id": "job-1"})

        assert job_repo.claim_calls == 0
        assert job_repo.statuses == []
