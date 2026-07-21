"""Fix-147 — learn-domain coverage-hunt regression tests.

F1 (HIGH): daily_brief's _reflection_section has always called
  ReflectionService.latest_summary() behind a `# type: ignore` + `except
  AttributeError` shim — the method never existed, so the "Yesterday" brief
  tile/email section showed "No reflection summary yet" on every brief, forever.
  latest_summary() now surfaces the newest persisted reflection episodic memories.

F2 (XS): daily_improvement_service._execute_auto_fix wrote every backup to a
  deterministic `<file>.bak`. _select_diverse_improvements allows up to 2 signals
  from the same file per cycle, so the 2nd fix overwrote the 1st's backup with the
  already-patched content, corrupting the rollback trail recorded in fixes.json.
  Backups are now tagged with the signal id.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# F1 — ReflectionService.latest_summary
# ---------------------------------------------------------------------------

def _mem(content, source_type="reflection", age_days=0):
    return SimpleNamespace(
        content=content,
        source_type=source_type,
        created_at=datetime.now(timezone.utc) - timedelta(days=age_days),
    )


class _FakeEpisodic:
    def __init__(self, mems):
        self._mems = mems

    async def get_recent(self, namespace=None, limit=20, source_type=None):
        # Honor the source_type SQL filter the production get_recent now applies
        # (Fix-150 R2): a low-frequency reflection source stays findable.
        mems = self._mems
        if source_type is not None:
            mems = [m for m in mems if getattr(m, "source_type", None) == source_type]
        return mems[:limit]


def _patch_episodic(mems):
    fake = _FakeEpisodic(mems)
    return patch(
        "app.services.episodic_memory_service.get_episodic_memory_service",
        lambda: fake,
    )


async def test_latest_summary_none_when_no_reflection_memories():
    from app.services.reflection_service import ReflectionService

    # Only non-reflection memories present -> None (brief shows placeholder).
    with _patch_episodic([_mem("a conversation", source_type="conversation")]):
        assert await ReflectionService().latest_summary() is None


async def test_latest_summary_returns_wins_from_reflection_memories():
    from app.services.reflection_service import ReflectionService

    mems = [
        _mem("Ship smaller diffs to the critic", age_days=1),
        _mem("Pre-fetch codegraph for subagents", age_days=2),
        _mem("some email", source_type="email", age_days=0),
    ]
    with _patch_episodic(mems):
        out = await ReflectionService().latest_summary()
    assert out is not None
    assert out["wins"] == [
        "Ship smaller diffs to the critic",
        "Pre-fetch codegraph for subagents",
    ]
    assert "2 reflection insights" in out["summary"]


async def test_latest_summary_filters_stale_beyond_window():
    from app.services.reflection_service import ReflectionService

    mems = [_mem("old insight", age_days=30)]  # older than within_days=8
    with _patch_episodic(mems):
        assert await ReflectionService().latest_summary(within_days=8) is None


async def test_latest_summary_degrades_to_none_on_error():
    from app.services.reflection_service import ReflectionService

    class _Boom:
        async def get_recent(self, namespace=None, limit=20, source_type=None):
            raise RuntimeError("db down")

    with patch(
        "app.services.episodic_memory_service.get_episodic_memory_service",
        lambda: _Boom(),
    ):
        # must NOT raise — the brief section degrades to the placeholder.
        assert await ReflectionService().latest_summary() is None


async def test_latest_summary_caps_at_five_wins():
    from app.services.reflection_service import ReflectionService

    mems = [_mem(f"insight {i}", age_days=0) for i in range(9)]
    with _patch_episodic(mems):
        out = await ReflectionService().latest_summary()
    assert out is not None and len(out["wins"]) == 5


# ---------------------------------------------------------------------------
# F2 — same-file same-cycle auto-fix backups do not collide
# ---------------------------------------------------------------------------

async def test_autofix_backups_unique_per_signal(tmp_path):
    from app.services.daily_improvement_service import DailyImprovementService

    svc = DailyImprovementService()

    src = tmp_path / "sample_mod.py"
    original = "# l1\n# l2\n# l3\n# l4\n# l5\n# l6\n"
    src.write_text(original, encoding="utf-8")

    async def fake_ollama(prompt, model=None):
        return "# fixed"

    svc._call_ollama = fake_ollama
    svc._extract_code_from_response = lambda r: ["# fixed"]

    recorded_backups = []

    async def fake_record(item, original_c, fixed_c, backup_path):
        recorded_backups.append(backup_path)

    svc._record_fix = fake_record

    item1 = {"file": str(src), "line": 1, "title": "x", "category": "todo", "signal_id": "sigAAA"}
    r1 = await svc._execute_auto_fix(item1)
    assert r1.get("applied") is True, r1

    item2 = {"file": str(src), "line": 1, "title": "y", "category": "todo", "signal_id": "sigBBB"}
    r2 = await svc._execute_auto_fix(item2)
    assert r2.get("applied") is True, r2

    # Two DISTINCT backup files, each tagged with its signal id.
    assert r1["backup"] != r2["backup"], "same-cycle backups collided (F2 regression)"
    assert "sigAAA" in r1["backup"] and "sigBBB" in r2["backup"]
    # Fix #1's backup preserves the TRUE pre-fix original (not overwritten by fix #2).
    from pathlib import Path
    assert Path(r1["backup"]).read_text(encoding="utf-8") == original
