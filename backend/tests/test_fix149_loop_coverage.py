"""Fix-149 — content-loop coverage hunt (loop_runner + loop_judge + content_swarm).

Never-swept files (0 prior tests). Findings verified against source before filing:

A2 (HIGH): loop runners recorded an empty LLM completion (200 OK with choices:[]
  or blank content -> _call_litellm returns ("",0)) as status="success",
  inflating success-rate metrics + the variant successes counter, and the run
  was silently unjudgeable (output stored NULL). Blank output is now a failure.
A3: _pick_variant fell back to variants[0] when every non-retired variant had
  zero traffic weight (all deactivated but not retired), running a deliberately
  disabled variant and corrupting its stats. Now returns None -> caller reschedules.
A6 (MED): the judge wrote judge_score to Zero's DB but never pushed it to
  Legion's mirror (docstring claimed it did), so the cross-project loop dashboard
  showed null quality for every run. score_one now backfills via the new
  POST /api/loops/runs/{id}/judge (score-only, no clobber).
B3 (HIGH): content_swarm._collect_vote crashed (float(None) TypeError, outside
  the LLM try/except) when a role returned predicted_engagement:null, aborting
  the whole vote round instead of degrading to the neutral fallback.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# A2 — empty completion is a failure, real output is a success
# ---------------------------------------------------------------------------

def _make_runner(litellm_return):
    from app.services.loop_runner_service import LoopRunnerService
    svc = LoopRunnerService.__new__(LoopRunnerService)
    svc._registry = AsyncMock()
    svc._vault = MagicMock()
    svc._vault.available.return_value = False
    svc._sink = AsyncMock()
    svc._runner_model = "test-model"
    svc._read_skill_markdown = MagicMock(return_value="SPEC")
    svc._call_litellm = AsyncMock(return_value=litellm_return)
    svc._push_to_legion = AsyncMock(return_value=None)
    return svc


_LOOP = {
    "id": 1,
    "name": "t",
    "owner_project": "zero",
    "runner_kind": "claude_skill",
    "run_id": 99,
    "runner_target": "dummy",
}


async def test_claude_skill_empty_completion_is_failure():
    svc = _make_runner(("", 0))
    await svc._run_claude_skill(dict(_LOOP))
    svc._registry.mark_run_completed.assert_awaited()
    kwargs = svc._registry.mark_run_completed.await_args.kwargs
    assert kwargs["status"] == "failure"
    assert "empty completion" in (kwargs.get("error") or "")


async def test_claude_skill_whitespace_only_is_failure():
    svc = _make_runner(("   \n  ", 4))
    await svc._run_claude_skill(dict(_LOOP))
    assert svc._registry.mark_run_completed.await_args.kwargs["status"] == "failure"


async def test_claude_skill_real_output_is_success():
    svc = _make_runner(("A concrete finding: foo.py:12 leaks a handle.", 42))
    await svc._run_claude_skill(dict(_LOOP))
    assert svc._registry.mark_run_completed.await_args.kwargs["status"] == "success"


# ---------------------------------------------------------------------------
# A3 — _pick_variant returns None instead of a zero-weight variant
# ---------------------------------------------------------------------------

class _FakeScalars:
    def __init__(self, items):
        self._items = items

    def all(self):
        return self._items


class _FakeExec:
    def __init__(self, items):
        self._items = items

    def scalars(self):
        return _FakeScalars(self._items)


class _FakeSession:
    def __init__(self, items):
        self._items = items

    async def execute(self, stmt):
        return _FakeExec(self._items)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _patch_session(items):
    return patch("app.infrastructure.database.get_session", lambda: _FakeSession(items))


def _variant(**kw):
    base = dict(id=1, variant_label="v", payload="p", is_active=False,
                is_canary=False, canary_traffic_pct=0.0, retired_at=None)
    base.update(kw)
    return SimpleNamespace(**base)


async def test_pick_variant_none_when_all_weights_zero():
    from app.services.loop_runner_service import LoopRunnerService
    svc = LoopRunnerService.__new__(LoopRunnerService)
    with _patch_session([_variant(id=1), _variant(id=2)]):  # both inactive, not retired
        assert await svc._pick_variant(1) is None


async def test_pick_variant_none_when_no_variants():
    from app.services.loop_runner_service import LoopRunnerService
    svc = LoopRunnerService.__new__(LoopRunnerService)
    with _patch_session([]):
        assert await svc._pick_variant(1) is None


async def test_pick_variant_picks_active_when_weighted():
    from app.services.loop_runner_service import LoopRunnerService
    svc = LoopRunnerService.__new__(LoopRunnerService)
    with _patch_session([_variant(id=7, is_active=True)]):
        chosen = await svc._pick_variant(1)
        assert chosen is not None and chosen["id"] == 7


# ---------------------------------------------------------------------------
# B3 — _safe_float + _collect_vote survives a null/garbage engagement field
# ---------------------------------------------------------------------------

def test_safe_float_coerces_and_falls_back():
    from app.services.content_swarm_service import _safe_float
    assert _safe_float(None, 50.0) == 50.0
    assert _safe_float("high", 50.0) == 50.0        # non-numeric string
    assert _safe_float("42", 0.0) == 42.0
    assert _safe_float(42, 0.0) == 42.0
    assert _safe_float(0.5, 9.0) == 0.5


async def test_collect_vote_survives_null_predicted_engagement():
    from app.services.content_swarm_service import ContentSwarmService
    svc = ContentSwarmService.__new__(ContentSwarmService)
    svc._llm = MagicMock()
    # key PRESENT with null value -> dict.get default does NOT apply -> float(None)
    svc._llm.chat = AsyncMock(
        return_value='{"predicted_engagement": null, "confidence": 0.5, "vote": "hold", "reasoning": "unsure"}'
    )
    role = SimpleNamespace(name="critic", system="sys", task_type="swarm_vote")
    result = await svc._collect_vote(role, "prompt")  # must not raise
    assert result["predicted_engagement"] == 50.0
    assert result["vote"] == "hold"


async def test_collect_vote_non_numeric_engagement_falls_back():
    from app.services.content_swarm_service import ContentSwarmService
    svc = ContentSwarmService.__new__(ContentSwarmService)
    svc._llm = MagicMock()
    svc._llm.chat = AsyncMock(
        return_value='{"predicted_engagement": "very high", "confidence": "n/a", "vote": "boost"}'
    )
    role = SimpleNamespace(name="hype", system="sys", task_type="swarm_vote")
    result = await svc._collect_vote(role, "prompt")
    assert result["predicted_engagement"] == 50.0
    assert result["confidence"] == 0.5
    assert result["vote"] == "boost"


# ---------------------------------------------------------------------------
# A6 — judge backfills the score to Legion via the score-only endpoint
# ---------------------------------------------------------------------------

class _Resp:
    def __init__(self, status_code=200):
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400 and self.status_code != 404:
            raise RuntimeError(f"http {self.status_code}")


class _Client:
    def __init__(self, captured, status_code=200):
        self._captured = captured
        self._status = status_code

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None, headers=None):
        self._captured["url"] = url
        self._captured["json"] = json
        return _Resp(self._status)


def _make_judge():
    from app.services.loop_judge_service import LoopJudgeService
    svc = LoopJudgeService.__new__(LoopJudgeService)
    svc._legion_base = "http://legion:8005"
    return svc


async def test_push_judge_posts_score_only_to_right_url():
    svc = _make_judge()
    captured: dict = {}
    with patch("app.services.loop_judge_service.httpx.AsyncClient",
               lambda *a, **k: _Client(captured)):
        await svc._push_judge_to_legion(555, 87.0)
    assert captured["url"] == "http://legion:8005/api/loops/runs/555/judge"
    assert captured["json"] == {"judge_score": 87.0}  # ONLY judge_score, no clobber


async def test_push_judge_swallows_404_and_errors():
    svc = _make_judge()
    captured: dict = {}
    # 404 (no mirror row) must not raise
    with patch("app.services.loop_judge_service.httpx.AsyncClient",
               lambda *a, **k: _Client(captured, status_code=404)):
        await svc._push_judge_to_legion(1, 5.0)

    # A transport error must be swallowed too (best-effort, never blocks scoring)
    def _boom(*a, **k):
        raise RuntimeError("connection refused")

    with patch("app.services.loop_judge_service.httpx.AsyncClient", _boom):
        await svc._push_judge_to_legion(1, 5.0)  # no raise
