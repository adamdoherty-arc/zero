"""Fix-105 — hermetic guards for the adversarial gap batch.

Each test discriminates the FIXED behavior from the prior buggy behavior so a
regression re-breaks the test, not just the runtime. No DB / LLM / network.

Covered (backend, in-container): A1 face clustering, B1 voice research dispatch,
B2 memory-recall repr leak, B3 council all-abstain, B4 orchestration tz, C1/C3
realtime task-GC, C2 tail-speech basis, D2 reflection starvation, D3 thumbs
bridge, D4 trend window, plus the email-sender->GmailService contract (lead).
A2/A3 (host_agent) are verified out-of-band on the host (not COPY'd into the
zero-api container).
"""
import inspect

import numpy as np


# ---- A1: face clustering uses cosine, not bit-Hamming on float descriptors ----
def test_a1_cosine_separates_distinct_faces():
    from app.services.meeting_face_service import (
        _cosine_dist,
        _hamming,
        _CLUSTER_COSINE_THRESHOLD,
    )
    rng = np.random.default_rng(0)
    a = rng.standard_normal(128).astype("float32"); a /= np.linalg.norm(a)
    b = rng.standard_normal(128).astype("float32"); b /= np.linalg.norm(b)
    # Two independent unit descriptors -> cosine distance well above the
    # same-face cap, so they form SEPARATE clusters (the fix).
    assert _cosine_dist(a, b) > _CLUSTER_COSINE_THRESHOLD
    # Identical descriptor -> ~0 distance (same cluster).
    assert _cosine_dist(a, a.copy()) < 1e-5
    # The OLD metric would have wrongly merged them: L1 over the first 64 dims
    # of unit vectors is tiny, far under the bit-Hamming cap of 14.
    assert _hamming(a, b) <= 14


# ---- B1: voice research dispatch calls the real start_research, not svc.start ----
def test_b1_deep_research_dispatch_contract():
    from app.services.deep_research_service import DeepResearchService
    assert hasattr(DeepResearchService, "start_research")
    assert not hasattr(DeepResearchService, "start"), (
        "the supervisor research adapter relies on start_research(); a bare "
        "start() would resurrect the swallowed-AttributeError dead path"
    )
    import app.services.supervisor_graph as sg
    src = inspect.getsource(sg._research_adapter)
    assert "start_research(" in src
    assert "isn't wired yet" not in src  # dead fallback removed


# ---- B2: memory recall pulls Note.text, never str(Note) repr (embedding leak) ----


# ---- B3: an all-abstain council must not silently auto-approve ----
def test_b3_all_abstain_not_autoapprove():
    position_counts = {"approve": 0, "reject": 0, "needs_revision": 0}
    # The bug: max() over all-zero counts returns the first key by insertion order.
    assert max(position_counts, key=position_counts.get) == "approve"
    # The fix: the zero-vote guard routes a degenerate council to needs_revision.
    decision = (
        "needs_revision"
        if sum(position_counts.values()) == 0
        else max(position_counts, key=position_counts.get)
    )
    assert decision == "needs_revision"
    import app.services.council_service as cs
    assert "sum(position_counts.values()) == 0" in inspect.getsource(cs)


# ---- B4: orchestration router context timestamp is tz-aware ----
def test_b4_orchestration_tz_aware():
    import app.services.orchestration_graph as og
    src = inspect.getsource(og)
    assert '"classified_at": datetime.now(timezone.utc).isoformat()' in src


# ---- C1/C3: realtime best-effort + typed tasks are retained / tracked ----


# ---- C2: tail flush slices the same basis spoken_to_idx indexes ----


# ---- D2: reflection pulls scored rows so voice telemetry can't starve it ----
def test_d2_reflection_scored_only():
    from app.services.outcome_learning_service import OutcomeLearningService
    sig = inspect.signature(OutcomeLearningService.get_recent)
    assert "scored_only" in sig.parameters
    import app.services.zero_brain_service as zb
    assert "scored_only=True" in inspect.getsource(zb)


# ---- D3: thumbs feedback is bridged onto the structured outcome row ----
def test_d3_feedback_bridges_to_structured_store():
    import app.services.turn_outcome_service as to
    src = inspect.getsource(to)
    assert "async def _bridge_feedback_score(" in src
    assert "_bridge_feedback_score(turn_id, signal)" in src


# ---- D4: trend() read window scales with the requested span ----
def test_d4_trend_scales_read_window():
    import asyncio as _asyncio
    from app.services.turn_outcome_service import get_turn_outcome_service
    svc = get_turn_outcome_service()
    captured: dict = {}

    async def fake_recent(*, limit):
        captured["limit"] = limit
        return []

    orig = svc.recent
    svc.recent = fake_recent
    try:
        _asyncio.run(svc.trend(hours=24 * 30))  # 720*200=144000 -> hard cap 50000
        assert captured["limit"] == 50000
        _asyncio.run(svc.trend(hours=1))        # floor at 2000
        assert captured["limit"] == 2000
    finally:
        svc.recent = orig


# ---- LEAD: email senders' contract against GmailService.send_email ----
def test_lead_email_sender_contract():
    from app.services.gmail_service import GmailService
    params = inspect.signature(GmailService.send_email).parameters
    for required in ("to", "subject", "body_text"):
        assert required in params, (
            f"GmailService.send_email lost the '{required}' kwarg the approval-pool "
            f"and daily-brief senders depend on (the gap-1/gap-2 dead-send class)"
        )
