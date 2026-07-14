"""Unit tests for DailyImprovementService._verify_auto_fix (Fix-143 F2).

Signal IDs embed the LINE NUMBER (enhancement_service.py:275 —
md5(f"{file}:{line}:{message[:50]}")). The verifier used to match only on the
stale stored signal_id, so a "fix" that shifted a still-present issue to a new
line changed its id, never matched, and fell through to "Signal resolved" —
inflating the self-improvement success metrics (FAILURE-AS-SUCCESS). The fix also
matches on the message TEXT, which is stable across line shifts.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.services.daily_improvement_service import DailyImprovementService


def _svc():
    # _verify_auto_fix uses no instance state; skip __init__ (which builds storage).
    return DailyImprovementService.__new__(DailyImprovementService)


def _patch_scan(signals):
    """Patch EnhancementService so the rescan returns `signals`."""
    class _FakeEnh:
        def __init__(self, *a, **k):
            pass

        def _extract_signals_from_file(self, *a, **k):
            return signals

    return patch("app.services.enhancement_service.EnhancementService", _FakeEnh)


@pytest.mark.asyncio
async def test_shifted_but_present_reports_not_resolved(tmp_path):
    """Same TODO text, different line/id (a shift) => still present => False."""
    src = tmp_path / "mod.py"
    src.write_text("x = 1\n# TODO: fix the thing\n", encoding="utf-8")
    item = {
        "file": str(src),
        "line": 10,
        "signal_id": "SIG_oldhash",
        "title": "TODO: fix the thing",
        "category": "todo",
    }
    shifted = [SimpleNamespace(id="SIG_newhash", message="TODO: fix the thing")]
    with _patch_scan(shifted):
        result = await _svc()._verify_auto_fix(item)
    assert result is False, "shifted-but-present issue was falsely reported resolved (F2)"


@pytest.mark.asyncio
async def test_unshifted_id_match_reports_not_resolved(tmp_path):
    src = tmp_path / "mod.py"
    src.write_text("# TODO: fix the thing\n", encoding="utf-8")
    item = {
        "file": str(src),
        "line": 1,
        "signal_id": "SIG_same",
        "title": "TODO: fix the thing",
        "category": "todo",
    }
    same = [SimpleNamespace(id="SIG_same", message="TODO: fix the thing")]
    with _patch_scan(same):
        result = await _svc()._verify_auto_fix(item)
    assert result is False


@pytest.mark.asyncio
async def test_genuinely_resolved_reports_true(tmp_path):
    """Issue actually gone (no matching id, no matching message) => True."""
    src = tmp_path / "mod.py"
    src.write_text("x = 1\n", encoding="utf-8")
    item = {
        "file": str(src),
        "line": 2,
        "signal_id": "SIG_old",
        "title": "TODO: fix the thing",
        "category": "todo",
    }
    other = [SimpleNamespace(id="SIG_unrelated", message="FIXME: something else entirely")]
    with _patch_scan(other):
        result = await _svc()._verify_auto_fix(item)
    assert result is True


@pytest.mark.asyncio
async def test_missing_file_reports_not_resolved():
    item = {"file": "/nonexistent/path/x.py", "line": 1, "signal_id": "s", "title": "t"}
    result = await _svc()._verify_auto_fix(item)
    assert result is False
