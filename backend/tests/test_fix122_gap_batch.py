"""
Fix-122 — reflect+reason+respond coverage batch (3 source-verified gaps).

Discriminating regression tests: each FAILS against the pre-fix code and
PASSES against the fix. Run: pytest backend/tests/test_fix122_gap_batch.py -v

  RFL-A  reachy_user_memory_service.maybe_extract() fired a bare
         asyncio.create_task -> GC-cancellable -> durable user notes silently
         lost. Fix anchors the task in self._bg_tasks.
  RSN-A  orchestration_graph.council_node listed decisions with
         `confidence_score:.0f%` but confidence_score is None for un-voted
         decisions (list_decisions(limit=10) returns those) -> TypeError
         swallowed by the except -> the "list council decisions" reply died.
  RSP-LH-1  local_handler llm_timeout early-return leaked eager motion tasks
         (the timeout returns the 3-tuple with live eager_tasks; only the
         tool-timeout/normal/httpx paths cancelled). Fix cancels before return.
"""
import asyncio
import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest


# ---------------------------------------------------------------------------
# RFL-A — durable-note extraction task is anchored (not GC-cancellable)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_rfla_maybe_extract_anchors_background_task():
    from app.services.reachy_user_memory_service import (
        ReachyUserMemoryService,
        EXTRACT_EVERY_N_TURNS,
    )

    # Real constructor so the __init__ change (adds _bg_tasks) is exercised too.
    svc = ReachyUserMemoryService()
    # PRE-FIX: no _bg_tasks attribute. POST-FIX: __init__ creates the anchor set.
    assert hasattr(svc, "_bg_tasks"), "fix adds a _bg_tasks anchor set in __init__"
    # Content is irrelevant — _extract_and_save is mocked; maybe_extract only
    # needs _turns non-empty + the counter on an extraction boundary.
    svc._turns = [object() for _ in range(EXTRACT_EVERY_N_TURNS)]
    svc._notes = []
    svc._bg_tasks = set()
    # Cross the extraction boundary.
    svc._turn_counter = EXTRACT_EVERY_N_TURNS

    started = asyncio.Event()
    release = asyncio.Event()

    async def _fake_extract(recent):
        started.set()
        await release.wait()

    svc._extract_and_save = _fake_extract

    await svc.maybe_extract()
    await asyncio.wait_for(started.wait(), timeout=1.0)

    # The in-flight task MUST be strongly referenced so the GC can't cancel it.
    assert len(svc._bg_tasks) == 1, "in-flight extraction task is anchored"
    task = next(iter(svc._bg_tasks))
    assert not task.done()

    release.set()
    await asyncio.wait_for(task, timeout=1.0)
    # done_callback removes it from the set.
    assert len(svc._bg_tasks) == 0


# ---------------------------------------------------------------------------
# RSN-A — council list handles None confidence_score without dying
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_rsna_council_list_handles_none_confidence(monkeypatch):
    from app.services import orchestration_graph as og

    # A freshly-proposed decision: decision=None AND confidence_score=None.
    unvoted = SimpleNamespace(
        id="d1", topic="ship the thing", decision=None, confidence_score=None
    )
    voted = SimpleNamespace(
        id="d2", topic="hire someone", decision="approve", confidence_score=88.0
    )

    class _FakeCouncil:
        async def list_decisions(self, status=None, pending_only=False, limit=20):
            return [unvoted, voted]

    # council_node does a local `from app.services.council_service import
    # get_council_service` inside the function, so patch it at the source module.
    import app.services.council_service as council_mod
    monkeypatch.setattr(council_mod, "get_council_service", lambda: _FakeCouncil())

    state = {"messages": [SimpleNamespace(content="list council decisions")]}
    out = await og.council_node(state)
    text = out["result"]

    # PRE-FIX: TypeError on None:.0f -> swallowed -> "Council query failed: ...".
    assert "Council query failed" not in text, f"council list must not crash: {text}"
    # The un-voted decision renders as 'pending', the voted one as a percentage.
    assert "pending" in text
    assert "88%" in text


# ---------------------------------------------------------------------------
# RSP-LH-1 — llm_timeout early-return cancels eager motion tasks
# ---------------------------------------------------------------------------
def test_rsplh1_llm_timeout_return_cancels_eager_tasks():
    """The llm_timeout branch must cancel eager_tasks BEFORE returning, the
    same as the tool-timeout / normal-round / httpx-error paths. Verified at
    source: the cancel loop must appear between the `local LLM timed out`
    guard and its `return` (the branch is otherwise un-runtime-testable
    robot-off without a full LocalHandler+websocket harness)."""
    # Resolve relative to this test file so it works on host (backend/tests/)
    # and inside the container (/app/tests/, backend root mounted at /app).
    here = Path(__file__).resolve().parent
    candidates = [
        here.parent / "app/services/reachy_realtime/local_handler.py",
        here / "app/services/reachy_realtime/local_handler.py",
    ]
    path = next((p for p in candidates if p.exists()), candidates[0])
    src = path.read_text(encoding="utf-8")

    guard = 'if self._last_error == "local LLM timed out":'
    assert guard in src
    after = src.split(guard, 1)[1]
    # The branch ends at its emit_phase("stalled", ...) marker just before the
    # `return`. Anchor on that (not the word "return", which also appears in the
    # explanatory comment) so the check is unambiguous.
    marker = '_emit_phase("stalled", reason="llm_timeout")'
    assert marker in after
    branch_body = after.split(marker, 1)[0]
    assert "for _orphan in eager_tasks.values():" in branch_body, (
        "llm_timeout early-return must cancel eager_tasks before returning"
    )
    assert "_orphan.cancel()" in branch_body
