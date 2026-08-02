"""
Outbox relay tests — `_publish_pending_batch`.

Fakes stand in for the DB session and the OutboxRepository/broker so the
publish/retry logic is tested without Postgres or Redis, matching the
in-memory-fake pattern used in test_upload_service.py.
"""
from __future__ import annotations

import pytest

from src.worker import relay


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0

    async def __aenter__(self) -> "FakeSession":
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1


class FakeOutboxRepository:
    def __init__(self, session: FakeSession, events: list[dict]) -> None:
        self._session = session
        self._events = events
        self.published: list[str] = []
        self.failed: list[tuple[str, int, int]] = []

    async def fetch_pending(self, limit: int, max_attempts: int) -> list[dict]:
        return [e for e in self._events if e["attempts"] < max_attempts][:limit]

    async def mark_published(self, event_id: str) -> None:
        self.published.append(event_id)

    async def mark_failed(self, event_id: str, attempts: int, max_attempts: int) -> None:
        self.failed.append((event_id, attempts, max_attempts))


class FakeBroker:
    def __init__(self, fail_ids: set[str] | None = None) -> None:
        self.fail_ids = fail_ids or set()
        self.published: list[tuple[dict, str]] = []

    async def publish(self, payload, *, stream: str) -> None:
        event_id = payload.get("event_id")
        if event_id in self.fail_ids:
            raise RuntimeError("broker unavailable")
        self.published.append((payload, stream))


@pytest.fixture
def patch_session(monkeypatch):
    """Wire relay's hardcoded AsyncSessionLocal/SqlOutboxRepository to fakes."""

    def _patch(events: list[dict]):
        session = FakeSession()
        repo = FakeOutboxRepository(session, events)

        monkeypatch.setattr(relay, "AsyncSessionLocal", lambda: session)
        monkeypatch.setattr(relay, "SqlOutboxRepository", lambda s: repo)
        return session, repo

    return _patch


def _event(event_id: str, stream: str = "takeflow.analysis", attempts: int = 0) -> dict:
    return {"id": event_id, "stream": stream, "payload": {"event_id": event_id}, "attempts": attempts}


class TestPublishPendingBatch:
    async def test_successful_publish_marks_published(self, patch_session):
        session, repo = patch_session([_event("e1")])
        broker = FakeBroker()

        await relay._publish_pending_batch(broker)

        assert repo.published == ["e1"]
        assert repo.failed == []
        assert session.commits == 1

    async def test_publish_failure_marks_failed_with_incremented_attempts(self, patch_session):
        session, repo = patch_session([_event("e1", attempts=2)])
        broker = FakeBroker(fail_ids={"e1"})

        await relay._publish_pending_batch(broker)

        assert repo.published == []
        assert repo.failed == [("e1", 3, 5)]
        assert session.commits == 1

    async def test_batch_processes_all_events_independently(self, patch_session):
        events = [_event("e1"), _event("e2", attempts=1), _event("e3")]
        session, repo = patch_session(events)
        broker = FakeBroker(fail_ids={"e2"})

        await relay._publish_pending_batch(broker)

        assert sorted(repo.published) == ["e1", "e3"]
        assert repo.failed == [("e2", 2, 5)]
        assert session.commits == 1

    async def test_no_pending_events_skips_commit(self, patch_session):
        session, repo = patch_session([])
        broker = FakeBroker()

        await relay._publish_pending_batch(broker)

        assert repo.published == []
        assert repo.failed == []
        assert session.commits == 0


class TestFetchPendingExcludesExhaustedEvents:
    async def test_exhausted_event_is_not_returned(self, patch_session):
        events = [_event("e1", attempts=5), _event("e2", attempts=4)]
        _, repo = patch_session(events)

        pending = await repo.fetch_pending(limit=50, max_attempts=5)

        assert [e["id"] for e in pending] == ["e2"]
