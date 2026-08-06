"""
A list-shaped `output_schema` must always yield a list.

Models answer a list schema with a bare object when they produce exactly one
result, and with a wrapper object when they decide to nest. Callers wrote
`if isinstance(result, list)` and dropped everything else, so one result became
no result.

This class has bitten twice:
  * run 868a8df4 (2026-08-01) -- `email_to_tasks` extracted 0 items from an
    unmistakably actionable email.
  * run c214aef9 (2026-08-06) -- `reflect_on_decisions` analysed 20 decisions and
    stored 0 learnings on every 8-hourly run, because a single-learning reply is
    a bare item and the unwrap branch only recognised wrapper keys.

Seven of the eight list-schema call sites in the repo had the same hole, so the
normalisation lives in `structured_chat` and is pinned here.
"""

import pytest

from app.infrastructure.unified_llm_client import _coerce_to_schema_shape

LEARNING_SCHEMA = [{"learning": "string", "confidence": "number"}]


def test_bare_item_becomes_single_element_list():
    """The exact payload that silently zeroed the reflection loop."""
    result = _coerce_to_schema_shape(
        {"learning": "Prefer smaller batches", "confidence": 0.9}, LEARNING_SCHEMA
    )
    assert result == [{"learning": "Prefer smaller batches", "confidence": 0.9}]


def test_wrapper_object_is_unwrapped():
    payload = {"learnings": [{"learning": "a", "confidence": 1}, {"learning": "b", "confidence": 1}]}
    assert _coerce_to_schema_shape(payload, LEARNING_SCHEMA) == payload["learnings"]


def test_list_passes_through_untouched():
    payload = [{"learning": "a", "confidence": 1}]
    assert _coerce_to_schema_shape(payload, LEARNING_SCHEMA) is payload


def test_item_wins_over_wrapper_when_keys_match_schema():
    """
    A single-key item whose value is a list must not be mistaken for a wrapper.

    Schema key match is the discriminator, which is why the exemplar's keys are
    consulted before the single-key-list heuristic.
    """
    schema = [{"tags": ["string"]}]
    payload = {"tags": ["alpha", "beta"]}
    assert _coerce_to_schema_shape(payload, schema) == [payload]


def test_generic_wrapper_keys_are_unwrapped():
    for key in ("results", "items", "data"):
        payload = {key: [{"learning": "x", "confidence": 1}], "note": "extra"}
        assert _coerce_to_schema_shape(payload, LEARNING_SCHEMA) == payload[key]


def test_unrecognised_object_is_kept_not_dropped():
    """A bad guess costs nothing; a silent [] costs the whole call."""
    payload = {"totally": "unexpected"}
    assert _coerce_to_schema_shape(payload, LEARNING_SCHEMA) == [payload]


def test_empty_object_yields_empty_list():
    assert _coerce_to_schema_shape({}, LEARNING_SCHEMA) == []


def test_dict_schema_is_left_alone():
    """Only list-shaped schemas are coerced; object schemas keep their shape."""
    payload = {"learning": "a"}
    assert _coerce_to_schema_shape(payload, {"learning": "string"}) is payload
    assert _coerce_to_schema_shape(payload, None) is payload


def test_non_dict_result_is_left_alone():
    assert _coerce_to_schema_shape("plain string", LEARNING_SCHEMA) == "plain string"


@pytest.mark.asyncio
async def test_reflection_keeps_a_single_bare_item_learning(monkeypatch):
    """
    Service-level companion to Gap #6's wrapper test.

    Gap #6 pinned the wrapper shape. The bare-item shape -- what a
    single-learning reply actually looks like -- went unpinned and was silently
    dropped on every 8-hourly run.
    """
    import app.services.reflection_service as rs

    class _FakeLLM:
        async def structured_chat(self, **kw):
            return {"learning": "ship smaller", "confidence": 0.9}

    monkeypatch.setattr(rs, "get_unified_llm_client", lambda: _FakeLLM())
    out = await rs.get_reflection_service().reflect_on_decisions(
        [{"action_type": "x"}], "ops"
    )
    assert out == ["ship smaller"]
