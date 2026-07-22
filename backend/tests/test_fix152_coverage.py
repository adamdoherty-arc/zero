"""Fix-152 (supervise ee392aa1) — coverage sweep over the missed=2 domains
(act-with-approval / retrieve / respond). All findings source-verified before
filing; each test asserts the specific corrected value (a "did it run" assertion
cannot catch a fix that never executes).
"""

import pytest


# ---------------------------------------------------------------------------
# ACT-1 — ApprovalService.list_all()/get_request() echoed raw status, so a
# pending-but-expired row (before the hourly sweep) rendered as actionable.
# ---------------------------------------------------------------------------

class TestApprovalEffectiveStatus:
    def _row(self, status, expires_at):
        class _R:
            pass
        r = _R()
        r.status = status
        r.expires_at = expires_at
        return r

    def test_pending_past_expiry_reads_expired(self):
        from datetime import datetime, timezone, timedelta
        from app.services.approval_service import ApprovalService
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        assert ApprovalService.effective_status(self._row("pending", past)) == "expired"

    def test_pending_future_expiry_stays_pending(self):
        from datetime import datetime, timezone, timedelta
        from app.services.approval_service import ApprovalService
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        assert ApprovalService.effective_status(self._row("pending", future)) == "pending"

    def test_pending_no_expiry_stays_pending(self):
        from app.services.approval_service import ApprovalService
        assert ApprovalService.effective_status(self._row("pending", None)) == "pending"

    def test_decided_status_untouched(self):
        from datetime import datetime, timezone, timedelta
        from app.services.approval_service import ApprovalService
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        assert ApprovalService.effective_status(self._row("approved", past)) == "approved"

    def test_naive_expiry_is_treated_as_utc(self):
        from datetime import datetime, timedelta
        from app.services.approval_service import ApprovalService
        naive_past = datetime.utcnow() - timedelta(hours=2)
        assert ApprovalService.effective_status(self._row("pending", naive_past)) == "expired"


# ---------------------------------------------------------------------------
# ACT-2 — ApprovalDecision.status was a bare str, so an invalid value 500'd in
# the service (raw ValueError) instead of a 422 at the boundary.
# ---------------------------------------------------------------------------

class TestApprovalDecisionValidation:
    def test_invalid_status_rejected_at_boundary(self):
        from pydantic import ValidationError
        from app.routers.agent_approvals import ApprovalDecision
        with pytest.raises(ValidationError):
            ApprovalDecision(status="maybe")
        with pytest.raises(ValidationError):
            ApprovalDecision(status="approve")  # common typo for "approved"

    def test_valid_status_accepted(self):
        from app.routers.agent_approvals import ApprovalDecision
        assert ApprovalDecision(status="approved").status == "approved"
        assert ApprovalDecision(status="rejected").status == "rejected"


# ---------------------------------------------------------------------------
# R1 — BifrostProvider.chat_stream() yielded only `content` deltas, so a
# reasoning-only stream (qwen3-chat frequently answers via reasoning_content)
# produced ZERO chunks → silent blank reply.
# ---------------------------------------------------------------------------

class TestBifrostStreamReasoningFallback:
    def _provider(self, lines):
        from app.infrastructure.llm_providers import bifrost_provider as mod

        class _Resp:
            def raise_for_status(self):
                return None

            async def aiter_lines(self):
                for l in lines:
                    yield l

        class _Ctx:
            async def __aenter__(self):
                return _Resp()

            async def __aexit__(self, *a):
                return False

        class _Client:
            def stream(self, *a, **k):
                return _Ctx()

        p = mod.BifrostProvider.__new__(mod.BifrostProvider)
        p._client = _Client()
        p._base_url = "http://x/v1"
        p._payload = lambda *a, **k: {}
        p._request_headers = lambda payload: {}
        return p

    @pytest.mark.asyncio
    async def test_reasoning_only_stream_yields_the_answer(self):
        lines = [
            'data: {"choices":[{"delta":{"reasoning_content":"hel"}}]}',
            'data: {"choices":[{"delta":{"reasoning_content":"lo"}}]}',
            "data: [DONE]",
        ]
        p = self._provider(lines)
        out = [c async for c in p.chat_stream(messages=[], model="qwen3-chat")]
        assert "".join(out) == "hello", "a reasoning-only stream must not be silently dropped"

    @pytest.mark.asyncio
    async def test_content_stream_yields_content_and_does_not_leak_reasoning(self):
        # content present → reasoning must NOT be appended (no think-leak)
        lines = [
            'data: {"choices":[{"delta":{"reasoning_content":"thinking..."}}]}',
            'data: {"choices":[{"delta":{"content":"the answer"}}]}',
            "data: [DONE]",
        ]
        p = self._provider(lines)
        out = [c async for c in p.chat_stream(messages=[], model="qwen3-chat")]
        assert "".join(out) == "the answer"
        assert "thinking" not in "".join(out)


# ---------------------------------------------------------------------------
# RET-1 + RET-3 — episodic extract_and_store: `"tags": null` from the LLM left
# tags=None (Pydantic ValidationError after the DB commit → fact persisted but
# dropped from the return list, and a NULL-tags row unreadable on retrieval);
# `importance or 50` promoted a legitimate 0 to 50.
# ---------------------------------------------------------------------------

class TestEpisodicExtractGuards:
    @pytest.mark.asyncio
    async def test_null_tags_and_zero_importance_are_preserved(self, monkeypatch):
        from app.services import episodic_memory_service as mod

        svc = mod.EpisodicMemoryService.__new__(mod.EpisodicMemoryService)

        class _LLM:
            async def structured_chat(self, **_k):
                # the exact shape a JSON-mode LLM emits for an unimportant,
                # untagged fact
                return [{"content": "a trivia fact long enough to pass the length gate",
                         "importance": 0, "tags": None}]

        class _Ollama:
            async def embed_safe(self, _content):
                return [0.01] * 8

        class _Session:
            def add(self, _m):
                return None

            async def commit(self):
                return None

        class _Ctx:
            async def __aenter__(self):
                return _Session()

            async def __aexit__(self, *a):
                return False

        monkeypatch.setattr(mod, "get_unified_llm_client", lambda: _LLM())
        monkeypatch.setattr(mod, "get_llm_client", lambda: _Ollama())
        monkeypatch.setattr(mod, "get_session", lambda: _Ctx())

        out = await mod.EpisodicMemoryService.extract_and_store(
            svc, text="Some source text well over the twenty character minimum.",
            source_type="analysis",
        )
        assert len(out) == 1, "a null-tags item must still be returned, not dropped by a ValidationError"
        assert out[0].tags == [], "null tags must coerce to an empty list"
        assert out[0].importance == 0.0, "a legitimate importance of 0 must not be promoted to 50"
