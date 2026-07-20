"""
Media routes — upload and (synchronous) transcription.

NOTE: /transcribe here runs Whisper inline for quick single-file use. The
async, outbox-backed analysis pipeline (for long files) is exposed via the jobs
router once Step 3/4 land; this endpoint stays for direct/testing use.
"""
from __future__ import annotations

import logging

from anyio import to_thread
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from src.api.deps import media_service, storage_provider, transcriber_provider
from src.api.schemas.media import TranscriptionResponse, UploadResponse, WordOut
from src.application.services.media_service import MediaService
from src.domain.errors import (
    FileTooLargeError,
    OutOfMemoryError,
    TranscriptionError,
    UnsupportedMediaError,
)
from src.domain.ports.services import StoragePort, TranscriberPort
from src.infrastructure.storage.local import LocalStorage

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/media", tags=["media"])

_CHUNK = 1024 * 1024  # 1 MiB streaming reads


async def _upload_chunks(upload: UploadFile):
    """Async generator adapting UploadFile to the StoragePort.save_stream contract."""
    while True:
        chunk = await upload.read(_CHUNK)
        if not chunk:
            break
        yield chunk


@router.post(
    "/upload",
    response_model=UploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a WAV/MP4 audio or video file",
)
async def upload_media(
    file: UploadFile = File(...),
    service: MediaService = Depends(media_service),
) -> UploadResponse:
    """Stream a (possibly multi-GB) file to storage, persist a Media row, return its id."""
    try:
        # Extension validation lives on the local adapter; guard generically here.
        ext = LocalStorage.validate_extension(file.filename or "")
    except UnsupportedMediaError as exc:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(exc)) from exc

    try:
        media = await service.upload(
            filename=file.filename or "upload",
            extension=ext,
            content_type=file.content_type,
            chunks=_upload_chunks(file),
        )
    except FileTooLargeError as exc:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)) from exc
    finally:
        await file.close()

    logger.info("Stored upload %s (%s, %d bytes)", media.id, media.filename, media.size_bytes)
    return UploadResponse(
        file_id=media.id,
        filename=media.filename,
        size_bytes=media.size_bytes,
        content_type=media.content_type,
    )


@router.post(
    "/transcribe/{file_id}",
    response_model=TranscriptionResponse,
    summary="Transcribe an uploaded file with word-level timestamps",
)
async def transcribe_media(
    file_id: str,
    language: str | None = None,
    storage: StoragePort = Depends(storage_provider),
    transcriber: TranscriberPort = Depends(transcriber_provider),
) -> TranscriptionResponse:
    """Run the configured transcriber. The blocking call is offloaded to a thread."""
    path = storage.resolve(file_id)
    if path is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"No upload for file_id '{file_id}'.")

    try:
        words, lang, lang_prob, duration = await to_thread.run_sync(
            transcriber.transcribe, path, language
        )
    except OutOfMemoryError as exc:
        raise HTTPException(status.HTTP_507_INSUFFICIENT_STORAGE, detail=str(exc)) from exc
    except TranscriptionError as exc:
        logger.exception("Transcription failed for %s", file_id)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

    return TranscriptionResponse(
        file_id=file_id,
        language=lang,
        language_probability=lang_prob,
        duration=duration,
        words=[
            WordOut(
                word=w.text, start=w.start, end=w.end,
                probability=w.probability, speaker=w.speaker,
            )
            for w in words
        ],
    )
