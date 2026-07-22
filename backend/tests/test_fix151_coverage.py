"""Fix-151 (supervise ee392aa1) — coverage sweep.

IDX-NUL: a corrupt vault file padded with 0x00 bytes (observed live:
20_Calendar/Daily/2026-06-26.md, 1165 of 2048 bytes NUL, a half-written
health-watchdog journal) decoded NUL into chunk content. PostgreSQL text
columns reject 0x00, so the batch INSERT raised DataError and aborted the
ENTIRE vault reindex tick every 2 minutes — silently, because the scheduler
wrapper caught+logged the error and still recorded job status=completed.

The fix strips NUL at the decode boundary in _index_file so one corrupt file
degrades to its readable text instead of breaking all indexing.
"""

import pytest


class TestVaultIndexerStripsNul:
    @pytest.mark.asyncio
    async def test_index_file_strips_nul_from_stored_content(self, monkeypatch, tmp_path):
        """A file whose body carries 0x00 must be indexed with NUL stripped —
        pre-fix the content reached the INSERT verbatim and PostgreSQL raised
        DataError, aborting the whole reindex batch."""
        from app.services import vault_indexer_service as mod

        svc = mod.VaultIndexerService.__new__(mod.VaultIndexerService)

        # _index_file reads fp.stat().st_mtime for file_mtime, so fp must exist.
        real_fp = tmp_path / "x.md"
        real_fp.write_bytes(b"placeholder")

        async def _fake_embed(text):
            # embedder must never see NUL either; assert the strip happened upstream
            assert "\x00" not in text, "chunk content must be NUL-free before embed"
            return [0.0] * 8

        monkeypatch.setattr(svc, "_embed", _fake_embed, raising=False)

        captured: list = []

        class _FakeSession:
            async def execute(self, *_a, **_k):
                return None

            def add_all(self, rows):
                captured.extend(rows)

            async def commit(self):
                return None

        class _Ctx:
            async def __aenter__(self):
                return _FakeSession()

            async def __aexit__(self, *a):
                return False

        monkeypatch.setattr(mod, "get_session", lambda: _Ctx())

        # body has a real NUL run (the corruption signature) plus readable text
        raw = b"# Daily\n\nSystem health \x00\x00\x00 report ok\n"
        written = await mod.VaultIndexerService._index_file(
            svc, real_fp, "20_Calendar/Daily/x.md", raw, "hash151"
        )

        assert written >= 1, "the readable text must still be indexed"
        assert captured, "rows must be written"
        for row in captured:
            assert "\x00" not in (row.content or ""), (
                "stored chunk content must never contain NUL (0x00) — PostgreSQL "
                "text columns reject it and one such row aborts the whole batch"
            )
        # the readable words survive the strip
        joined = " ".join((r.content or "") for r in captured)
        assert "report ok" in joined


class TestMealPromoLlmCircuitBreaker:
    """CB-LLM: the 4-hourly meal_promo_hunt batch fired ~90+ doomed LLM
    extractions when the LLM was fully unavailable (vllm-local saturated at
    max_num_seqs=1; groq/cerebras 429; freellm 401), each cascading through
    every dead provider and starving the shared GPU. A time-boxed breaker
    skips extraction during a cooldown once 'all providers failed' is seen."""

    def _fresh_service(self):
        from app.services import meal_promo_hunter_service as mod
        return mod, mod.MealPromoHunterService.__new__(mod.MealPromoHunterService)

    @pytest.mark.asyncio
    async def test_open_breaker_skips_llm_call_entirely(self, monkeypatch):
        import time as _t
        mod, svc = self._fresh_service()
        mod._llm_cb["until"] = _t.monotonic() + 100  # breaker OPEN
        try:
            called = {"n": 0}

            def _boom():
                called["n"] += 1
                raise AssertionError("LLM client must NOT be built while breaker is open")

            monkeypatch.setattr(mod, "get_unified_llm_client", _boom, raising=False)
            out = await mod.MealPromoHunterService._extract_codes_llm(
                svc, "some page markdown with codes", "HelloFresh", "hellofresh"
            )
            assert out == []
            assert called["n"] == 0, "open breaker must short-circuit before any LLM call"
        finally:
            mod._llm_cb["until"] = 0.0

    @pytest.mark.asyncio
    async def test_all_providers_failed_trips_breaker(self, monkeypatch):
        import time as _t
        mod, svc = self._fresh_service()
        mod._llm_cb["until"] = 0.0  # closed
        try:
            class _FakeClient:
                async def chat(self, **_kw):
                    raise RuntimeError(
                        "All LLM providers failed. Last error: freellmapi HTTP 401 Invalid API key"
                    )

            monkeypatch.setattr(mod, "get_unified_llm_client", lambda: _FakeClient(), raising=False)
            out = await mod.MealPromoHunterService._extract_codes_llm_inner(
                svc, "page markdown", "HelloFresh", "hellofresh"
            )
            assert out == []
            assert mod._llm_cb["until"] > _t.monotonic(), (
                "an all-providers-failed error must OPEN the breaker so the rest "
                "of the batch skips the dead gateway"
            )
        finally:
            mod._llm_cb["until"] = 0.0

    @pytest.mark.asyncio
    async def test_ordinary_error_does_not_trip_breaker(self, monkeypatch):
        """A single non-fatal extract error (bad JSON, one merchant hiccup) must
        NOT open the breaker — only a full fallback-chain failure does."""
        import time as _t
        mod, svc = self._fresh_service()
        mod._llm_cb["until"] = 0.0
        try:
            class _FakeClient:
                async def chat(self, **_kw):
                    raise RuntimeError("timeout talking to one provider")

            monkeypatch.setattr(mod, "get_unified_llm_client", lambda: _FakeClient(), raising=False)
            out = await mod.MealPromoHunterService._extract_codes_llm_inner(
                svc, "page markdown", "HelloFresh", "hellofresh"
            )
            assert out == []
            assert mod._llm_cb["until"] <= _t.monotonic(), "a single provider error must not open the breaker"
        finally:
            mod._llm_cb["until"] = 0.0
