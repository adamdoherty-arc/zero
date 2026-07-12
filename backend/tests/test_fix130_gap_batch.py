"""
Fix-130 (supervise cb0befc3) regression guards.

Three coverage-domain fixes, one per audited domain:
  - ACT-C2 (act-with-approval): the reachy_email FSM router must be gated by the
    gateway token. Its /text-input + /voice-input transitions can reach
    `awaiting_send_confirmation` -> _send_pending_reply() -> gmail.send_email()
    DIRECTLY, so a bare APIRouter() left an unauthenticated email-send window.
  - LRN-N5 (learn): content_learning_engine.process_content_outcomes had a narrow
    OUTER guard (ValueError,KeyError,TypeError,ImportError) while the per-record
    loop already caught Exception; a transient DB/timeout on the initial
    batch-fetch escaped uncaught and broke the Dict return contract.
  - CAP-5 (capture): reachy_user_memory_service.add_note read self._notes, awaited
    the embed, then appended without serialization; concurrent callers double-stored
    semantically-equal notes. Fixed with a DEDICATED _add_lock (not self._lock,
    which compact() already holds when calling add_note -> would deadlock).

The first three are source-pattern guards (deterministic, no app import chain).
The fourth exercises the CAP-5 lock behaviorally.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]


def _src(rel: str) -> str:
    return (_BACKEND / rel).read_text(encoding="utf-8")




def test_lrn_n5_outer_guard_is_broad():
    src = _src("app/services/content_learning_engine.py")
    # Isolate the process_content_outcomes function body.
    start = src.index("async def process_content_outcomes")
    rest = src[start + 1 :]
    nxt = rest.index("\n    async def ")
    body = rest[:nxt]
    # The narrow outer tuple guard must be gone; the outer guard must catch Exception.
    assert "except (ValueError, KeyError, TypeError, ImportError)" not in body, (
        "the narrow outer guard in process_content_outcomes must be widened"
    )
    assert "except Exception as e:" in body, (
        "process_content_outcomes outer guard must be `except Exception`"
    )
    assert 'logger.error("content_outcome_processing_failed"' in body




def test_cap5_concurrent_dedup_holds_under_lock():
    """Two concurrent add_note calls for semantically-equal text must yield ONE note.

    The embed stub yields the event loop (await sleep) so the race window is real;
    without _add_lock both callers would pass the dedup check and append.
    """
    try:
        import app.services.reachy_user_memory_service as mem_mod
    except Exception:  # pragma: no cover - heavy app import chain unavailable host-side
        pytest.skip("reachy_user_memory_service import chain unavailable in this env")

    svc = mem_mod.ReachyUserMemoryService()
    svc._notes = []

    async def _fake_embed(text: str):
        await asyncio.sleep(0)  # force the cooperative yield the real network call has
        return [1.0, 0.0, 0.0]  # identical vector -> cosine 1.0 -> dedup merge

    async def _run():
        orig = mem_mod._safe_embed
        mem_mod._safe_embed = _fake_embed
        try:
            await asyncio.gather(
                svc.add_note("topic", "user likes tea", confidence=0.9),
                svc.add_note("topic", "user prefers tea", confidence=0.9),
            )
        finally:
            mem_mod._safe_embed = orig
        return len(svc._notes)

    n = asyncio.run(_run())
    assert n == 1, f"concurrent semantically-equal add_note must dedup to 1 note, got {n}"
