"""
Media routes — transcription of already-uploaded files.

Uploading lives in routers/uploads.py: clients send bytes straight to storage
with presigned URLs, so no media body passes through this process.

NOTE: /transcribe here runs Whisper inline for quick single-file use and will
block for the length of the audio. The async, outbox-backed pipeline (for long
files) is exposed via the jobs router; prefer it for anything sizeable.
"""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from anyio import to_thread
from fastapi import APIRouter, Depends, HTTPException, status

from src.api.deps import media_service, storage_provider, transcriber_provider
from src.api.schemas.media import ExportDownloadResponse, TranscriptionResponse, WordOut
from src.application.services.media_service import MediaService
from src.domain.errors import (
    MediaNotFoundError,
    OutOfMemoryError,
    StorageError,
    TranscriptionError,
)
from src.domain.ports.services import StoragePort, TranscriberPort

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/media", tags=["media"])


@router.post(
    "/transcribe/{file_id}",
    response_model=TranscriptionResponse,
    summary="Transcribe an uploaded file with word-level timestamps",
)
async def transcribe_media(
    file_id: str,
    language: str | None = None,
    service: MediaService = Depends(media_service),
    storage: StoragePort = Depends(storage_provider),
    transcriber: TranscriberPort = Depends(transcriber_provider),
) -> TranscriptionResponse:
    """Run the configured transcriber. The blocking call is offloaded to a thread."""
    media = await service.get(file_id)
    if media is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"No media '{file_id}'.")

    # Whisper needs a real file; with S3 this downloads, with the fs adapter it
    # resolves in place. TemporaryDirectory guarantees cleanup either way.
    with tempfile.TemporaryDirectory(prefix="takeflow-") as tmp:
        try:
            path: Path = await storage.materialize(media.storage_key, Path(tmp))
        except StorageError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

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


@router.get(
    "/{media_id}/export",
    response_model=ExportDownloadResponse,
    summary="Get a presigned download URL for the finished export",
)
async def get_export_download(
    media_id: str,
    service: MediaService = Depends(media_service),
) -> ExportDownloadResponse:
    """Mint a short-lived GET URL for the media's most recent EXPORT artifact.

    404s if no EXPORT job has completed for this media yet — the client should
    poll GET /jobs/{job_id} for the export job's status first.
    """
    try:
        ticket = await service.get_export_download(media_id)
    except MediaNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return ExportDownloadResponse(url=ticket.url, method=ticket.method, expires_at=ticket.expires_at)
