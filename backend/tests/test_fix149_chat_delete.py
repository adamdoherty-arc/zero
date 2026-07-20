"""Fix-149 — chat session delete removes the DB rows, not just memory.

R1 (carried lead from run 6a8c5562): ``ChatService.delete_session`` only did
``del _sessions[session_id]``. Sessions are persisted by ``memory_service`` and
merged into ``list_sessions`` / rehydrated by ``get_session_history``, so:

  * a "deleted" chat resurrected on the next list/rehydrate (the DB rows
    survived the in-memory delete); and
  * a session already evicted from memory (24h TTL or a restart) returned False
    from delete_session -> the router raised 404, even though the user could
    still see the session in the list.

Fix: ``MemoryService.delete_session`` hard-deletes the session row plus every
message it owns; ``ChatService.delete_session`` now deletes from BOTH the
in-memory store and the DB and returns True if the session existed in EITHER.

These assert the specific behaviour (which tables are hit, in which order, and
the exact boolean for each existence case) rather than merely that the function
ran -- a "returned something" test could not have caught the original bug.
"""
from __future__ import annotations

from unittest.mock import patch


# ---------------------------------------------------------------------------
# MemoryService.delete_session -- the DB-side hard delete
# ---------------------------------------------------------------------------

class _FakeResult:
    def __init__(self, rowcount):
        self.rowcount = rowcount


class _FakeDB:
    """Async-context DB double: records statements, returns rowcounts in order."""

    def __init__(self, rowcounts):
        self._rowcounts = list(rowcounts)
        self.executed = []
        self.committed = False

    async def execute(self, stmt):
        self.executed.append(str(stmt))
        rc = self._rowcounts.pop(0) if self._rowcounts else 0
        return _FakeResult(rc)

    async def commit(self):
        self.committed = True

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _patch_sessionlocal(db):
    return patch("app.services.memory_service.AsyncSessionLocal", lambda: db)


async def test_memory_delete_hits_messages_then_session_and_commits():
    from app.services.memory_service import MemoryService

    db = _FakeDB([3, 1])  # 3 messages removed, then 1 session row
    with _patch_sessionlocal(db):
        existed = await MemoryService().delete_session("sess-1")

    assert existed is True
    assert db.committed is True
    assert len(db.executed) == 2
    # Messages are purged BEFORE the session so the delete holds even if the
    # live FK predates ondelete=CASCADE.
    assert "conversation_messages" in db.executed[0]
    assert "conversation_sessions" in db.executed[1]


async def test_memory_delete_false_when_nothing_existed():
    from app.services.memory_service import MemoryService

    db = _FakeDB([0, 0])
    with _patch_sessionlocal(db):
        existed = await MemoryService().delete_session("ghost")

    assert existed is False
    assert db.committed is True  # still a clean, committed no-op


async def test_memory_delete_true_when_only_orphan_messages():
    # Defensive: messages present but the session row is already gone.
    from app.services.memory_service import MemoryService

    db = _FakeDB([2, 0])
    with _patch_sessionlocal(db):
        assert await MemoryService().delete_session("orphan") is True


# ---------------------------------------------------------------------------
# ChatService.delete_session -- the memory + DB orchestration (the bug)
# ---------------------------------------------------------------------------

class _FakeMem:
    def __init__(self, db_result, raise_exc=False):
        self._db_result = db_result
        self._raise = raise_exc
        self.called_with = None

    async def delete_session(self, session_id):
        self.called_with = session_id
        if self._raise:
            raise RuntimeError("db down")
        return self._db_result


def _patch_mem(mem):
    return patch("app.services.memory_service.get_memory_service", lambda: mem)


async def test_chat_delete_db_only_session_returns_true_not_404():
    # THE 404 BUG: session persisted in the DB but evicted from memory.
    from app.services import chat_service
    from app.services.chat_service import ChatService

    chat_service._sessions.clear()
    mem = _FakeMem(db_result=True)
    with _patch_mem(mem):
        result = await ChatService.delete_session("db-only")

    assert result is True            # was False -> router 404
    assert mem.called_with == "db-only"


async def test_chat_delete_memory_only_still_purges_db():
    from app.services import chat_service
    from app.services.chat_service import ChatService, ConversationSession

    chat_service._sessions.clear()
    chat_service._sessions["m1"] = ConversationSession(session_id="m1")
    mem = _FakeMem(db_result=False)
    with _patch_mem(mem):
        result = await ChatService.delete_session("m1")

    assert result is True
    assert mem.called_with == "m1"       # DB purge attempted even for in-memory
    assert "m1" not in chat_service._sessions


async def test_chat_delete_neither_returns_false():
    from app.services import chat_service
    from app.services.chat_service import ChatService

    chat_service._sessions.clear()
    mem = _FakeMem(db_result=False)
    with _patch_mem(mem):
        assert await ChatService.delete_session("ghost") is False


async def test_chat_delete_survives_db_error_when_in_memory():
    from app.services import chat_service
    from app.services.chat_service import ChatService, ConversationSession

    chat_service._sessions.clear()
    chat_service._sessions["m2"] = ConversationSession(session_id="m2")
    mem = _FakeMem(db_result=False, raise_exc=True)
    with _patch_mem(mem):
        # DB delete raises, but the in-memory removal still succeeds.
        assert await ChatService.delete_session("m2") is True
    assert "m2" not in chat_service._sessions
