"""
ProjectService tests — listing projects and their media with latest-job status.

Fakes mirror the pattern in test_upload_service.py: in-memory repos so the
list/aggregate logic is tested without Postgres.
"""
from __future__ import annotations

import pytest

from src.application.services.project_service import ProjectNotFoundError, ProjectService
from src.domain.entities import Job, Media, Project
from src.domain.enums import JobKind, JobStatus


class FakeProjects:
    def __init__(self, rows: list[Project] | None = None) -> None:
        self.rows: dict[str, Project] = {p.id: p for p in (rows or [])}

    async def add(self, project: Project) -> Project:
        self.rows[project.id] = project
        return project

    async def get(self, project_id: str) -> Project | None:
        return self.rows.get(project_id)

    async def get_or_create(self, project_id: str, name: str) -> Project:
        existing = self.rows.get(project_id)
        if existing is not None:
            return existing
        project = Project(id=project_id, name=name)
        self.rows[project_id] = project
        return project

    async def list_all(self) -> list[Project]:
        return list(self.rows.values())


class FakeMedia:
    def __init__(self, rows: list[Media] | None = None) -> None:
        self.rows: list[Media] = rows or []

    async def add(self, media: Media) -> Media:
        self.rows.append(media)
        return media

    async def get(self, media_id: str) -> Media | None:
        return next((m for m in self.rows if m.id == media_id), None)

    async def list_by_project(self, project_id: str) -> list[Media]:
        return [m for m in self.rows if m.project_id == project_id]


class FakeJobs:
    def __init__(self, rows: list[Job] | None = None) -> None:
        self.rows: list[Job] = rows or []

    async def add(self, job: Job) -> Job:
        self.rows.append(job)
        return job

    async def get(self, job_id: str) -> Job | None:
        return next((j for j in self.rows if j.id == job_id), None)

    async def claim(self, job_id: str) -> Job | None:
        raise NotImplementedError

    async def set_status(self, job_id, status, error=None) -> None:
        raise NotImplementedError

    async def set_progress(self, job_id, progress, stage=None) -> None:
        raise NotImplementedError

    async def get_latest_for_media(self, media_id: str) -> Job | None:
        matches = [j for j in self.rows if j.media_id == media_id]
        return matches[-1] if matches else None


def _media(id: str, project_id: str) -> Media:
    return Media(id=id, project_id=project_id, filename=f"{id}.wav", storage_key=f"objects/{id}.wav", size_bytes=1)


class TestListProjects:
    async def test_returns_each_project_with_its_media_count(self):
        projects = FakeProjects([Project(id="p1", name="Take 1"), Project(id="p2", name="Take 2")])
        media = FakeMedia([_media("m1", "p1"), _media("m2", "p1"), _media("m3", "p2")])
        service = ProjectService(projects, media, FakeJobs())

        result = await service.list_projects()

        counts = {project.id: count for project, count in result}
        assert counts == {"p1": 2, "p2": 1}

    async def test_project_with_no_media_has_zero_count(self):
        projects = FakeProjects([Project(id="p1", name="Empty")])
        service = ProjectService(projects, FakeMedia(), FakeJobs())

        result = await service.list_projects()

        assert result == [(projects.rows["p1"], 0)]


class TestListMedia:
    async def test_returns_media_with_latest_job(self):
        projects = FakeProjects([Project(id="p1", name="Take 1")])
        media = FakeMedia([_media("m1", "p1")])
        job = Job(id="j1", media_id="m1", kind=JobKind.ANALYSIS, status=JobStatus.PROCESSING, progress=0.5)
        jobs = FakeJobs([job])
        service = ProjectService(projects, media, jobs)

        entries = await service.list_media("p1")

        assert len(entries) == 1
        assert entries[0].media.id == "m1"
        assert entries[0].latest_job is job

    async def test_media_without_a_job_yet_has_none(self):
        projects = FakeProjects([Project(id="p1", name="Take 1")])
        media = FakeMedia([_media("m1", "p1")])
        service = ProjectService(projects, media, FakeJobs())

        entries = await service.list_media("p1")

        assert entries[0].latest_job is None

    async def test_unknown_project_raises(self):
        service = ProjectService(FakeProjects(), FakeMedia(), FakeJobs())

        with pytest.raises(ProjectNotFoundError):
            await service.list_media("nope")
