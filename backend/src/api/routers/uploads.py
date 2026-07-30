"""
Upload routes — negotiate a client-direct transfer.

No endpoint here accepts a media body except the local-adapter sink, which
exists only so local development exercises the same client flow as S3. In
production (`STORAGE_PROVIDER=s3`) the bytes go from the client straight to the
bucket and never enter this process.

    POST /uploads              -> tickets
    (client PUTs to storage)
    POST /uploads/{id}/complete -> Media
    DELETE /uploads/{id}        -> abort
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response, status

from src.api.deps import storage_provider, upload_service
from src.api.schemas.uploads import (
    MediaOut,
    PartTicketOut,
    TicketOut,
    UploadCompleteRequest,
    UploadInitRequest,
    UploadInitResponse,
)
from src.application.services.upload_service import UploadService
from src.domain.errors import (
    FileTooLargeError,
    StorageError,
    UnsupportedMediaError,
    UploadNotFinishedError,
    UploadSessionNotFoundError,
    UploadSizeMismatchError,
    UploadStateError,
)
from src.domain.ports.services import StoragePort

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/uploads", tags=["uploads"])

_SINK_CHUNK = 1024 * 1024


@router.post(
    "",
    response_model=UploadInitResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Start an upload and receive presigned URLs",
)
async def init_upload(
    payload: UploadInitRequest,
    service: UploadService = Depends(upload_service),
) -> UploadInitResponse:
    """Validate the declaration and mint tickets. No bytes are transferred here."""
    try:
        session, single, parts = await service.init(
            filename=payload.filename,
            declared_size=payload.size_bytes,
            content_type=payload.content_type,
        )
    except UnsupportedMediaError as exc:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(exc)) from exc
    except FileTooLargeError as exc:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)) from exc
    except StorageError as exc:
        logger.exception("Storage refused to start an upload")
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    return UploadInitResponse(
        session_id=session.id,
        mode=session.mode,
        storage_key=session.storage_key,
        part_size=session.part_size,
        part_count=session.part_count,
        single=(
            TicketOut(
                url=single.url,
                method=single.method,
                headers=single.headers,
                expires_at=single.expires_at,
            )
            if single
            else None
        ),
        parts=[
            PartTicketOut(
                part_number=part.part_number,
                url=part.url,
                method=part.method,
                headers=part.headers,
            )
            for part in parts
        ],
        expires_at=session.expires_at,
    )


@router.post(
    "/{session_id}/complete",
    response_model=MediaOut,
    summary="Finalize an upload after the client has sent the bytes",
)
async def complete_upload(
    payload: UploadCompleteRequest,
    session_id: str = Path(..., max_length=32),
    service: UploadService = Depends(upload_service),
) -> MediaOut:
    """
    Verify against storage, then register the Media row.

    Idempotent — a client retrying after a lost response gets the same media.
    """
    parts = [(p.part_number, p.etag) for p in payload.parts]
    try:
        media = await service.complete(session_id, parts)
    except UploadSessionNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except UploadNotFinishedError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except (UploadSizeMismatchError, UnsupportedMediaError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except UploadStateError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except StorageError as exc:
        logger.exception("Storage failed to complete upload %s", session_id)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    return MediaOut(
        file_id=media.id,
        filename=media.filename,
        size_bytes=media.size_bytes,
        content_type=media.content_type,
        checksum=media.checksum,
    )


@router.delete(
    "/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
    summary="Abort an upload and discard any uploaded parts",
)
async def abort_upload(
    session_id: str = Path(..., max_length=32),
    service: UploadService = Depends(upload_service),
) -> None:
    try:
        await service.abort(session_id)
    except UploadSessionNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


# --- local-adapter sink ---------------------------------------------------------------
# Only reachable with STORAGE_PROVIDER=local. It plays the role S3 plays in
# production so the client-side upload path is identical in both modes.
@router.put(
    "/sink/{key:path}",
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
    summary="Local storage sink for presigned PUTs (dev only)",
)
async def local_sink(
    request: Request,
    key: str = Path(...),
    expires: int = Query(...),
    signature: str = Query(...),
    part: int | None = Query(default=None, ge=1),
    storage: StoragePort = Depends(storage_provider),
) -> dict[str, str]:
    """Accept a signed PUT and stream it to disk, mimicking S3's ETag response."""
    verify = getattr(storage, "verify", None)
    write_object = getattr(storage, "write_object", None)
    if verify is None or write_object is None:
        # S3 is configured; this endpoint must not be used as a bypass.
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not found.")

    if not verify(key, expires, signature, part):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Invalid or expired signature.")

    async def _chunks():
        async for chunk in request.stream():
            yield chunk

    try:
        size = await write_object(key, _chunks(), part=part)
    except StorageError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    # Deterministic stand-in for an S3 ETag; the client echoes it back on complete.
    etag = f"{part or 0:05d}-{size:d}"
    return {"etag": etag}
