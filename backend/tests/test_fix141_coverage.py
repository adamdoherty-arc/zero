"""Fix-141 — respond/reflect/reason coverage-hunt findings (supervise run 1f1bf3ed).

F1  chat_service: list_sessions/get_session_history never rehydrated from DB —
    every zero-api restart blanked the Ask Zero sidebar and 404'd history.
F2  chat_service._build_message_window could drop the CURRENT user turn
    entirely when the system prompt ate the whole budget (empty window).
F3  character_content_service council vote: StructuredOutputError missing from
    the per-role except tuple — one role's failure aborted the whole vote.
F4  character_reference_video_service: StructuredOutputError escaped both
    pipeline handlers — _mark_failed never ran, rows froze in a non-terminal
    status _claim_one_pending can never re-select.
F5  voice_intent_router: "skip"/"skip it" lived in the ignore list, shadowing
    the skip intent (unreachable by its own name).
"""

import pytest

from langchain_core.messages import AIMessage, HumanMessage

from app.infrastructure.unified_llm_client import StructuredOutputError
from app.services.chat_service import (
    MAX_CONTEXT_CHARS,
    ChatService,
    _sessions,
)
from app.services.voice_intent_router import _keyword_classify


# ---------------------------------------------------------------------------
# F2 — sliding window must never drop the newest message
# ---------------------------------------------------------------------------


def test_window_keeps_newest_when_system_prompt_eats_budget():
    system_prompt = "s" * (MAX_CONTEXT_CHARS - 100)  # leaves budget of 100
    messages = [HumanMessage(content="x" * 500)]
    out = ChatService._build_message_window(system_prompt, messages)
    # [system, user] — the current turn survives (truncation allowed)
    assert len(out) == 2
    assert out[1]["role"] == "user"
    assert len(out[1]["content"]) > 0


def test_window_truncates_huge_newest_to_floor():
    system_prompt = "s" * (MAX_CONTEXT_CHARS - 10)
    messages = [HumanMessage(content="x" * 50_000)]
    out = ChatService._build_message_window(system_prompt, messages)
    assert len(out) == 2
    assert out[1]["content"] == "x" * 1024  # keep = max(budget, 1024)


def test_window_normal_flow_unchanged():
    system_prompt = "short"
    messages = [
        HumanMessage(content="one"),
        AIMessage(content="two"),
        HumanMessage(content="three"),
    ]
    out = ChatService._build_message_window(system_prompt, messages)
    assert [m["content"] for m in out[1:]] == ["one", "two", "three"]
    assert [m["role"] for m in out[1:]] == ["user", "assistant", "user"]


# ---------------------------------------------------------------------------
# F5 — skip intent reachable by its own name; ignore keeps its own triggers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("skip", "skip"),
        ("skip it", "skip"),
        ("next", "skip"),
        ("ignore", "ignore"),
        ("not now", "ignore"),
    ],
)
def test_skip_and_ignore_keywords_route_to_own_intents(text, expected):
    result = _keyword_classify(text, allowed=["ignore", "skip"])
    assert result is not None, f"{text!r} matched no intent"
    assert result.intent == expected


# ---------------------------------------------------------------------------
# F4 — StructuredOutputError must reach _mark_failed, not escape the loop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reference_video_structured_error_marks_failed(monkeypatch):
    from app.services.character_reference_video_service import (
        CharacterReferenceVideoService,
    )

    svc = CharacterReferenceVideoService()
    claims = iter(["cref-test-1"])
    failed = []

    async def fake_claim():
        return next(claims, None)

    async def fake_pipeline(ref_id):
        raise StructuredOutputError("retries exhausted")

    async def fake_mark_failed(ref_id, message):
        failed.append((ref_id, message))

    monkeypatch.setattr(svc, "_claim_one_pending", fake_claim)
    monkeypatch.setattr(svc, "_run_pipeline", fake_pipeline)
    monkeypatch.setattr(svc, "_mark_failed", fake_mark_failed)

    processed = await svc.process_pending(batch_size=3)
    assert processed == 0
    assert len(failed) == 1
    assert failed[0][0] == "cref-test-1"
    assert "retries exhausted" in failed[0][1]


# ---------------------------------------------------------------------------
# F1 — session history rehydrates from DB on cache miss; list merges DB rows
# ---------------------------------------------------------------------------


class _FakeMemoryService:
    def __init__(self, messages=None, sessions=None):
        self._messages = messages or []
        self._sessions = sessions or []

    async def get_messages(self, session_id, limit=50):
        return self._messages

    async def list_sessions(self, limit=50, include_archived=False):
        return self._sessions


@pytest.mark.asyncio
async def test_history_rehydrates_from_db_on_miss(monkeypatch):
    import app.services.memory_service as mem_mod

    fake = _FakeMemoryService(
        messages=[
            {"role": "human", "content": "hi"},
            {"role": "ai", "content": "hello"},
            {"role": "system", "content": "internal"},
        ]
    )
    monkeypatch.setattr(mem_mod, "get_memory_service", lambda: fake)
    _sessions.pop("fix141-restored", None)

    history = await ChatService.get_session_history("fix141-restored")
    assert history == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]


@pytest.mark.asyncio
async def test_history_unknown_session_still_404s(monkeypatch):
    import app.services.memory_service as mem_mod

    monkeypatch.setattr(mem_mod, "get_memory_service", lambda: _FakeMemoryService())
    _sessions.pop("fix141-nope", None)

    assert await ChatService.get_session_history("fix141-nope") is None


@pytest.mark.asyncio
async def test_list_sessions_merges_db_rows_without_duplicates(monkeypatch):
    import app.services.memory_service as mem_mod

    from app.services.chat_service import ConversationSession

    live = ConversationSession(session_id="fix141-live")
    _sessions["fix141-live"] = live

    fake = _FakeMemoryService(
        sessions=[
            {"session_id": "fix141-live", "title": "dup", "project_id": None,
             "message_count": 9, "created_at": "2026-07-11T00:00:00",
             "last_active": "2026-07-11T00:00:00"},
            {"session_id": "fix141-db-only", "title": "restored", "project_id": None,
             "message_count": 4, "created_at": "2026-07-10T00:00:00",
             "last_active": "2026-07-10T00:00:00"},
        ]
    )
    monkeypatch.setattr(mem_mod, "get_memory_service", lambda: fake)

    try:
        rows = await ChatService.list_sessions()
        ids = [r["session_id"] for r in rows]
        assert ids.count("fix141-live") == 1  # in-memory wins, no dup
        assert "fix141-db-only" in ids  # DB-persisted session visible again
        db_row = next(r for r in rows if r["session_id"] == "fix141-db-only")
        assert db_row["message_count"] == 4
    finally:
        _sessions.pop("fix141-live", None)
