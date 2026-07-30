"""
UploadService — negotiates client-direct uploads.

The API mediates but never carries the bytes:

    1. init      client declares filename/size -> validated -> presigned tickets
    2. (client)  PUTs the object (or its parts) straight to storage, in parallel
    3. complete  server asks storage for the truth, sniffs magic bytes, then
                 creates the Media row

Nothing the client says is trusted. The declared size only enables a cheap early
rejection; the authoritative size comes from `storage.stat`, and the real
container type from the object's first bytes. `complete` is idempotent so a
client retrying after a dropped response does not create a second Media row.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain import upload_policy as policy
from src.domain.entities import Media, PartUploadTicket, UploadSession, UploadTicket
from src.domain.enums import UploadMode, UploadStatus
from src.domain.errors import (
    UnsupportedMediaError,
    UploadNotFinishedError,
    UploadSessionNotFoundError,
    UploadSizeMismatchError,
    UploadStateError,
)
from src.domain.ports.repositories import MediaRepository, UploadSessionRepository
from src.domain.ports.services import StoragePort
from src.settings.config import CoreSettings, StorageSettings

logger = logging.getLogger(__name__)

# Enough to cover every signature we check, including ISO-BMFF's 'ftyp' at offset 4.
_SNIFF_BYTES = 16


class UploadService:
    def __init__(
        self,
        session: AsyncSession,
        sessions: UploadSessionRepository,
        media_repo: MediaRepository,
        storage: StoragePort,
        core: CoreSettings,
        storage_settings: StorageSettings,
    ) -> None:
        self._session = session
        self._sessions = sessions
        self._media = media_repo
        self._storage = storage
        self._core = core
        self._settings = storage_settings

    async def init(
        self, *, filename: str, declared_size: int, content_type: str | None
    ) -> tuple[UploadSession, UploadTicket | None, list[PartUploadTicket]]:
        """
        Validate the declaration, reserve a key, mint tickets.

        Returns (session, single_ticket, part_tickets) — exactly one of the two
        ticket forms is populated, depending on the planned mode.
        """
        extension = policy.validate_extension(filename)
        policy.validate_declared_size(declared_size, self._core.max_upload_bytes)

        media_id = policy.new_media_id()
        key = policy.build_storage_key(media_id, extension)
        mode, part_size, part_count = policy.plan_upload(declared_size)
        ttl = self._settings.presign_ttl_seconds

        upload_id: str | None = None
        single: UploadTicket | None = None
        parts: list[PartUploadTicket] = []

        if mode is UploadMode.SINGLE:
            single = await self._storage.presign_put(
                key, content_type=content_type, expires_in=ttl
            )
        else:
            upload_id = await self._storage.create_multipart(key, content_type=content_type)
            parts = await self._storage.presign_parts(
                key, upload_id, part_numbers=list(range(1, (part_count or 0) + 1)), expires_in=ttl
            )

        session = UploadSession(
            id=policy.new_media_id(),
            storage_key=key,
            filename=filename,
            declared_size=declared_size,
            mode=mode,
            status=UploadStatus.INITIATED,
            upload_id=upload_id,
            part_size=part_size,
            part_count=part_count,
            content_type=content_type,
            media_id=media_id,  # reserved now, only persisted as Media on complete
            expires_at=policy.ticket_expiry(ttl),
        )
        saved = await self._sessions.add(session)
        await self._session.commit()
        logger.info(
            "Upload session %s initiated: key=%s mode=%s parts=%s",
            saved.id, key, mode.value, part_count,
        )
        return saved, single, parts

    async def complete(self, session_id: str, parts: list[tuple[int, str]] | None = None) -> Media:
        """
        Verify the upload against storage and register the Media row.

        Idempotent: completing an already-completed session returns the existing
        Media instead of duplicating it, which matters because clients retry.
        """
        session = await self._require_session(session_id)

        if session.status is UploadStatus.COMPLETED:
            existing = await self._media.get(session.media_id or "")
            if existing is not None:
                return existing
            # Session says completed but Media vanished — treat as inconsistent.
            raise UploadStateError(f"Session '{session_id}' is completed but its media is missing.")

        if session.status is not UploadStatus.INITIATED:
            raise UploadStateError(
                f"Session '{session_id}' is {session.status.value}; it can no longer be completed."
            )

        if session.mode is UploadMode.MULTIPART:
            if not parts:
                raise UploadNotFinishedError("Multipart completion requires the uploaded part list.")
            if session.part_count and len(parts) != session.part_count:
                raise UploadNotFinishedError(
                    f"Expected {session.part_count} parts, got {len(parts)}."
                )
            stored = await self._storage.complete_multipart(
                session.storage_key, session.upload_id or "", parts
            )
        else:
            found = await self._storage.stat(session.storage_key)
            if found is None:
                raise UploadNotFinishedError("No object found in storage for this session.")
            stored = found

        # Storage is the authority on size; the declaration was only a hint.
        if stored.size_bytes != session.declared_size:
            await self._fail(session, UploadStatus.ABORTED)
            raise UploadSizeMismatchError(
                f"Declared {session.declared_size} bytes but stored object is {stored.size_bytes}."
            )
        if stored.size_bytes > self._core.max_upload_bytes:
            await self._fail(session, UploadStatus.ABORTED)
            raise UploadSizeMismatchError("Stored object exceeds the configured maximum.")

        await self._verify_content(session)

        media = Media(
            id=session.media_id or policy.new_media_id(),
            filename=session.filename,
            storage_key=session.storage_key,
            size_bytes=stored.size_bytes,
            content_type=stored.content_type or session.content_type,
            checksum=stored.etag,
        )
        saved = await self._media.add(media)
        await self._sessions.set_status(session.id, UploadStatus.COMPLETED, media_id=saved.id)
        await self._session.commit()
        logger.info("Upload session %s completed as media %s", session.id, saved.id)
        return saved

    async def abort(self, session_id: str) -> None:
        """Client-initiated cancel: discard parts so storage is not billed for them."""
        session = await self._require_session(session_id)
        if session.status is not UploadStatus.INITIATED:
            return
        await self._discard(session)
        await self._sessions.set_status(session.id, UploadStatus.ABORTED)
        await self._session.commit()

    async def reap_stale(self, limit: int = 100) -> int:
        """
        Abort sessions whose tickets expired without completion.

        Without this, multipart parts linger in the bucket and are billed
        indefinitely. Runs from the worker on a schedule.
        """
        stale = await self._sessions.fetch_stale(limit)
        for session in stale:
            await self._discard(session)
            await self._sessions.set_status(session.id, UploadStatus.EXPIRED)
        if stale:
            await self._session.commit()
            logger.info("Reaped %d stale upload sessions", len(stale))
        return len(stale)

    # --- internals -------------------------------------------------------------------
    async def _require_session(self, session_id: str) -> UploadSession:
        session = await self._sessions.get(session_id)
        if session is None:
            raise UploadSessionNotFoundError(f"No upload session '{session_id}'.")
        return session

    async def _verify_content(self, session: UploadSession) -> None:
        """Sniff magic bytes: a client can rename any file to .wav."""
        extension = policy.validate_extension(session.filename)
        header = await self._storage.open_range(session.storage_key, start=0, length=_SNIFF_BYTES)
        if not policy.sniff_matches_extension(header, extension):
            await self._fail(session, UploadStatus.ABORTED)
            raise UnsupportedMediaError(
                f"File contents do not match the '{extension}' extension."
            )

    async def _fail(self, session: UploadSession, status: UploadStatus) -> None:
        await self._discard(session)
        await self._sessions.set_status(session.id, status)
        await self._session.commit()

    async def _discard(self, session: UploadSession) -> None:
        if session.mode is UploadMode.MULTIPART and session.upload_id:
            await self._storage.abort_multipart(session.storage_key, session.upload_id)
        else:
            await self._storage.delete(session.storage_key)

    @staticmethod
    def is_expired(session: UploadSession, *, now: datetime | None = None) -> bool:
        if session.expires_at is None:
            return False
        return (now or datetime.now(timezone.utc)) > session.expires_at
