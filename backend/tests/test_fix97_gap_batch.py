"""Fix-103 (supervise run 2026-06-02) adversarial gap batch — regression locks.

Six gaps fixed this supervise run across Zero capability loops; each test pins
one fix so it cannot silently regress. Provenance: run 8e83557d, run_state.json.

  #1 HIGH  act-with-approval  approval_service.py        API restored (broken stub reverted)
  #2 HIGH  reflect            proactive_service.py        real DND gate (was swallowed AttributeError)
  #3 MED   capture            reachy_realtime/tools.py     follow-up task held by strong ref (no GC)
  #4 MED   reason             legion_task_handler.py       dead+broken module deleted
  #5 LOW   respond            gemini/openai_handler.py     connect-timeout closes the half-open cm
  #6 LOW   reflect            reflection_service.py        dict-wrapped LLM result not dropped
"""
import importlib
import types
from datetime import datetime, timezone
from pathlib import Path

import pytest

SERVICES = Path(__file__).resolve().parents[1] / "app" / "services"


# --- Gap #1 (HIGH, act-with-approval): approvals API restored ----------------
def test_approval_service_api_intact():
    from app.services.approval_service import ApprovalService, get_approval_service

    svc = get_approval_service()
    assert isinstance(svc, ApprovalService)
    for m in (
        "create_approval_request",
        "get_request",
        "list_pending",
        "list_all",
        "approve",
        "reject",
        "get_stats",
    ):
        assert callable(getattr(svc, m, None)), f"ApprovalService missing {m}()"


# --- Gap #2 (HIGH, reflect): DND gate actually evaluates ----------------------
def test_attention_in_dnd_window(monkeypatch):
    import app.services.attention_middleware as am

    mw = am.AttentionMiddleware()
    mw._settings = types.SimpleNamespace(dnd_start_hour=22, dnd_end_hour=7)
    # 23:00 is inside the 22->7 overnight window -> DND on
    monkeypatch.setattr(am, "_now_local", lambda: datetime(2026, 6, 2, 23, 0, tzinfo=timezone.utc))
    assert mw.in_dnd() is True
    # 12:00 is outside -> DND off
    monkeypatch.setattr(am, "_now_local", lambda: datetime(2026, 6, 2, 12, 0, tzinfo=timezone.utc))
    assert mw.in_dnd() is False


def test_proactive_uses_real_dnd_gate():
    src = (SERVICES / "proactive_service.py").read_text(encoding="utf-8")
    # the phantom method that always raised (and was swallowed) must be gone
    assert "get_attention_middleware().should_interrupt(" not in src
    assert ".in_dnd()" in src


# --- Gap #3 (MED, capture): meeting follow-up task survives GC ----------------
def test_followup_task_strongref():
    import app.services.reachy_realtime.tools as tools

    assert isinstance(tools._BG_FOLLOWUP_TASKS, set)
    src = (SERVICES / "reachy_realtime" / "tools.py").read_text(encoding="utf-8")
    assert "_BG_FOLLOWUP_TASKS.add(" in src
    assert "add_done_callback(_BG_FOLLOWUP_TASKS.discard)" in src


# --- Gap #4 (MED, reason): dead-broken module removed -------------------------
def test_legion_task_handler_removed():
    assert not (SERVICES / "legion_task_handler.py").exists()
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("app.services.legion_task_handler")


# --- Gap #5 (LOW, respond): connect-timeout cleans up the half-open cm --------
def test_realtime_connect_timeout_cleanup():
    for name in ("gemini_handler.py", "openai_handler.py"):
        src = (SERVICES / "reachy_realtime" / name).read_text(encoding="utf-8")
        # one __aexit__ in the success finally + one new in the timeout branch
        assert src.count("__aexit__(None, None, None)") >= 2, f"{name} missing timeout cleanup"


# --- Gap #6 (LOW, reflect): dict-wrapped LLM result not silently dropped ------
async def test_reflection_unwraps_dict(monkeypatch):
    import app.services.reflection_service as rs

    class _FakeLLM:
        async def structured_chat(self, **kw):
            return {"learnings": [{"learning": "ship smaller", "confidence": 0.9}]}

    monkeypatch.setattr(rs, "get_unified_llm_client", lambda: _FakeLLM())
    svc = rs.get_reflection_service()
    out = await svc.reflect_on_decisions([{"action_type": "x"}], "ops")
    assert out == ["ship smaller"]
