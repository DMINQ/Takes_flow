"""
SqlAlchemy OutboxRepository — the transactional outbox.

`add` is called within the same session/transaction as the job insert, so the
event and the job commit atomically. The relay (step 3) uses `fetch_pending`
(locking) and `mark_published` / `mark_failed`.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.enums import OutboxStatus
from src.infrastructure.models import OutboxModel


class SqlOutboxRepository:
    """Satisfies domain.ports.repositories.OutboxRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, stream: str, payload: dict) -> None:
        self._s.add(OutboxModel(stream=stream, payload=payload))
        await self._s.flush()

    async def fetch_pending(self, limit: int, max_attempts: int) -> list[dict]:
        """Lock-and-return pending events so multiple relays don't double-publish.

        Excludes events that already exhausted `max_attempts` — those are
        left `failed` and require manual/operator intervention, not endless
        relay retries.
        """
        stmt = (
            select(OutboxModel)
            .where(
                OutboxModel.status == OutboxStatus.PENDING.value,
                OutboxModel.attempts < max_attempts,
            )
            .order_by(OutboxModel.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        rows = (await self._s.execute(stmt)).scalars().all()
        return [
            {"id": r.id, "stream": r.stream, "payload": r.payload, "attempts": r.attempts}
            for r in rows
        ]

    async def mark_published(self, event_id: str) -> None:
        row = await self._s.get(OutboxModel, event_id)
        if row is None:
            return
        row.status = OutboxStatus.PUBLISHED.value
        await self._s.flush()

    async def mark_failed(self, event_id: str, attempts: int, max_attempts: int) -> None:
        """Record a failed publish attempt.

        Stays `pending` while retries remain (`attempts < max_attempts`) so
        the next `fetch_pending` picks it up again; becomes terminally
        `failed` once attempts are exhausted.
        """
        row = await self._s.get(OutboxModel, event_id)
        if row is None:
            return
        row.attempts = attempts
        row.status = (
            OutboxStatus.PENDING.value if attempts < max_attempts else OutboxStatus.FAILED.value
        )
        await self._s.flush()
