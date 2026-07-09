"""Fix-138 — respond/reason exception-guard bugfixes + coverage.

F5 (BUG): TTSService.synthesize_with_meta edge-tts voice-override path only
    caught ImportError around _synthesize_edge; a real synth failure (network,
    edge-tts service down, empty-audio RuntimeError) propagated unguarded,
    breaking the "voice loop never silently dies" invariant that the
    fish/kokoro/sesame branches already honor. Now falls through on any
    Exception.

F6 (BUG): the default ENGINE_EDGE synth path (no voice_override) had zero
    exception handling, unlike ENGINE_PIPER which falls back to edge-tts on
    failure. When edge-tts is itself the active default engine and synthesis
    fails, this used to raise a raw, uncontextualized traceback. Now wrapped
    and re-raised as a clear RuntimeError.

F7 (BUG): council_service.conduct_vote only caught StructuredOutputError per
    role/round; a raw provider/network/timeout exception escaped the loop and
    aborted the whole vote, losing already-computed votes (the same class RSN-8
    fixed in experiment_service.design_experiment). Now degrades to abstain
    (round 1) / keeps the round-1 vote (round 2), like the StructuredOutputError
    path already does.

F8 (test-gap): tts_service pure voice-classifier helpers had zero coverage.

F9 (test-gap): carousel_v2 reflexion_service (make_reflection/append_reflection)
    had zero coverage.

F10 (test-gap): vault_retrieval_service._embed_query dimension-mismatch +
    failure degradation had zero coverage.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest


# ---------------------------------------------------------------------------
# F5/F8 — tts_service
# ---------------------------------------------------------------------------

def test_f8_is_edge_tts_voice():
    from app.services.tts_service import _is_edge_tts_voice

    assert _is_edge_tts_voice("en-US-AriaNeural") is True
    assert _is_edge_tts_voice("kokoro:af_bella") is False
    assert _is_edge_tts_voice("") is False
    assert _is_edge_tts_voice(None) is False


def test_f8_is_kokoro_voice():
    from app.services.tts_service import _is_kokoro_voice

    assert _is_kokoro_voice("kokoro:af_bella") is True
    assert _is_kokoro_voice("en-US-AriaNeural") is False


def test_f8_is_piper_voice():
    from app.services.tts_service import _is_piper_voice

    assert _is_piper_voice("en_US-lessac-medium") is True
    assert _is_piper_voice("some-voice.onnx") is True
    assert _is_piper_voice("kokoro:af_bella") is False


async def test_f5_edge_tts_voice_override_falls_back_on_synth_failure(monkeypatch):
    """A real synth failure (not ImportError) during a voice_override edge-tts
    call must fall through to the default engine rather than raising."""
    from app.services.tts_service import TTSService, ENGINE_PIPER

    svc = TTSService()
    svc._initialized = True
    svc._engine = ENGINE_PIPER

    async def _fail_edge(text, voice=None):
        raise RuntimeError("edge-tts returned empty audio")

    async def _ok_piper(text):
        return b"piper-audio"

    monkeypatch.setattr(svc, "_synthesize_edge", _fail_edge)
    monkeypatch.setattr(svc, "_synthesize_piper", _ok_piper)

    audio, meta = await svc.synthesize_with_meta(
        "hello", voice_override="en-US-AriaNeural"
    )

    # Fell through past the failed edge-tts override to the default piper path.
    assert audio == b"piper-audio"
    assert meta["engine"] == ENGINE_PIPER


async def test_f6_default_edge_engine_synth_failure_raises_clear_runtime_error(monkeypatch):
    """When ENGINE_EDGE is the active default engine and synthesis fails, the
    caller must get a clear RuntimeError, not a raw unrelated traceback."""
    from app.services.tts_service import TTSService, ENGINE_EDGE

    svc = TTSService()
    svc._initialized = True
    svc._engine = ENGINE_EDGE

    async def _fail_edge(text):
        raise ConnectionError("edge-tts unreachable")

    monkeypatch.setattr(svc, "_synthesize_edge", _fail_edge)

    with pytest.raises(RuntimeError, match="edge-tts synthesis failed"):
        await svc.synthesize_with_meta("hello")


# ---------------------------------------------------------------------------
# F7 — council_service.conduct_vote provider-error degradation
# ---------------------------------------------------------------------------

class _FakeRow:
    def __init__(self, decision_id: str):
        self.id = decision_id
        self.topic = "Ship feature X?"
        self.context = {}
        self.proposer_role = "ceo"
        self.rounds = None
        self.votes = None
        self.decision = None
        self.confidence_score = None
        self.created_at = datetime.now(timezone.utc)
        self.decided_at = None


class _FakeSession:
    """Single persistent row so save-then-reread (conduct_vote's tail call to
    get_decision) reflects the tally, mirroring a real DB round-trip."""

    def __init__(self, row):
        self._row = row

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, model, decision_id):
        return self._row

    async def commit(self):
        pass


async def test_f7_conduct_vote_degrades_to_abstain_on_provider_error(monkeypatch):
    from app.services import council_service as cs

    svc = cs.CouncilService()
    row = _FakeRow("dec-1")
    monkeypatch.setattr(cs, "get_session", lambda: _FakeSession(row))

    class _FailingLLM:
        async def structured_chat(self, **kwargs):
            raise ConnectionError("bifrost timeout")

    svc._llm = _FailingLLM()

    result = await svc.conduct_vote("dec-1")

    # Every role in both rounds degraded to abstain instead of raising, and
    # the decision still completes with a valid tally.
    round1_votes = result.rounds[0]["votes"]
    round2_votes = result.rounds[1]["votes"]
    assert all(v["position"] == "abstain" for v in round1_votes.values())
    assert all(v["position"] == "abstain" for v in round2_votes.values())


async def test_f7_conduct_vote_round2_keeps_round1_vote_on_provider_error(monkeypatch):
    """Round 2 provider error must keep the (already-successful) round-1 vote
    rather than raising, mirroring the StructuredOutputError degrade path."""
    from app.services import council_service as cs

    svc = cs.CouncilService()
    row = _FakeRow("dec-2")
    monkeypatch.setattr(cs, "get_session", lambda: _FakeSession(row))

    calls = {"n": 0}

    class _FlakyRound2LLM:
        async def structured_chat(self, **kwargs):
            calls["n"] += 1
            if calls["n"] <= len(cs.COUNCIL_ROLES):
                # Round 1: succeed for every role.
                return {"position": "approve", "reasoning": "looks good", "confidence": 80}
            # Round 2: fail for every role.
            raise TimeoutError("provider timeout")

    svc._llm = _FlakyRound2LLM()

    result = await svc.conduct_vote("dec-2")

    round1_votes = result.rounds[0]["votes"]
    round2_votes = result.rounds[1]["votes"]
    assert all(v["position"] == "approve" for v in round1_votes.values())
    # Round 2 kept round 1's vote rather than aborting.
    assert round2_votes == round1_votes


# ---------------------------------------------------------------------------
# F9 — carousel_v2 reflexion_service
# ---------------------------------------------------------------------------

def _rubric(scores: dict):
    from app.models.carousel import CarouselRubric, JudgeAxisScore, JudgeName, RubricAxis

    per_axis = [
        JudgeAxisScore(
            judge=JudgeName.QWEN3_32B_LOCAL,
            axis=axis,
            score=score,
            rationale=f"{axis.value} needs work",
        )
        for axis, score in scores.items()
    ]
    return CarouselRubric(per_axis_per_judge=per_axis, aggregated=scores)


def test_f9_make_reflection_empty_when_no_scores():
    from app.services.carousel_v2.reflexion_service import make_reflection
    from app.models.carousel import CarouselRubric

    assert make_reflection(CarouselRubric()) == ""


def test_f9_make_reflection_picks_weakest_axes():
    from app.services.carousel_v2.reflexion_service import make_reflection
    from app.models.carousel import RubricAxis

    rubric = _rubric({
        RubricAxis.HOOK_STRENGTH: 3.0,
        RubricAxis.FACT_ACCURACY: 9.0,
        RubricAxis.NARRATIVE_ARC: 5.0,
    })
    reflection = make_reflection(rubric, threshold=6.5)

    assert "hook_strength" in reflection
    assert "narrative_arc" in reflection
    # fact_accuracy scored above threshold, must not appear.
    assert "fact_accuracy" not in reflection


def test_f9_make_reflection_no_weak_axes_returns_empty():
    from app.services.carousel_v2.reflexion_service import make_reflection
    from app.models.carousel import RubricAxis

    rubric = _rubric({RubricAxis.HOOK_STRENGTH: 9.0, RubricAxis.FACT_ACCURACY: 8.5})
    assert make_reflection(rubric, threshold=6.5) == ""


def test_f9_append_reflection_caps_history_at_max():
    from app.services.carousel_v2.reflexion_service import append_reflection, MAX_REFLECTIONS

    history = [f"r{i}" for i in range(MAX_REFLECTIONS)]
    new = append_reflection(history, "latest")

    assert len(new) == MAX_REFLECTIONS
    assert new[-1] == "latest"
    assert new[0] == "r1"  # oldest ("r0") dropped


def test_f9_append_reflection_ignores_empty():
    from app.services.carousel_v2.reflexion_service import append_reflection

    history = ["r0"]
    assert append_reflection(history, "") == history


def test_f9_render_for_designer_empty_history():
    from app.services.carousel_v2.reflexion_service import render_for_designer

    assert render_for_designer([]) == ""


def test_f9_render_for_designer_formats_bullets():
    from app.services.carousel_v2.reflexion_service import render_for_designer

    out = render_for_designer(["fix the hook", "tighten the arc"])
    assert "- fix the hook" in out
    assert "- tighten the arc" in out


# ---------------------------------------------------------------------------
# F10 — vault_retrieval_service._embed_query
# ---------------------------------------------------------------------------

async def test_f10_embed_query_returns_none_on_dimension_mismatch(monkeypatch):
    from app.services import vault_retrieval_service as vrs

    class _FakeClient:
        async def embed(self, text, max_retries=1):
            return [0.1] * 1024  # wrong dimension

    class _FakeSettings:
        embedding_dimension = 768

    monkeypatch.setattr(vrs, "get_llm_client", lambda: _FakeClient())
    monkeypatch.setattr(vrs, "get_settings", lambda: _FakeSettings())

    result = await vrs._embed_query("what did I do Monday")
    assert result is None


async def test_f10_embed_query_degrades_on_embedder_exception(monkeypatch):
    from app.services import vault_retrieval_service as vrs

    class _FailingClient:
        async def embed(self, text, max_retries=1):
            raise ConnectionError("embedder down")

    monkeypatch.setattr(vrs, "get_llm_client", lambda: _FailingClient())

    result = await vrs._embed_query("what did I do Monday")
    assert result is None


async def test_f10_embed_query_returns_vector_on_success(monkeypatch):
    from app.services import vault_retrieval_service as vrs

    class _FakeClient:
        async def embed(self, text, max_retries=1):
            return [0.1] * 768

    class _FakeSettings:
        embedding_dimension = 768

    monkeypatch.setattr(vrs, "get_llm_client", lambda: _FakeClient())
    monkeypatch.setattr(vrs, "get_settings", lambda: _FakeSettings())

    result = await vrs._embed_query("what did I do Monday")
    assert result == [0.1] * 768
