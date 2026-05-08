"""Coverage for the first half of the carousel V2 pipeline activities:

  topic.select_topic
  research.research
  curate_images.curate_images
  score_images.score_images
  design.design_carousel
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

# pytest-asyncio runs in mode=auto (see pytest.ini); async functions are
# auto-detected. No module-level pytestmark needed.


# ---------------------------------------------------------------------------
# select_topic
# ---------------------------------------------------------------------------

async def test_select_topic_seeds_generation_id_and_status():
    from app.models.carousel import CarouselWorkflowInput
    from app.workflows.activities.topic import select_topic

    payload = CarouselWorkflowInput(
        topic="Homelander", franchise="the_boys", slide_count=8, auto_publish=True
    )
    out = await select_topic(payload)

    assert out["generation_id"]
    assert len(out["generation_id"]) == 32  # uuid4 hex
    assert out["topic"] == "Homelander"
    assert out["franchise"] == "the_boys"
    assert out["status"] == "researching"
    assert out["auto_publish"] is True
    assert out["novelty_ok"] is True


async def test_select_topic_returns_distinct_ids_per_call():
    from app.models.carousel import CarouselWorkflowInput
    from app.workflows.activities.topic import select_topic

    p = CarouselWorkflowInput(topic="Loki")
    a, b = await select_topic(p), await select_topic(p)
    assert a["generation_id"] != b["generation_id"]


# ---------------------------------------------------------------------------
# research.research
# ---------------------------------------------------------------------------

async def test_research_succeeds_when_legacy_sources_are_unavailable(workflow_ctx, monkeypatch):
    """If the legacy research module isn't importable, the activity must
    still succeed with an empty fact list.
    """
    import builtins
    real_import = builtins.__import__

    def _fail_research(name, *a, **kw):
        if name == "app.services.character_research_sources":
            raise ImportError("simulated missing module")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", _fail_research)

    from app.workflows.activities.research import research

    out = await research(workflow_ctx)
    assert out["atomic_fact_ids"] == []
    assert out["status"] == "researched"


async def test_research_persists_fragments_as_atomic_facts(workflow_ctx, monkeypatch):
    """When the legacy research returns fragments, the activity tier-tags
    each one and calls ``atomic_facts_service.upsert``.
    """
    import sys, types

    fake_research = types.ModuleType("app.services.character_research_sources")

    async def _gather(*, character, franchise=None):
        return [
            {"source": "fandom_wiki", "url": "https://x/marvel", "content": "Loki was Asgardian"},
            {"source": "imdb_trivia", "url": "https://imdb/tt1", "content": "Original cut had Loki survive"},
        ]

    fake_research.gather_research_fragments = _gather
    monkeypatch.setitem(sys.modules, "app.services.character_research_sources", fake_research)

    from app.workflows.activities import research as research_act
    from app.models.carousel import AtomicFact, Source, SourceKind, TrustTier

    upserted: list[AtomicFact] = []

    async def _fake_upsert(fact: AtomicFact) -> AtomicFact:
        upserted.append(fact)
        return fact

    monkeypatch.setattr(
        "app.services.carousel_v2.atomic_facts_service.upsert",
        _fake_upsert,
    )

    out = await research_act.research(workflow_ctx)
    assert len(upserted) == 2
    tiers = sorted(int(f.trust_tier) for f in upserted)
    assert tiers == [1, 2]  # fandom→1, imdb_trivia→2
    assert all(f.source.url.startswith("https://") for f in upserted)
    assert out["atomic_fact_ids"]
    assert out["status"] == "researched"


# ---------------------------------------------------------------------------
# curate_images
# ---------------------------------------------------------------------------

async def test_curate_images_populates_candidates(workflow_ctx, monkeypatch):
    from app.services.image_sources.types import CandidateImage
    from app.workflows.activities import curate_images as ci

    sample = [
        CandidateImage(source="tmdb", source_url="https://i/tmdb1.jpg", width=1920, height=1080),
        CandidateImage(source="fanart", source_url="https://i/fanart1.png", width=2048, height=1152),
    ]

    class _Curator:
        async def curate(self, query, **_kw):
            assert query.character == "Homelander"
            return sample

    # The activity imports get_image_curator lazily; patch the source module.
    import app.services.image_curator_service as curator_mod
    monkeypatch.setattr(curator_mod, "get_image_curator", lambda: _Curator())

    out = await ci.curate_images(workflow_ctx)
    assert len(out["image_candidates"]) == 2
    assert out["image_candidates"][0]["source"] == "tmdb"


async def test_curate_images_handles_empty_query_gracefully(workflow_ctx, monkeypatch):
    from app.workflows.activities import curate_images as ci
    import app.services.image_curator_service as curator_mod

    class _Curator:
        async def curate(self, *_a, **_kw):
            return []

    monkeypatch.setattr(curator_mod, "get_image_curator", lambda: _Curator())
    out = await ci.curate_images(workflow_ctx)
    assert out["image_candidates"] == []


# ---------------------------------------------------------------------------
# score_images
# ---------------------------------------------------------------------------

async def test_score_images_skips_when_no_candidates(workflow_ctx, monkeypatch):
    from app.workflows.activities import score_images as si

    workflow_ctx["image_candidates"] = []
    out = await si.score_images(workflow_ctx)
    assert out["scored_images"] == []


async def test_score_images_persists_image_score_rows(workflow_ctx, monkeypatch, stub_db):
    """``score_images`` must INSERT one ``image_scores`` row per candidate
    (kept + dropped) so Phase 6 weight recalibration can replay every funnel
    decision.
    """
    from app.models.carousel import ImageScore, ImageSourceKind
    from app.workflows.activities import score_images as si
    import app.services.image_scorer_service as scorer_mod

    workflow_ctx["image_candidates"] = [
        {"source": "tmdb", "source_url": "https://i/1.jpg"},
        {"source": "fanart", "source_url": "https://i/2.png"},
    ]

    class _Scorer:
        async def score(self, candidates, **kw):
            return [
                ImageScore(id="a", source=ImageSourceKind.TMDB,
                           source_url="https://i/1.jpg", composite_z=1.5,
                           rank=0, kept=True, aesthetic_v2=7.5),
                ImageScore(id="b", source=ImageSourceKind.FANART,
                           source_url="https://i/2.png", composite_z=-0.3,
                           rank=None, kept=False, drop_reason="below_top_k"),
            ]

    monkeypatch.setattr(scorer_mod, "get_image_scorer", lambda: _Scorer())

    out = await si.score_images(workflow_ctx)
    assert len(out["scored_images"]) == 2

    # Both candidates persisted to image_scores via stub_db.
    persisted = [r for r in stub_db.added if type(r).__name__ == "ImageScoreModel"]
    assert len(persisted) == 2
    sources = sorted(r.source for r in persisted)
    assert sources == ["fanart", "tmdb"]
    kept_flags = {r.source_url: r.kept for r in persisted}
    assert kept_flags["https://i/1.jpg"] is True
    assert kept_flags["https://i/2.png"] is False
    assert any(r.composite_z == 1.5 for r in persisted)


async def test_score_images_passes_through_to_scorer(workflow_ctx, monkeypatch):
    from app.models.carousel import ImageScore, ImageSourceKind
    from app.workflows.activities import score_images as si
    import app.services.image_scorer_service as scorer_mod

    workflow_ctx["image_candidates"] = [
        {"source": "tmdb", "source_url": "https://i/1.jpg"},
        {"source": "fanart", "source_url": "https://i/2.png"},
    ]

    class _Scorer:
        async def score(self, candidates, *, character, franchise=None, **kw):
            assert character == "Homelander"
            return [
                ImageScore(
                    id="abc",
                    source=ImageSourceKind.TMDB,
                    source_url="https://i/1.jpg",
                    composite_z=1.5,
                    rank=0,
                    kept=True,
                ),
                ImageScore(
                    id="def",
                    source=ImageSourceKind.FANART,
                    source_url="https://i/2.png",
                    composite_z=-0.3,
                    rank=None,
                    kept=False,
                    drop_reason="below_top_k",
                ),
            ]

    monkeypatch.setattr(scorer_mod, "get_image_scorer", lambda: _Scorer())

    out = await si.score_images(workflow_ctx)
    kept = [s for s in out["scored_images"] if s["kept"]]
    assert len(kept) == 1
    assert kept[0]["composite_z"] == 1.5


# ---------------------------------------------------------------------------
# design.design_carousel
# ---------------------------------------------------------------------------

async def test_design_carousel_uses_voice_prompt_and_picks_hook(workflow_ctx, stub_unified_client, monkeypatch):
    from app.workflows.activities.design import design_carousel

    # Avoid touching the DB for fact lookups.
    async def _lookup(_ids):
        return []

    monkeypatch.setattr("app.services.carousel_v2.atomic_facts_service.lookup_ids", _lookup)

    out = await design_carousel(workflow_ctx)
    assert out["chosen_hook"]
    assert "PROPERTY:" in (out["voice_prompt"] or "")
    assert isinstance(out["slides"], list)
    if out["slides"]:
        # Slide 1 always carries the hook verbatim.
        assert out["slides"][0]["text"] == out["chosen_hook"]
        assert out["slides"][0]["role"] == "hook"
    assert out["designer_prompt_id"]


async def test_design_carousel_survives_designer_call_failure(workflow_ctx, monkeypatch):
    from app.workflows.activities import design as design_mod

    class _BrokenClient:
        async def structured_chat(self, *_a, **_kw):
            raise RuntimeError("router down")

    monkeypatch.setattr(
        "app.infrastructure.unified_llm_client.UnifiedLLMClient",
        lambda: _BrokenClient(),
    )

    async def _lookup(_ids):
        return []

    monkeypatch.setattr("app.services.carousel_v2.atomic_facts_service.lookup_ids", _lookup)

    out = await design_mod.design_carousel(workflow_ctx)
    # Empty slides — but still returns a context, not raises.
    assert out["slides"] == []
    assert out["chosen_hook"]
