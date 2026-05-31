"""Audit-87: unit tests for the codegraph prompt enricher.

Hermetic — no network. The single transport (`_fetch_codegraph_context`) is
monkeypatched so the tests exercise hint extraction, skip/disable gates, the
cache, the token-budget formatter, and the messages-list adapter without a
live bridge.
"""
import pytest

from app.services import codegraph_enricher as ce


@pytest.fixture(autouse=True)
def _clear_cache():
    """Each test starts with an empty enricher cache (it's a module global)."""
    ce._CACHE._store.clear()
    yield
    ce._CACHE._store.clear()


# --------------------------------------------------------------------------
# extract_symbol_hints
# --------------------------------------------------------------------------

def test_extract_hints_backtick_priority():
    prompt = (
        "Please refactor the `UnifiedLLMClient` and also look at "
        "def helper_fn and class WidgetFactory in the module."
    )
    hints = ce.extract_symbol_hints(prompt, None, max_hints=2)
    assert hints[0] == "UnifiedLLMClient"  # backtick wins
    assert len(hints) <= 2


def test_extract_hints_short_haystack_returns_empty():
    # Guard: haystack < 80 chars short-circuits to [].
    assert ce.extract_symbol_hints("fix `Foo`", None) == []


def test_extract_hints_filters_stoplist():
    prompt = "x" * 90 + " discuss the `context` and the `result` and `status` here"
    hints = ce.extract_symbol_hints(prompt, None, max_hints=2)
    assert "context" not in hints and "result" not in hints and "status" not in hints


def test_is_stoplisted_dunders_and_paths():
    assert ce._is_stoplisted("__init__")
    assert ce._is_stoplisted("path/to/file.py")
    assert ce._is_stoplisted("your_thing")
    assert not ce._is_stoplisted("UnifiedLLMClient")


def test_should_skip_source_prefixes():
    assert ce._should_skip_source("embedding_call")
    assert ce._should_skip_source("health_probe")
    assert ce._should_skip_source("codegraph_enricher_self")
    assert not ce._should_skip_source("analysis")
    assert not ce._should_skip_source("")


# --------------------------------------------------------------------------
# enrich() gates
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_enrich_disabled(monkeypatch):
    monkeypatch.setenv("ZERO_CODEGRAPH_ENRICHER", "false")
    res = await ce.enrich("anything " * 20, None, source="analysis")
    assert res.enriched is False and res.status == "disabled"


@pytest.mark.asyncio
async def test_enrich_skips_skip_source():
    res = await ce.enrich("Refactor `Foo` " * 10, None, source="embedding")
    assert res.enriched is False and res.status == "skipped"


@pytest.mark.asyncio
async def test_enrich_no_hints():
    # Long enough to pass the guard but no symbol-like tokens.
    res = await ce.enrich("the quick brown fox jumps " * 6, None, source="analysis")
    assert res.enriched is False and res.status == "no_hints"


@pytest.mark.asyncio
async def test_enrich_unavailable_when_bridge_empty(monkeypatch):
    async def _none(hint, timeout=8.0, project="zero"):
        return None
    monkeypatch.setattr(ce, "_fetch_codegraph_context", _none)
    res = await ce.enrich("Explain `WidgetFactory` " * 6, None, source="analysis")
    assert res.enriched is False and res.status == "unavailable"


@pytest.mark.asyncio
async def test_enrich_ok_and_cache_hit(monkeypatch):
    calls = {"n": 0}

    async def _chunk(hint, timeout=8.0, project="zero"):
        calls["n"] += 1
        return f"context for {hint}"

    monkeypatch.setattr(ce, "_fetch_codegraph_context", _chunk)
    prompt = "Explain what the `WidgetFactory` class does in detail please " * 2
    res = await ce.enrich(prompt, "You are helpful.", source="analysis")
    assert res.enriched is True and res.status == "ok"
    assert res.tokens_added > 0
    assert "<codegraph_context" in res.new_system_prompt
    assert res.new_system_prompt.endswith("You are helpful.")

    # Second identical call must hit the cache (no new fetch).
    before = calls["n"]
    res2 = await ce.enrich(prompt, "You are helpful.", source="analysis")
    assert res2.cache_hit is True
    assert calls["n"] == before


# --------------------------------------------------------------------------
# _format_block budget
# --------------------------------------------------------------------------

def test_format_block_respects_budget():
    block, toks = ce._format_block(["Foo"], ["x" * 10000], budget_tokens=100)
    assert toks <= 130  # budget + small header slack
    assert "truncated by enricher budget" in block


def test_format_block_empty():
    block, toks = ce._format_block([], [], budget_tokens=100)
    assert block == "" and toks == 0


# --------------------------------------------------------------------------
# enrich_messages adapter
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_enrich_messages_mutates_system(monkeypatch):
    async def _chunk(hint, timeout=8.0, project="zero"):
        return f"ctx::{hint}"
    monkeypatch.setattr(ce, "_fetch_codegraph_context", _chunk)
    msgs = [
        {"role": "system", "content": "You are a careful coding assistant for the Zero backend."},
        {"role": "user", "content": "Describe the `WidgetFactory` class in detail and explain how its build pipeline works end to end."},
    ]
    res = await ce.enrich_messages(msgs, source="analysis")
    assert res.enriched is True
    assert "<codegraph_context" in msgs[0]["content"]
    assert msgs[0]["content"].endswith("You are a careful coding assistant for the Zero backend.")


@pytest.mark.asyncio
async def test_enrich_messages_inserts_system_when_absent(monkeypatch):
    async def _chunk(hint, timeout=8.0, project="zero"):
        return f"ctx::{hint}"
    monkeypatch.setattr(ce, "_fetch_codegraph_context", _chunk)
    msgs = [{"role": "user", "content": "Describe the `WidgetFactory` class in detail and explain how its build pipeline works end to end."}]
    res = await ce.enrich_messages(msgs, source="analysis")
    assert res.enriched is True
    assert msgs[0]["role"] == "system"
    assert "<codegraph_context" in msgs[0]["content"]


@pytest.mark.asyncio
async def test_enrich_messages_noop_when_not_enriched(monkeypatch):
    # Bridge returns nothing -> unavailable; messages must be untouched.
    async def _none(hint, timeout=8.0, project="zero"):
        return None
    monkeypatch.setattr(ce, "_fetch_codegraph_context", _none)
    msgs = [{"role": "user", "content": "Describe the `WidgetFactory` class in detail and explain how its build pipeline works end to end."}]
    original = msgs[0]["content"]
    res = await ce.enrich_messages(msgs, source="analysis")
    assert res.enriched is False
    assert len(msgs) == 1 and msgs[0]["content"] == original
