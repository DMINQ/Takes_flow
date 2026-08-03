"""
Project routes — list projects and the media inside them.

Projects themselves are created implicitly by UploadService (POST /uploads
with an omitted project_id starts a new one; passing an existing project_id
adds another file to it). This router is read-only:

    GET /projects              -> every project + media count
    GET /projects/{id}/media   -> every media in one project, with its latest
                                   job status (so the frontend knows whether to
                                   route to Analysis or Timeline for each file)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from src.api.deps import project_service
from src.api.schemas.projects import ProjectMediaOut, ProjectOut
from src.application.services.project_service import ProjectNotFoundError, ProjectService

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=list[ProjectOut], summary="List all projects")
async def list_projects(
    service: ProjectService = Depends(project_service),
) -> list[ProjectOut]:
    projects = await service.list_projects()
    return [
        ProjectOut(id=project.id, name=project.name, created_at=project.created_at, media_count=count)
        for project, count in projects
    ]


@router.get(
    "/{project_id}/media",
    response_model=list[ProjectMediaOut],
    summary="List the media files inside one project",
)
async def list_project_media(
    project_id: str,
    service: ProjectService = Depends(project_service),
) -> list[ProjectMediaOut]:
    try:
        entries = await service.list_media(project_id)
    except ProjectNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return [
        ProjectMediaOut(
            id=entry.media.id,
            filename=entry.media.filename,
            duration=entry.media.duration,
            created_at=entry.media.created_at,
            latest_job_id=entry.latest_job.id if entry.latest_job else None,
            latest_job_kind=entry.latest_job.kind.value if entry.latest_job else None,
            latest_job_status=entry.latest_job.status if entry.latest_job else None,
            latest_job_progress=entry.latest_job.progress if entry.latest_job else None,
            latest_job_stage=entry.latest_job.stage if entry.latest_job else None,
        )
        for entry in entries
    ]
