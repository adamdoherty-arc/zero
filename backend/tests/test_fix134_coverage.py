"""Fix-134 coverage batch (supervise 6a7efcb9, 2026-07-02).

Two halves:

1. RSN-NEW1 regression tests: `run_experiment` returns `get_experiment()`
   (Optional) on every terminal path, so a row deleted mid-run yields None.
   The `/{exp_id}/run` router returned that None under
   `response_model=Experiment`, which FastAPI surfaces as a 500
   ResponseValidationError. Same class as the shipped RSN-5 council guard;
   the sibling GET route already had the 404 guard the run route lacked.

2. Dedicated unit tests for previously-untested pure-logic methods
   (inherited sprint 11433, test_coverage below cross-project avg):
   - vault_indexer_service: _parse_frontmatter / _split_by_headings /
     _chunk_section (incl. the Fix-118 IDX-B no-dropped-bytes property).
   - reachy_realtime.local_handler: _looks_like_long_short_noise_transcript.
   - reflection_service.reflect: all four exit paths (threshold-met validate,
     empty-critique validate, improve floor, outer-exception break) plus the
     RFL-2 non-dict shape coercion.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

import app.routers.experiments as exp_router
import app.services.reflection_service as rs
from app.services.vault_indexer_service import (
    _MAX_CHUNK_CHARS,
    _chunk_section,
    _parse_frontmatter,
    _split_by_headings,
)
# =====================================================================
# RSN-NEW1 — experiments run router guards the mid-run-delete None
# =====================================================================

class _FakeExpService:
    def __init__(self, pre_check_exp, run_result):
        self._pre = pre_check_exp
        self._run = run_result

    async def get_experiment(self, exp_id):
        return self._pre

    async def run_experiment(self, exp_id):
        return self._run


async def test_run_experiment_404_when_row_vanishes_mid_run(monkeypatch):
    """Row exists at pre-check, deleted during the run -> 404, not a 500."""
    sentinel = object()
    monkeypatch.setattr(
        exp_router, "get_experiment_service",
        lambda: _FakeExpService(pre_check_exp=sentinel, run_result=None),
    )
    with pytest.raises(HTTPException) as exc:
        await exp_router.run_experiment("exp-vanished")
    assert exc.value.status_code == 404


async def test_run_experiment_passthrough_on_success(monkeypatch):
    sentinel = object()
    monkeypatch.setattr(
        exp_router, "get_experiment_service",
        lambda: _FakeExpService(pre_check_exp=sentinel, run_result=sentinel),
    )
    assert await exp_router.run_experiment("exp-ok") is sentinel


async def test_run_experiment_404_when_missing_at_precheck(monkeypatch):
    monkeypatch.setattr(
        exp_router, "get_experiment_service",
        lambda: _FakeExpService(pre_check_exp=None, run_result=None),
    )
    with pytest.raises(HTTPException) as exc:
        await exp_router.run_experiment("exp-missing")
    assert exc.value.status_code == 404


# =====================================================================
# vault_indexer_service._parse_frontmatter
# =====================================================================

def test_parse_frontmatter_absent():
    fm, body = _parse_frontmatter("just a body\nno frontmatter")
    assert fm == {}
    assert body == "just a body\nno frontmatter"


def test_parse_frontmatter_valid():
    fm, body = _parse_frontmatter("---\ntitle: x\ntags: [a, b]\n---\nbody text")
    assert fm["title"] == "x"
    assert fm["tags"] == ["a", "b"]
    assert body == "body text"


def test_parse_frontmatter_only_no_body_returns_empty_str():
    """IDX-FM-NOEOL: frontmatter-only note -> body coerced to '' (not None)."""
    fm, body = _parse_frontmatter("---\ntitle: x\n---")
    assert fm == {"title": "x"}
    assert body == ""


def test_parse_frontmatter_invalid_yaml_falls_back_to_full_text():
    text = "---\nfoo: [a, b\n---\nbody"
    fm, body = _parse_frontmatter(text)
    assert fm == {}
    assert body == text


def test_parse_frontmatter_non_dict_yaml_coerced():
    fm, body = _parse_frontmatter("---\n- a\n- b\n---\nbody")
    assert fm == {}
    assert body == "body"


# =====================================================================
# vault_indexer_service._split_by_headings
# =====================================================================

def test_split_no_headings_single_section():
    assert _split_by_headings("plain body\nsecond line") == [
        ("", "plain body\nsecond line")
    ]


def test_split_nested_heading_paths():
    text = "# A\ncontent a\n## B\ncontent b"
    assert _split_by_headings(text) == [("A", "content a"), ("A > B", "content b")]


def test_split_sibling_h1_resets_path():
    text = "# A\na\n## B\nb\n# C\nc"
    assert _split_by_headings(text) == [("A", "a"), ("A > B", "b"), ("C", "c")]


def test_split_preamble_before_first_heading():
    text = "preamble\n# A\na"
    assert _split_by_headings(text) == [("", "preamble"), ("A", "a")]


def test_split_empty_sections_skipped():
    assert _split_by_headings("# A\n# B\nb") == [("B", "b")]


# =====================================================================
# vault_indexer_service._chunk_section
# =====================================================================

def test_chunk_empty_body():
    assert _chunk_section("H", "   ") == []


def test_chunk_small_body_stays_whole():
    # Fix-155 (IDX-7): the fixture was "small body" (9 chars of signal), which
    # now falls under the boilerplate floor added to _chunk_section. The
    # property under test is unchanged — a body below _MAX_CHUNK_CHARS is
    # emitted as ONE whole chunk rather than split — so only the fixture grew
    # enough to carry real signal.
    body = "A small but genuinely meaningful body of vault prose."
    chunks = _chunk_section("H", body)
    assert len(chunks) == 1
    assert chunks[0].idx == 0
    assert chunks[0].heading_path == "H"
    assert chunks[0].content == body
    assert chunks[0].token_count == len(body) // 4


def test_chunk_large_body_multi_chunk_no_bytes_dropped():
    """Fix-118 IDX-B property: every region of a large body lands in a chunk."""
    body = " ".join(f"w{i}" for i in range(1200))  # ~7000 chars, no \n\n
    chunks = _chunk_section("H", body)
    assert len(chunks) > 1
    assert all(len(c.content) <= _MAX_CHUNK_CHARS for c in chunks)
    assert [c.idx for c in chunks] == list(range(len(chunks)))
    # tail must be present in the final chunk
    assert body[-80:] in chunks[-1].content
    # every 500-char-stride marker word must appear in at least one chunk
    for probe in range(0, 1200, 100):
        w = f"w{probe}"
        assert any(w in c.content for c in chunks), f"{w} dropped from all chunks"


def test_chunk_paragraph_boundary_snap_keeps_post_boundary_text():
    """The IDX-B regression: bytes after a paragraph-boundary snap must not vanish."""
    body = "x" * 1500 + "\n\nMARKER-AFTER-BOUNDARY " + "y" * 2500
    chunks = _chunk_section("H", body)
    assert chunks[0].content == "x" * 1500  # snapped at the paragraph boundary
    assert any("MARKER-AFTER-BOUNDARY" in c.content for c in chunks[1:])
    assert body[-60:] in chunks[-1].content


# =====================================================================
# reflection_service.reflect — exit paths
# =====================================================================

class _SeqLLM:
    """Sequence-driven fake: pops one queued response per call."""

    def __init__(self, structured=None, chats=None):
        self.structured = list(structured or [])
        self.chats = list(chats or [])
        self.structured_calls = 0
        self.chat_calls = 0

    async def structured_chat(self, **kw):
        self.structured_calls += 1
        item = self.structured.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def chat(self, **kw):
        self.chat_calls += 1
        item = self.chats.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _patch_llm(monkeypatch, fake):
    monkeypatch.setattr(rs, "get_unified_llm_client", lambda: fake)


async def test_reflect_empty_content_short_circuits(monkeypatch):
    def _boom():
        raise AssertionError("LLM client must not be constructed for empty content")

    monkeypatch.setattr(rs, "get_unified_llm_client", _boom)
    out = await rs.ReflectionService().reflect("")
    assert out == {"final_content": "", "iterations": 0,
                   "improvements_made": [], "quality_scores": []}


async def test_reflect_threshold_exit_appends_calibrated_validation_score(monkeypatch):
    improved = "improved content " * 5  # >= 40 chars
    fake = _SeqLLM(
        structured=[
            {"overall": 90, "issues": ["i1"], "scores": {}},   # iter0 analyze (no break: iteration==0)
            {"critiques": ["c1"], "severity": "low"},           # iter0 critique
            {"overall": 92, "issues": [], "scores": {}},        # iter1 analyze -> threshold branch
            {"overall": 88},                                     # iter1 validate
        ],
        chats=[improved],
    )
    _patch_llm(monkeypatch, fake)
    out = await rs.ReflectionService().reflect("content", quality_threshold=75.0)
    last = out["quality_scores"][-1]
    assert last["validation"] is True
    assert last["score"] == 88.0
    assert last["iteration"] == 1.5
    assert out["iterations"] == 1
    assert out["final_content"] == improved.strip()


async def test_reflect_threshold_validate_failure_degrades_not_raises(monkeypatch):
    fake = _SeqLLM(
        structured=[
            {"overall": 90, "issues": [], "scores": {}},
            {"critiques": ["c1"], "severity": "low"},
            {"overall": 92, "issues": [], "scores": {}},
            RuntimeError("validate blew up"),
        ],
        chats=["improved content that is definitely long enough to pass"],
    )
    _patch_llm(monkeypatch, fake)
    out = await rs.ReflectionService().reflect("content")
    # no validation entry appended; last score is the iter1 analyze score
    assert out["quality_scores"][-1]["score"] == 92.0
    assert "validation" not in out["quality_scores"][-1]


async def test_reflect_empty_critiques_validates_before_break(monkeypatch):
    """Fix-119 RFL-2 path: 'good enough' exit still reports a calibrated score."""
    fake = _SeqLLM(structured=[
        {"overall": 50, "issues": [], "scores": {}},  # analyze
        {"critiques": []},                             # critique -> early exit
        {"overall": 77},                               # validate before break
    ])
    _patch_llm(monkeypatch, fake)
    out = await rs.ReflectionService().reflect("content")
    assert out["iterations"] == 0
    assert out["quality_scores"][-1]["score"] == 77.0
    assert out["quality_scores"][-1]["validation"] is True


async def test_reflect_non_dict_llm_shapes_coerced_not_raised(monkeypatch):
    """RFL-2: a JSON-array reply on analyze/critique degrades instead of aborting."""
    fake = _SeqLLM(structured=[
        ["not", "a", "dict"],   # analyze -> coerced {}
        ["also", "a", "list"],  # critique -> coerced {} -> empty critiques exit
        {"overall": 61},        # validate
    ])
    _patch_llm(monkeypatch, fake)
    out = await rs.ReflectionService().reflect("content")
    assert out["quality_scores"][0]["score"] == 50.0  # default when coerced
    assert out["quality_scores"][-1]["score"] == 61.0


async def test_reflect_improve_floor_discards_trivial_rewrite(monkeypatch):
    fake = _SeqLLM(
        structured=[
            {"overall": 50, "issues": ["i"], "scores": {}},
            {"critiques": ["c1"], "severity": "high"},
            {"overall": 60},  # last-iteration validate
        ],
        chats=["tiny"],  # < 40 chars -> discarded
    )
    _patch_llm(monkeypatch, fake)
    out = await rs.ReflectionService().reflect("original content", max_iterations=1)
    assert out["final_content"] == "original content"
    assert out["iterations"] == 0
    assert out["improvements_made"] == []


async def test_reflect_improve_accepted_records_severity(monkeypatch):
    improved = "a genuinely better piece of content, rewritten properly"
    fake = _SeqLLM(
        structured=[
            {"overall": 50, "issues": ["i"], "scores": {}},
            {"critiques": ["c1"], "severity": "high"},
            {"overall": 80},  # last-iteration validate
        ],
        chats=[improved],
    )
    _patch_llm(monkeypatch, fake)
    out = await rs.ReflectionService().reflect("original", max_iterations=1)
    assert out["final_content"] == improved
    assert out["iterations"] == 1
    assert out["improvements_made"][0]["severity"] == "high"


async def test_reflect_analyze_exception_breaks_gracefully(monkeypatch):
    fake = _SeqLLM(structured=[RuntimeError("brain down")])
    _patch_llm(monkeypatch, fake)
    out = await rs.ReflectionService().reflect("content")
    assert out["final_content"] == "content"
    assert out["quality_scores"] == []
    assert out["iterations"] == 0


async def test_reflect_on_decisions_recovers_unknown_wrapper(monkeypatch):
    """
    An unknown wrapper key is recovered, not dropped (Fix-164 — was RFL-8).

    RFL-8 originally asserted `== []` here: a wrapper whose key was not in a
    hardcoded allow-list was discarded. But this payload is a well-formed
    learning that merely arrived under a name nobody had listed, and discarding
    it is the same lossy behaviour that left the reflection loop analysing 20
    decisions and storing 0 learnings every 8 hours. A single-key object whose
    value is a list is a wrapper regardless of what the model called it.
    """
    class _Fake:
        async def structured_chat(self, **kw):
            return {"unexpected_key": [{"learning": "hidden"}]}

    _patch_llm(monkeypatch, _Fake())
    out = await rs.ReflectionService().reflect_on_decisions([{"action_type": "x"}], "ops")
    assert out == ["hidden"]


async def test_reflect_on_decisions_object_with_no_learning_yields_empty(monkeypatch):
    """Recovery is not credulity: an object carrying no learning still gives []."""
    class _Fake:
        async def structured_chat(self, **kw):
            return {"totally": "unexpected"}

    _patch_llm(monkeypatch, _Fake())
    out = await rs.ReflectionService().reflect_on_decisions([{"action_type": "x"}], "ops")
    assert out == []


async def test_reflect_on_decisions_filters_malformed_items(monkeypatch):
    class _Fake:
        async def structured_chat(self, **kw):
            return [{"learning": "A"}, {"nope": 1}, "junk", {"learning": ""}]

    _patch_llm(monkeypatch, _Fake())
    out = await rs.ReflectionService().reflect_on_decisions([{"action_type": "x"}], "ops")
    assert out == ["A"]
