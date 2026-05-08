"""Coverage for the second half of the carousel V2 pipeline activities:

  skeptic.skeptic_review
  reflexion.judge_and_reflect
  render.render_slides
  publish.request_human_review
  publish.publish_to_tiktok
  analytics.schedule_polls
  legacy.legacy_generate
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

# pytest-asyncio mode=auto (pytest.ini) auto-detects async tests.


@pytest.fixture
def designed_ctx(workflow_ctx):
    """A workflow context that has reached the design stage."""
    workflow_ctx["slides"] = [
        {
            "slide_num": 1,
            "role": "hook",
            "text": "Homelander wasn't supposed to be the villain",
            "transition_to_next": "but here's why...",
            "cited_fact_ids": [],
            "template": "hook",
        },
        {
            "slide_num": 2,
            "role": "build",
            "text": "Vought engineered him from infancy [fact_id:abc123]",
            "transition_to_next": "and that's just the start",
            "cited_fact_ids": ["abc123"],
            "template": "fact",
        },
    ]
    workflow_ctx["chosen_hook"] = workflow_ctx["slides"][0]["text"]
    return workflow_ctx


# ---------------------------------------------------------------------------
# skeptic_review
# ---------------------------------------------------------------------------

async def test_skeptic_review_keeps_supported_claims(designed_ctx, stub_unified_client, monkeypatch):
    from app.workflows.activities.skeptic import skeptic_review

    async def _lookup(_ids):
        return []

    monkeypatch.setattr("app.services.carousel_v2.atomic_facts_service.lookup_ids", _lookup)

    out = await skeptic_review(designed_ctx)
    counts = out["skeptic_counts"]
    assert counts["keep"] >= 1
    assert counts["kill"] == 0
    assert "skeptic_verdicts" in out
    assert isinstance(out["skeptic_verdicts"], list)


async def test_skeptic_review_drops_killed_slides(designed_ctx, monkeypatch):
    """When the LLM returns a KILL verdict for a claim, the slide must be
    removed from the slides list.
    """
    from app.workflows.activities import skeptic as skeptic_act

    class _Stub:
        async def structured_chat(self, prompt, **kw):
            return [
                {
                    "claim": "Homelander wasn't supposed to be the villain",
                    "verdict": "KEEP",
                    "trap_category": None,
                    "supporting_quote": None,
                    "rewrite_suggestion": None,
                },
                {
                    "claim": "Vought engineered him from infancy [fact_id:abc123]",
                    "verdict": "KILL",
                    "trap_category": "fan_theory",
                    "supporting_quote": None,
                    "rewrite_suggestion": None,
                },
            ]

    monkeypatch.setattr(
        "app.infrastructure.unified_llm_client.UnifiedLLMClient", lambda: _Stub()
    )

    async def _lookup(_ids):
        return []

    monkeypatch.setattr("app.services.carousel_v2.atomic_facts_service.lookup_ids", _lookup)

    out = await skeptic_act.skeptic_review(designed_ctx)
    assert out["skeptic_counts"]["kill"] == 1
    # Slide 2 was killed.
    assert len(out["slides"]) == 1
    assert out["slides"][0]["slide_num"] == 1


async def test_skeptic_review_handles_empty_slides(workflow_ctx):
    from app.workflows.activities.skeptic import skeptic_review

    workflow_ctx["slides"] = []
    out = await skeptic_review(workflow_ctx)
    assert out["skeptic_verdicts"] == []
    assert out["skeptic_counts"] == {"keep": 0, "rewrite": 0, "kill": 0}


# ---------------------------------------------------------------------------
# judge_and_reflect
# ---------------------------------------------------------------------------

async def test_judge_and_reflect_passes_when_composite_high(designed_ctx, monkeypatch):
    from app.workflows.activities import reflexion as reflexion_act
    from app.models.carousel import (
        CarouselRubric,
        JudgeAxisScore,
        JudgeName,
        RubricAxis,
    )

    async def _score_carousel(carousel, *, samples_per_judge=3):
        per_axis = [
            JudgeAxisScore(judge=JudgeName.KIMI_K2_6, axis=RubricAxis.FACT_ACCURACY, score=9.0),
            JudgeAxisScore(judge=JudgeName.MINIMAX_M2_7, axis=RubricAxis.HOOK_STRENGTH, score=9.5),
            JudgeAxisScore(judge=JudgeName.QWEN3_32B_LOCAL, axis=RubricAxis.NOVELTY, score=8.0),
        ]
        return CarouselRubric(
            per_axis_per_judge=per_axis,
            aggregated={a.axis: a.score for a in per_axis},
            composite=9.0,
            passes_auto_publish=True,
            voice_floor_met=True,
            novelty_floor_met=True,
        )

    async def _persist(**_kw):
        return None

    monkeypatch.setattr(
        "app.services.carousel_v2.judge_panel_service.score_carousel", _score_carousel
    )
    monkeypatch.setattr(
        "app.services.carousel_v2.judge_panel_service.persist_rubric", _persist
    )

    result = await reflexion_act.judge_and_reflect(designed_ctx)
    assert result["passes"] is True
    assert result["context"]["composite_score"] == 9.0
    assert result["context"]["auto_approved"] is True


async def test_judge_and_reflect_appends_reflection_on_failure(designed_ctx, monkeypatch):
    from app.workflows.activities import reflexion as reflexion_act
    from app.models.carousel import (
        CarouselRubric,
        JudgeAxisScore,
        JudgeName,
        RubricAxis,
    )

    async def _score_carousel(carousel, *, samples_per_judge=3):
        per_axis = [
            JudgeAxisScore(
                judge=JudgeName.KIMI_K2_6,
                axis=RubricAxis.FACT_ACCURACY,
                score=4.0,
                rationale="Multiple uncited claims",
            ),
            JudgeAxisScore(
                judge=JudgeName.MINIMAX_M2_7,
                axis=RubricAxis.HOOK_STRENGTH,
                score=5.0,
                rationale="Hook too generic",
            ),
        ]
        return CarouselRubric(
            per_axis_per_judge=per_axis,
            aggregated={a.axis: a.score for a in per_axis},
            composite=5.0,
            passes_auto_publish=False,
        )

    async def _persist(**_kw):
        return None

    monkeypatch.setattr(
        "app.services.carousel_v2.judge_panel_service.score_carousel", _score_carousel
    )
    monkeypatch.setattr(
        "app.services.carousel_v2.judge_panel_service.persist_rubric", _persist
    )

    result = await reflexion_act.judge_and_reflect(designed_ctx)
    assert result["passes"] is False
    assert result["context"]["revision_count"] == 1
    assert result["context"]["reflections"], "reflections should be populated on failure"


async def test_judge_and_reflect_returns_zero_for_empty_slides(workflow_ctx):
    from app.workflows.activities.reflexion import judge_and_reflect

    workflow_ctx["slides"] = []
    result = await judge_and_reflect(workflow_ctx)
    assert result["passes"] is False
    assert result["context"]["composite_score"] == 0.0


# ---------------------------------------------------------------------------
# render.render_slides
# ---------------------------------------------------------------------------

async def test_render_slides_uploads_and_collects_urls(designed_ctx, monkeypatch):
    from app.workflows.activities import render as render_act

    designed_ctx["scored_images"] = [
        {"kept": True, "rank": 0, "source_url": "https://img/top.jpg"},
        {"kept": True, "rank": 1, "source_url": "https://img/second.jpg"},
    ]

    async def _render_concurrent(slides, *, brand_kit_key, max_concurrent=4):
        return [b"jpeg-bytes-1", b"jpeg-bytes-2"]

    async def _upload(*, body, key, content_type="image/jpeg"):
        return f"https://r2.example.com/{key}"

    monkeypatch.setattr(
        "app.services.carousel_v2.playwright_renderer.render_slides_concurrent",
        _render_concurrent,
    )
    monkeypatch.setattr(
        "app.services.carousel_v2.r2_uploader.upload_image", _upload
    )

    out = await render_act.render_slides(designed_ctx)
    assert len(out["rendered_image_urls"]) == 2
    assert all(u.startswith("https://r2.example.com/") for u in out["rendered_image_urls"])
    assert len(out["rendered_image_sha256"]) == 2


async def test_render_slides_handles_empty(workflow_ctx):
    from app.workflows.activities.render import render_slides

    workflow_ctx["slides"] = []
    out = await render_slides(workflow_ctx)
    assert out["rendered_image_urls"] == []


async def test_render_slides_continues_when_upload_fails(designed_ctx, monkeypatch):
    from app.workflows.activities import render as render_act

    designed_ctx["scored_images"] = [{"kept": True, "rank": 0, "source_url": "https://img/x.jpg"}]

    async def _render_concurrent(slides, **_kw):
        return [b"slide1", b"slide2"]

    calls = {"n": 0}

    async def _upload(*, body, key, content_type="image/jpeg"):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("R2 down")
        return "https://r2/recovered.jpg"

    monkeypatch.setattr(
        "app.services.carousel_v2.playwright_renderer.render_slides_concurrent",
        _render_concurrent,
    )
    monkeypatch.setattr(
        "app.services.carousel_v2.r2_uploader.upload_image", _upload
    )

    out = await render_act.render_slides(designed_ctx)
    # First failed, second succeeded → exactly one URL.
    assert len(out["rendered_image_urls"]) == 1


# ---------------------------------------------------------------------------
# publish.request_human_review
# ---------------------------------------------------------------------------

async def test_request_human_review_no_webhook_is_silent(designed_ctx, monkeypatch):
    from app.workflows.activities.publish import request_human_review

    monkeypatch.delenv("DISCORD_NOTIFICATION_WEBHOOK_URL", raising=False)
    designed_ctx["composite_score"] = 7.2
    designed_ctx["rendered_image_urls"] = ["https://r2/a.jpg"]
    # Should not raise, should not call out.
    await request_human_review(designed_ctx)


async def test_request_human_review_posts_to_discord_when_configured(designed_ctx, monkeypatch):
    from app.workflows.activities import publish as publish_act

    monkeypatch.setenv("DISCORD_NOTIFICATION_WEBHOOK_URL", "https://discord.test/webhook")
    designed_ctx["composite_score"] = 7.5
    designed_ctx["rendered_image_urls"] = ["https://r2/a.jpg", "https://r2/b.jpg"]

    posted = {}

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return None

        async def post(self, url, json=None, **_kw):
            posted["url"] = url
            posted["body"] = json
            class _R:
                status_code = 204

            return _R()

    monkeypatch.setattr("httpx.AsyncClient", lambda *_a, **_kw: _FakeClient())

    await publish_act.request_human_review(designed_ctx)
    assert posted["url"].startswith("https://discord.test")
    assert "Homelander" in posted["body"]["content"]


# ---------------------------------------------------------------------------
# publish.publish_to_tiktok
# ---------------------------------------------------------------------------

async def test_publish_dry_run_records_idempotency(designed_ctx, monkeypatch):
    from app.workflows.activities import publish as publish_act

    designed_ctx["rendered_image_urls"] = ["https://r2/a.jpg"]
    designed_ctx["rendered_image_sha256"] = ["sha-a"]

    monkeypatch.setenv("ZERO_TIKTOK_DRY_RUN", "true")

    async def _lookup(_key):
        return None

    recorded = {}

    async def _record(key, **kw):
        recorded["key"] = key
        recorded.update(kw)

    monkeypatch.setattr("app.services.carousel_v2.idempotency.lookup", _lookup)
    monkeypatch.setattr("app.services.carousel_v2.idempotency.record", _record)

    out = await publish_act.publish_to_tiktok(designed_ctx)
    assert out["dry_run"] is True
    assert out["publish_id"].startswith("dryrun-")
    assert recorded["publish_id"] == out["publish_id"]


async def test_publish_returns_cached_publish_id_on_replay(designed_ctx, monkeypatch):
    from app.workflows.activities import publish as publish_act

    designed_ctx["rendered_image_urls"] = ["https://r2/a.jpg"]
    designed_ctx["rendered_image_sha256"] = ["sha-a"]

    async def _lookup(_key):
        return {"publish_id": "tt-cached-123", "response_payload": {"publish_url": "https://tt/v/x"}}

    async def _record(*_a, **_kw):
        raise AssertionError("record must not be called on idempotent replay")

    monkeypatch.setattr("app.services.carousel_v2.idempotency.lookup", _lookup)
    monkeypatch.setattr("app.services.carousel_v2.idempotency.record", _record)

    out = await publish_act.publish_to_tiktok(designed_ctx)
    assert out["publish_id"] == "tt-cached-123"
    assert out["idempotent_replay"] is True


# ---------------------------------------------------------------------------
# analytics.schedule_polls
# ---------------------------------------------------------------------------

async def test_schedule_polls_seeds_engagement_row(monkeypatch, stub_db):
    from app.workflows.activities.analytics import schedule_polls

    await schedule_polls({
        "publish_id": "tt-456",
        "generation_id": "gen-test-1",
        "carousel_id": "c-test",
    })
    assert len(stub_db.added) == 1
    seed = stub_db.added[0]
    assert seed.publish_id == "tt-456"
    assert seed.t_offset_h == 0
    assert seed.source == "schedule_seed"


async def test_schedule_polls_skips_when_no_publish_id(monkeypatch, stub_db):
    from app.workflows.activities.analytics import schedule_polls

    await schedule_polls({"publish_id": None, "generation_id": "gen-x"})
    assert stub_db.added == []


# ---------------------------------------------------------------------------
# legacy.legacy_generate
# ---------------------------------------------------------------------------

async def test_legacy_generate_short_circuits_without_character_id():
    from app.models.carousel import CarouselGenerationStatus, CarouselWorkflowInput
    from app.workflows.activities.legacy import legacy_generate

    payload = CarouselWorkflowInput(topic="Loki", franchise="mcu")  # no character_id
    result = await legacy_generate(payload)
    assert result.status == CarouselGenerationStatus.FAILED
    assert "character_id required" in (result.error or "")


async def test_legacy_generate_calls_existing_service_when_character_id_present(monkeypatch):
    from app.models.carousel import CarouselGenerationStatus, CarouselWorkflowInput
    from app.workflows.activities import legacy as legacy_mod

    class _FakeCarousel:
        id = "c-legacy-1"
        ai_review_score = 8.2

    class _FakeService:
        async def generate_carousel(self, _data):
            return _FakeCarousel()

    import sys, types
    fake_module = types.ModuleType("app.services.character_content_service")
    fake_module.CharacterContentService = lambda: _FakeService()
    monkeypatch.setitem(sys.modules, "app.services.character_content_service", fake_module)

    fake_models = types.ModuleType("app.models.character_content")

    class _CarouselCreate:
        def __init__(self, **kw):
            for k, v in kw.items():
                setattr(self, k, v)

    fake_models.CarouselCreate = _CarouselCreate
    monkeypatch.setitem(sys.modules, "app.models.character_content", fake_models)

    payload = CarouselWorkflowInput(topic="Loki", franchise="mcu", character_id="char-x")
    result = await legacy_mod.legacy_generate(payload)
    assert result.status == CarouselGenerationStatus.AWAITING_REVIEW
    assert result.composite_score == 8.2
    assert result.carousel_id == "c-legacy-1"
