"""Smoke tests for the Phase 1-8 additions.

These exercise the new services and routers without requiring a running
container. Each test sandboxes the workspace dir so the JSON-backed
stores don't pollute the repo.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _isolate_workspace(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "workspace").mkdir(exist_ok=True)
    yield


async def test_tts_engine_constants():
    from app.services.tts_service import (
        ENGINE_KOKORO,
        ENGINE_SESAME,
        ENGINE_PIPER,
        _is_kokoro_voice,
        _is_sesame_voice,
    )
    assert ENGINE_KOKORO == "kokoro"
    assert ENGINE_SESAME == "sesame"
    assert _is_kokoro_voice("kokoro:af_bella")
    assert _is_sesame_voice("sesame:default")
    assert not _is_kokoro_voice("en-US-AriaNeural")


async def test_realtime_engine_flag():
    from app.services.reachy_realtime.common import (
        ENGINE_LEGACY,
        ENGINE_PIPECAT,
        REALTIME_ENGINES,
        normalize_engine,
    )
    assert "legacy" in REALTIME_ENGINES and "pipecat" in REALTIME_ENGINES
    assert normalize_engine(None) == ENGINE_LEGACY
    assert normalize_engine("pipecat") == ENGINE_PIPECAT
    assert normalize_engine("garbage") == ENGINE_LEGACY


async def test_realtime_config_engine_field_persists():
    from app.services.reachy_realtime import config_store

    config_store.update_config({"engine": "pipecat"})
    cfg = config_store.load_config_masked()
    assert cfg.get("engine") == "pipecat"


async def test_memory_facade_recall_and_remember_no_backends():
    from app.services.memory_facade import get_memory_facade, MemoryNote

    facade = get_memory_facade()
    notes = await facade.recall("hello world", k=3)
    assert isinstance(notes, list)
    res = await facade.remember("hi", "hello there")
    assert "written_to" in res
    formatted = facade.format_for_system_prompt([
        MemoryNote(text="Adam likes coffee", source="test", score=0.9),
    ])
    assert "Adam likes coffee" in formatted


async def test_supervisor_classifies_intents():
    from app.services.supervisor_graph import _classify, get_supervisor

    assert _classify("what's on my calendar today?") == "calendar"
    assert _classify("read my email") == "email"
    assert _classify("how is ada ai doing") == "company"
    assert _classify("what is my YTD revenue") == "bookkeeper"
    assert _classify("research the best CPAs in Duval county") == "research"
    assert _classify("hi how are you") == "direct"
    sup = get_supervisor()
    res = await sup.handle("hi reachy")
    assert res.direct and res.intent == "direct"


async def test_email_draft_pool_lifecycle():
    from app.services.email_draft_pool_service import get_email_draft_pool

    # Reset the singleton so we get a fresh instance with the temp workspace
    pool_mod = __import__("app.services.email_draft_pool_service", fromlist=["get_email_draft_pool"])
    pool_mod.get_email_draft_pool.cache_clear()  # type: ignore[attr-defined]
    pool = get_email_draft_pool()

    d = await pool.add_draft(
        account_id="work",
        to="cpa@example.com",
        subject="Hi",
        body="Body",
    )
    assert d.status == "pending"
    drafts = await pool.list_drafts(account_id="work")
    assert any(x.id == d.id for x in drafts)
    rj = await pool.reject(d.id, reason="test")
    assert rj is not None and rj.status == "rejected"


async def test_bookkeeper_csv_ingest_and_voice():
    from app.services.bookkeeper_service import get_bookkeeper_service
    bk_mod = __import__(
        "app.services.bookkeeper_service", fromlist=["get_bookkeeper_service"],
    )
    bk_mod.get_bookkeeper_service.cache_clear()  # type: ignore[attr-defined]
    bk = get_bookkeeper_service()
    drafts = await bk.ingest_bank_csv(
        source="bank_csv",
        csv_text="date,description,amount\n2026-01-15,Stripe payout,1500.00\n2026-01-16,AWS,-120.00\n",
    )
    assert len(drafts) == 2
    accepted = await bk.accept_draft(drafts[0].id)
    assert accepted is not None and accepted.status == "accepted"
    snap = await bk.snapshot()
    assert snap.entity == "ADA AI LLC"
    answer = await bk.answer_voice_question("what is my YTD revenue")
    assert "revenue" in answer.lower()


async def test_daily_brief_compose_and_cache():
    from app.services.daily_brief_service import get_daily_brief_service
    mod = __import__("app.services.daily_brief_service", fromlist=["get_daily_brief_service"])
    mod.get_daily_brief_service.cache_clear()  # type: ignore[attr-defined]
    svc = get_daily_brief_service()
    payload = await svc.compose_today()
    assert payload.markdown.startswith("# Daily brief")
    assert payload.spoken_summary
    cached = await svc.latest()
    assert cached is not None and cached.date == payload.date


async def test_digest_email_no_recipient_is_safe():
    from app.services.digest_email_service import get_digest_email_service
    mod = __import__("app.services.digest_email_service", fromlist=["get_digest_email_service"])
    mod.get_digest_email_service.cache_clear()  # type: ignore[attr-defined]
    svc = get_digest_email_service()
    res = await svc.send(markdown="# hi")
    assert res["sent"] is False


async def test_turn_outcome_record_and_feedback():
    from app.services.turn_outcome_service import get_turn_outcome_service
    mod = __import__("app.services.turn_outcome_service", fromlist=["get_turn_outcome_service"])
    mod.get_turn_outcome_service.cache_clear()  # type: ignore[attr-defined]
    svc = get_turn_outcome_service()
    out = await svc.record_turn(
        persona_id="default",
        intent="direct",
        user_text="hi",
        assistant_text="hello adam",
        ttfb_ms=420,
        total_ms=1300,
    )
    assert out.id.startswith("turn-")
    ok = await svc.feedback(out.id, "thumbs_up")
    assert ok
    trend = await svc.trend(hours=24)
    assert trend["n"] >= 1 and trend["thumbs_up"] >= 1


async def test_wake_presence_policy_round_trip():
    from app.services.wake_presence_service import get_wake_presence_service
    mod = __import__("app.services.wake_presence_service", fromlist=["get_wake_presence_service"])
    mod.get_wake_presence_service.cache_clear()  # type: ignore[attr-defined]
    svc = get_wake_presence_service()
    p = await svc.get_policy()
    assert p.wake_engine in ("openwakeword", "custom", "off")
    p2 = await svc.update_policy({"presence_enabled": True})
    assert p2.presence_enabled
    snap = await svc.snapshot_policy()
    assert "wake_required" in snap


async def test_realtime_tools_registry_includes_supervisor():
    from app.services.reachy_realtime.tools import _HANDLERS, _SPECS
    for name in (
        "delegate_research",
        "draft_email",
        "bookkeeping_query",
        "supervisor_dispatch",
    ):
        assert name in _HANDLERS, f"missing handler: {name}"
        assert name in _SPECS, f"missing spec: {name}"
