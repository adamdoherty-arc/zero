"""Tests for parse_json_response — the LLM-output → dict converter.

Locks in robust extraction against the failure modes audit-2026-04-28
exposed: Kimi reasoning prose containing stray ``{`` / ``}`` characters
followed by the real JSON answer 8 KB later.
"""

from __future__ import annotations

import pytest

from app.services.character_content_utils import (
    _extract_balanced_json,
    parse_json_response,
)


def test_parses_clean_json():
    out = parse_json_response('{"hook": "Foo", "slides": []}')
    assert out == {"hook": "Foo", "slides": []}


def test_strips_think_tags():
    raw = '<think>internal reasoning {fake brace}</think>{"hook": "real"}'
    assert parse_json_response(raw) == {"hook": "real"}


def test_extracts_from_markdown_code_fence():
    raw = 'Here you go:\n```json\n{"hook": "fenced"}\n```'
    assert parse_json_response(raw) == {"hook": "fenced"}


def test_handles_trailing_commas():
    raw = '{"hook": "Foo", "slides": [1, 2, 3,],}'
    out = parse_json_response(raw)
    assert out == {"hook": "Foo", "slides": [1, 2, 3]}


def test_skips_prose_brace_and_finds_real_json():
    """The Kimi reasoning failure mode — prose contains ``{director}``
    placeholder before the real JSON answer.
    """
    raw = (
        "The user wants a carousel. The format should be {placeholder} "
        "or {director} for examples. Now the real answer:\n"
        '{"hook": "real one", "slides": [{"slide_num": 1, "text": "first"}]}'
    )
    out = parse_json_response(raw)
    assert out == {
        "hook": "real one",
        "slides": [{"slide_num": 1, "text": "first"}],
    }


def test_handles_8kb_reasoning_with_json_at_end():
    """Concrete repro of the 2026-04-28 production failure: Kimi returned
    8 KB of thinking + the JSON at the very end. The greedy regex captured
    everything between the first prose ``{`` and the last JSON ``}``.
    """
    prose = (
        "The user wants a viral TikTok carousel about Black Panther (2018) "
        "with a Hidden Details angle, 6 slides. Constraints: hook must be "
        "specific, each slide reveals something. The schema requires "
        "{slide_num, text, image_query} per slide. Let me think about "
        "{the angle} and {what facts to use}. " * 50  # ~5 KB of prose
    )
    json_block = (
        '{"title": "BP secrets", "hook_text": "There are 12 hidden details", '
        '"slides": [{"slide_num": 1, "text": "Hook", "image_query": "Black Panther"}, '
        '{"slide_num": 2, "text": "Fact 2", "image_query": "Wakanda"}], '
        '"caption": "swipe", "hashtags": ["mcu"], "music_mood": "epic"}'
    )
    raw = prose + "\n\nFinal answer:\n" + json_block
    out = parse_json_response(raw, context="black_panther_test")
    assert out["title"] == "BP secrets"
    assert out["hook_text"] == "There are 12 hidden details"
    assert len(out["slides"]) == 2
    assert out["slides"][0]["text"] == "Hook"


def test_repairs_truncated_json():
    """When the LLM gets cut off mid-output, fall back to brace repair."""
    raw = '{"hook": "incomplete", "slides": [{"slide_num": 1, "text": "fact"'
    out = parse_json_response(raw, context="truncated_test")
    assert out["hook"] == "incomplete"


def test_parses_array_at_top_level():
    raw = 'Here are the verdicts: [{"verdict": "KEEP"}, {"verdict": "KILL"}]'
    out = parse_json_response(raw)
    assert isinstance(out, list)
    assert len(out) == 2


def test_returns_empty_dict_on_unrecoverable_input():
    raw = "Sorry, I cannot help with that request."
    out = parse_json_response(raw, context="refusal")
    assert out == {}


# ---------------------------------------------------------------------------
# _extract_balanced_json unit tests
# ---------------------------------------------------------------------------

def test_balanced_extractor_handles_strings_with_braces():
    """``{`` / ``}`` inside string literals must not affect depth tracking."""
    raw = '{"text": "value with {braces} inside"}'
    extracted = _extract_balanced_json(raw, 0, '{', '}')
    assert extracted == raw


def test_balanced_extractor_handles_escapes():
    raw = r'{"text": "with \"escaped quote\" {still inside}"}'
    extracted = _extract_balanced_json(raw, 0, '{', '}')
    assert extracted == raw


def test_balanced_extractor_returns_none_when_unbalanced():
    raw = '{"hook": "incomplete"'
    assert _extract_balanced_json(raw, 0, '{', '}') is None


def test_balanced_extractor_handles_nested_objects():
    raw = '{"a": {"b": {"c": 1}}}'
    extracted = _extract_balanced_json(raw, 0, '{', '}')
    assert extracted == raw
