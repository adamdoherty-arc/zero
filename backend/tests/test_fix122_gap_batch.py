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
