"""Coverage for the carousel V2 service layer that activities depend on:

  brand_kit_service        — palette + LUT lookup
  voice_loader             — system prompt composition
  fact_verifier_service    — citation regex + decomposition + cross-source rule
  atomic_facts_service     — make_fact / sha256 idempotency / cross_source_rule
  skeptic_service          — verdict application
  judge_panel_service      — composite from per-axis scores (Bradley-Terry)
  drift_detector           — EWMA + CUSUM + Cohen κ math
  golden_set_service       — Cohen κ implementation
  exemplar_memory          — render_for_designer block format
  caption_service          — hashtag stack composition
  idempotency              — sha256 stability
  image_scorer_service     — phash dedup + composite z-score math
  cinematic_pass           — Pillow no-op behaviour when pillow-lut missing
"""

from __future__ import annotations

import pytest

# Most tests in this file are sync (pure-Python service logic). Don't apply
# the asyncio mark globally — it triggers warnings on every sync test.


# ---------------------------------------------------------------------------
# brand_kit_service
# ---------------------------------------------------------------------------

def test_brand_kit_known_property_returns_specific_kit():
    from app.services.carousel_v2.brand_kit_service import KITS, get_brand_kit

    boys = get_brand_kit("the_boys")
    assert boys.key == "the_boys"
    assert boys.primary.startswith("#")
    assert boys.lut_path and boys.lut_path.endswith(".cube")
    assert all(k in KITS for k in ("mcu", "dceu", "the_boys", "snyderverse", "stranger_things"))


def test_brand_kit_unknown_falls_back_to_mcu():
    from app.services.carousel_v2.brand_kit_service import get_brand_kit

    fallback = get_brand_kit("non_existent_property")
    assert fallback.key == "mcu"


# ---------------------------------------------------------------------------
# voice_loader
# ---------------------------------------------------------------------------

def test_voice_loader_reads_yaml_files():
    from app.services.carousel_v2.voice_loader import compose_system_prompt, load_voice

    voice = load_voice("the_boys")
    assert voice["property"] == "the_boys"
    assert "tone" in voice

    prompt = compose_system_prompt("the_boys")
    assert "PROPERTY:" in prompt
    assert "TONE:" in prompt
    assert "FORBIDDEN PHRASES:" in prompt


def test_voice_loader_missing_property_returns_neutral_default(tmp_path, monkeypatch):
    from app.services.carousel_v2 import voice_loader

    voice_loader.load_voice.cache_clear()
    monkeypatch.setenv("ZERO_VOICES_DIR", str(tmp_path))

    voice = voice_loader.load_voice("never_existed")
    assert voice["tone"] == "neutral"
    assert voice["lexicon"] == []
    voice_loader.load_voice.cache_clear()


# ---------------------------------------------------------------------------
# fact_verifier_service
# ---------------------------------------------------------------------------

def test_extract_cited_ids_pulls_all_fact_id_tags():
    from app.services.carousel_v2.fact_verifier_service import extract_cited_ids

    text = "Vought made him [fact_id:abc1] and lied about it [fact_id:def2]."
    assert extract_cited_ids(text) == ["abc1", "def2"]


def test_strip_uncited_sentences_removes_unsourced_text():
    from app.services.carousel_v2.fact_verifier_service import strip_uncited_sentences

    text = (
        "He killed her [fact_id:a]. This part is invented. "
        "It was on screen [fact_id:b]."
    )
    out = strip_uncited_sentences(text)
    assert "[fact_id:a]" in out
    assert "[fact_id:b]" in out
    assert "invented" not in out


def test_decompose_to_claims_returns_only_cited_sentences():
    from app.services.carousel_v2.fact_verifier_service import decompose_to_claims

    text = "Hook line. Vought made him [fact_id:a]. Random aside. He died [fact_id:b]."
    claims = decompose_to_claims(text)
    assert len(claims) == 2


# ---------------------------------------------------------------------------
# atomic_facts_service
# ---------------------------------------------------------------------------

def test_make_fact_stamps_sha256_deterministically():
    from app.models.carousel import SourceKind, TrustTier
    from app.services.carousel_v2.atomic_facts_service import _hash, make_fact

    f = make_fact(
        subject="Loki",
        predicate="killed_by",
        obj="Thanos",
        source_kind=SourceKind.FANDOM,
        source_url="https://marvel.fandom.com/loki",
        source_quote="Thanos snapped Loki's neck in Infinity War",
        trust_tier=TrustTier.CANON,
        franchise="mcu",
    )
    assert f.sha256 == _hash("Loki", "killed_by", "Thanos", "https://marvel.fandom.com/loki")


def test_cross_source_rule_requires_tier_one_or_two_tier_two():
    from app.models.carousel import AtomicFact, Source, SourceKind, TrustTier
    from app.services.carousel_v2.atomic_facts_service import cross_source_rule

    def _f(tier: int) -> AtomicFact:
        return AtomicFact(
            id=f"id-{tier}",
            subject="x",
            predicate="y",
            object="z",
            trust_tier=TrustTier(tier),
            source=Source(kind=SourceKind.OTHER, url="https://example/" + str(tier)),
            sha256="0" * 64,
        )

    assert cross_source_rule([_f(1)]) is True
    assert cross_source_rule([_f(2)]) is False
    assert cross_source_rule([_f(2), _f(2)]) is True
    assert cross_source_rule([_f(3), _f(4)]) is False
    assert cross_source_rule([]) is False


# ---------------------------------------------------------------------------
# skeptic_service
# ---------------------------------------------------------------------------

def test_apply_verdicts_drops_kills_and_substitutes_rewrites():
    from app.models.carousel import SkepticReport, SkepticVerdict, TrapCategory
    from app.services.carousel_v2.skeptic_service import apply_verdicts

    slides = [
        {"slide_num": 1, "text": "Homelander wasn't supposed to be the villain"},
        {"slide_num": 2, "text": "Vought engineered him from infancy"},
        {"slide_num": 3, "text": "Soldier Boy is his father"},
    ]
    reports = [
        SkepticReport(claim=slides[0]["text"], verdict=SkepticVerdict.KEEP),
        SkepticReport(
            claim=slides[1]["text"],
            verdict=SkepticVerdict.REWRITE,
            rewrite_suggestion="Vought engineered him from before birth",
        ),
        SkepticReport(
            claim=slides[2]["text"],
            verdict=SkepticVerdict.KILL,
            trap_category=TrapCategory.FAN_THEORY,
        ),
    ]
    out, counts = apply_verdicts(slides, reports)
    assert counts == {"keep": 1, "rewrite": 1, "kill": 1}
    assert len(out) == 2
    assert "before birth" in out[1]["text"]


# ---------------------------------------------------------------------------
# judge_panel_service composite math
# ---------------------------------------------------------------------------

def test_rubric_weights_sum_to_one_and_composite_floor_makes_sense():
    from app.models.carousel import (
        AUTO_PUBLISH_THRESHOLD,
        RUBRIC_WEIGHTS,
        RubricAxis,
    )

    # Voice + novelty are floor-checked separately, so they're 0 in the
    # composite sum. The remaining 5 axes carry the weight.
    weighted_axes = {a: w for a, w in RUBRIC_WEIGHTS.items() if w > 0}
    assert pytest.approx(sum(weighted_axes.values()), abs=1e-6) == 1.0
    assert RubricAxis.HOOK_STRENGTH in weighted_axes
    assert 5.0 < AUTO_PUBLISH_THRESHOLD < 9.0


# ---------------------------------------------------------------------------
# reflexion_service
# ---------------------------------------------------------------------------

def test_reflexion_make_reflection_targets_lowest_axes():
    from app.models.carousel import (
        CarouselRubric,
        JudgeAxisScore,
        JudgeName,
        RubricAxis,
    )
    from app.services.carousel_v2.reflexion_service import (
        append_reflection,
        make_reflection,
    )

    rubric = CarouselRubric(
        per_axis_per_judge=[
            JudgeAxisScore(
                judge=JudgeName.KIMI_K2_6,
                axis=RubricAxis.FACT_ACCURACY,
                score=3.0,
                rationale="Uncited claim about Soldier Boy",
            ),
            JudgeAxisScore(
                judge=JudgeName.MINIMAX_M2_7,
                axis=RubricAxis.HOOK_STRENGTH,
                score=4.0,
                rationale="Hook generic",
            ),
        ],
        aggregated={
            RubricAxis.FACT_ACCURACY: 3.0,
            RubricAxis.HOOK_STRENGTH: 4.0,
            RubricAxis.NARRATIVE_ARC: 8.0,
        },
        composite=4.5,
    )
    text = make_reflection(rubric, threshold=6.0)
    assert "fact_accuracy" in text or "hook_strength" in text

    history = append_reflection([], text)
    assert len(history) == 1
    # Cap at 5
    history = append_reflection(["a", "b", "c", "d", "e"], "f")
    assert len(history) == 5
    assert history[-1] == "f"


def test_reflexion_sanitizes_html_and_urls():
    from app.services.carousel_v2.reflexion_service import _sanitize

    s = _sanitize("<script>bad</script> see https://evil/x for more")
    assert "<script>" not in s
    assert "https://evil" not in s
    assert "[url]" in s


# ---------------------------------------------------------------------------
# drift_detector EWMA + CUSUM
# ---------------------------------------------------------------------------

def test_ewma_recent_dominates():
    from app.services.carousel_v2.drift_detector import ewma

    base = [5.0] * 20
    drifted = base + [9.0] * 5
    e = ewma(drifted, alpha=0.5)
    # With α=0.5 the recent 9.0s pull the EWMA above 7.
    assert e > 7.0


def test_cusum_detects_persistent_positive_shift():
    from app.services.carousel_v2.drift_detector import cusum

    pos, neg = cusum([6.0] * 10, target=5.0)
    assert pos > 0
    assert neg <= 0


def test_cohen_kappa_perfect_agreement_is_one():
    from app.services.carousel_v2.golden_set_service import cohen_kappa_score

    h = [8, 7, 9, 4, 5]
    j = [8, 7, 9, 4, 5]
    assert cohen_kappa_score(h, j) == pytest.approx(1.0, abs=1e-6)


def test_cohen_kappa_random_agreement_near_zero():
    from app.services.carousel_v2.golden_set_service import cohen_kappa_score

    # Wildly different orderings.
    h = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    j = [10, 9, 8, 7, 6, 5, 4, 3, 2, 1]
    assert cohen_kappa_score(h, j) < 0.0  # negative when worse than chance


# ---------------------------------------------------------------------------
# exemplar_memory
# ---------------------------------------------------------------------------

def test_render_for_designer_includes_good_and_bad_blocks():
    from app.services.carousel_v2.exemplar_memory import render_for_designer

    pos = [{"composite": 9.1, "slides": [{"text": "Loki was always lying"}]}]
    neg = [{"composite": 4.0, "slides": [{"text": "He was nice"}], "failure_annotation": "boring"}]
    block = render_for_designer(pos, neg)
    assert "<good_example" in block
    assert "<bad_example" in block
    assert "boring" in block


def test_render_for_designer_empty_inputs_return_empty_string():
    from app.services.carousel_v2.exemplar_memory import render_for_designer

    assert render_for_designer([], []) == ""


# ---------------------------------------------------------------------------
# caption_service
# ---------------------------------------------------------------------------

def test_compose_hashtags_caps_at_nine_and_dedupes():
    from app.services.carousel_v2.caption_service import compose_hashtags

    tags = compose_hashtags(character="Homelander", franchise="The Boys", voice_key="the_boys")
    assert all(t.startswith("#") for t in tags)
    assert len(tags) <= 9
    assert len({t.lower() for t in tags}) == len(tags)  # no dupes
    # Character + franchise tokens included.
    assert any("homelander" in t.lower() for t in tags)


def test_compose_caption_under_2200_chars_and_includes_hook():
    from app.services.carousel_v2.caption_service import compose_caption

    cap = compose_caption(
        hook="Homelander wasn't supposed to be the villain",
        franchise="The Boys",
        character="Homelander",
        slide_summaries=["Vought engineered him", "Soldier Boy never knew", "Becca paid the price"],
        voice_key="the_boys",
    )
    assert "Homelander wasn't supposed to be the villain" in cap
    assert "👇" in cap
    assert len(cap) <= 2200


# ---------------------------------------------------------------------------
# idempotency
# ---------------------------------------------------------------------------

def test_idempotency_key_stable_under_image_order():
    from app.services.carousel_v2.idempotency import make_key

    a = make_key(carousel_id="c1", image_hashes=["sha-a", "sha-b", "sha-c"], caption="hi")
    b = make_key(carousel_id="c1", image_hashes=["sha-c", "sha-a", "sha-b"], caption="hi")
    assert a == b


def test_idempotency_key_changes_with_caption():
    from app.services.carousel_v2.idempotency import make_key

    a = make_key(carousel_id="c1", image_hashes=["x"], caption="hi")
    b = make_key(carousel_id="c1", image_hashes=["x"], caption="hi!")
    assert a != b


# ---------------------------------------------------------------------------
# image_scorer composite math
# ---------------------------------------------------------------------------

def test_phash_dedup_collapses_near_duplicates():
    from app.services.carousel_v2 import gpu_funnel  # noqa: F401  (ensures package loads)
    from app.services.image_scorer_service import ScoredCandidate, _phash_dedup
    from app.services.image_sources.types import CandidateImage

    def _sc(phash: str, src: str = "tmdb") -> ScoredCandidate:
        return ScoredCandidate(
            cand=CandidateImage(source=src, source_url=f"https://i/{phash}.jpg"),
            sha256="",
            phash=phash,
            kept=True,
        )

    items = [_sc("0000000000000000"), _sc("0000000000000001"), _sc("ffffffffffffffff")]
    survivors = _phash_dedup(items, threshold=6)
    assert len(survivors) == 2  # near-dupe collapsed


def test_composite_z_score_ranks_higher_aesthetic_higher():
    from app.services.image_scorer_service import ScoredCandidate, _composite
    from app.services.image_sources.types import CandidateImage

    a = ScoredCandidate(
        cand=CandidateImage(source="tmdb", source_url="https://i/a"),
        sha256="a",
        width=2048, height=1152,
        aesthetic_v2=9.0, clip_relevance=0.9, face_cosine=0.8,
        maniqa=0.9, vlm_likeness=0.95, aspect_match=True,
    )
    b = ScoredCandidate(
        cand=CandidateImage(source="tmdb", source_url="https://i/b"),
        sha256="b",
        width=2048, height=1152,
        aesthetic_v2=2.0, clip_relevance=0.2, face_cosine=0.1,
        maniqa=0.2, vlm_likeness=0.1, aspect_match=True,
    )
    _composite([a, b])
    assert a.composite_z is not None and b.composite_z is not None
    assert a.composite_z > b.composite_z


def test_composite_z_penalises_watermark():
    from app.services.image_scorer_service import ScoredCandidate, _composite
    from app.services.image_sources.types import CandidateImage

    clean = ScoredCandidate(
        cand=CandidateImage(source="tmdb", source_url="https://i/c"),
        sha256="c", width=1080, height=1920,
        aesthetic_v2=7.0, clip_relevance=0.8, face_cosine=0.6,
        maniqa=0.7, vlm_likeness=0.7, aspect_match=True,
    )
    dirty = ScoredCandidate(
        cand=CandidateImage(source="tmdb", source_url="https://i/d"),
        sha256="d", width=1080, height=1920,
        aesthetic_v2=7.0, clip_relevance=0.8, face_cosine=0.6,
        maniqa=0.7, vlm_likeness=0.7, aspect_match=True,
        watermark_flag=True,
    )
    _composite([clean, dirty])
    assert clean.composite_z > dirty.composite_z


# ---------------------------------------------------------------------------
# cinematic_pass — no Pillow / numpy is the default test environment;
# the function must return the original bytes intact.
# ---------------------------------------------------------------------------

def test_cinematic_pass_no_pillow_returns_original_bytes(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def _block_pil(name, *a, **kw):
        if name == "PIL" or name.startswith("PIL."):
            raise ImportError("PIL blocked for test")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", _block_pil)

    from app.services.carousel_v2.brand_kit_service import get_brand_kit
    from app.services.carousel_v2.cinematic_pass import apply_cinematic_pass

    body = b"fake-jpeg-bytes"
    out = apply_cinematic_pass(body, brand_kit=get_brand_kit("mcu"))
    assert out == body


# ---------------------------------------------------------------------------
# bandit_service composite reward
# ---------------------------------------------------------------------------

def test_composite_reward_weighted_sum():
    from app.services.carousel_v2.bandit_service import composite_reward

    r = composite_reward(
        completion_rate=1.0,
        saves_per_view=1.0,
        shares_per_view=1.0,
        comments_per_view=1.0,
        follows_per_view=1.0,
        likes_per_view=1.0,
    )
    # All-1 inputs sum to 1.0 by construction (weights total to 1.0).
    assert pytest.approx(r, rel=1e-6) == 1.0


def test_composite_reward_z_scores_when_cohort_provided():
    from app.services.carousel_v2.bandit_service import composite_reward

    r = composite_reward(
        completion_rate=2.0,
        cohort_stats={"completion_rate": (1.0, 0.5)},  # mean=1, sd=0.5 → z=2
    )
    # Only completion_rate provided + non-zero, weight 0.4 → 0.8
    assert pytest.approx(r, rel=1e-6) == 2.0 * 0.4
