"""Coverage for the carousel_generations row lifecycle.

The Temporal activities call ``generation_state.upsert_state`` at every stage
boundary so post-hoc queries (drift, golden set, exemplar memory, bandit
reward attribution) can join on ``generation_id`` without orphans. The
helper must be:

  - failure-soft when the DB isn't initialised (unit-test env)
  - idempotent on ``generation_id`` (insert on first call, update afterwards)
  - selective in its UPDATE (None values must NOT clobber existing fields)
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest


# pytest-asyncio mode=auto


async def test_upsert_state_no_db_does_not_raise(monkeypatch):
    """When the DB isn't initialised the helper logs a warning and returns
    cleanly. The workflow must never abort because the V2 schema is missing
    in a dev environment.
    """
    from app.services.carousel_v2 import generation_state

    # The default env raises ``Database not initialised`` from get_session.
    # We rely on the helper's outer try/except — it must log and return.
    await generation_state.upsert_state("gen-noop", topic="x", status="researching")
    # No exception raised → pass.


async def test_upsert_state_inserts_when_missing(monkeypatch):
    from app.services.carousel_v2 import generation_state

    captured = {}

    class _Result:
        def scalar_one_or_none(self): return None

    class _Session:
        async def execute(self, *_a, **_kw): return _Result()
        async def flush(self): captured["flushed"] = True
        def add(self, row): captured["row"] = row

    @asynccontextmanager
    async def _gs():
        yield _Session()

    monkeypatch.setattr(generation_state, "get_session", _gs)

    await generation_state.upsert_state(
        "gen-new",
        topic="Loki",
        franchise="mcu",
        prompt_version_id="pv-1",
        status="researching",
    )
    row = captured["row"]
    assert row.id == "gen-new"
    assert row.topic == "Loki"
    assert row.franchise == "mcu"
    assert row.prompt_version_id == "pv-1"
    assert row.status == "researching"
    assert captured["flushed"]


async def test_upsert_state_updates_when_existing_and_skips_none_fields(monkeypatch):
    """Verifies the partial-update semantics — passing only a few fields must
    not wipe the rest.
    """
    from app.services.carousel_v2 import generation_state
    from app.db.models import CarouselGenerationModel

    existing = CarouselGenerationModel(
        id="gen-existing",
        topic="Loki",
        franchise="mcu",
        slides_json=[{"slide_num": 1, "text": "Original hook"}],
        composite_score=6.5,
        revision_count=1,
        status="researching",
    )

    class _Result:
        def scalar_one_or_none(self): return existing

    class _Session:
        async def execute(self, *_a, **_kw): return _Result()
        async def flush(self): return None
        def add(self, _): raise AssertionError("must not insert when row exists")

    @asynccontextmanager
    async def _gs():
        yield _Session()

    monkeypatch.setattr(generation_state, "get_session", _gs)

    # Caller passes only composite_score + status — original topic/slides
    # must remain.
    await generation_state.upsert_state(
        "gen-existing",
        composite_score=8.5,
        status="awaiting_review",
    )
    assert existing.composite_score == 8.5
    assert existing.status == "awaiting_review"
    assert existing.topic == "Loki"
    assert existing.slides_json == [{"slide_num": 1, "text": "Original hook"}]
    assert existing.revision_count == 1


async def test_topic_activity_writes_initial_state(monkeypatch):
    from app.models.carousel import CarouselWorkflowInput
    from app.workflows.activities.topic import select_topic
    import app.services.carousel_v2.generation_state as gs

    captured = {}

    async def _fake_upsert(generation_id, **fields):
        captured["generation_id"] = generation_id
        captured["fields"] = fields

    monkeypatch.setattr(gs, "upsert_state", _fake_upsert)

    payload = CarouselWorkflowInput(topic="Loki", franchise="mcu", character_id="c-1")
    out = await select_topic(payload)
    assert captured["generation_id"] == out["generation_id"]
    assert captured["fields"]["topic"] == "Loki"
    assert captured["fields"]["franchise"] == "mcu"
    assert captured["fields"]["character_id"] == "c-1"
    assert captured["fields"]["status"] == "researching"


async def test_publish_activity_stamps_published_at(monkeypatch, designed_ctx):
    """publish_to_tiktok must call upsert_state with the publish metadata
    so post-hoc engagement queries can join on the row.
    """
    from app.workflows.activities import publish as publish_act
    import app.services.carousel_v2.generation_state as gs

    designed_ctx["rendered_image_urls"] = ["https://r2/a.jpg"]
    designed_ctx["rendered_image_sha256"] = ["sha-a"]

    monkeypatch.setenv("ZERO_TIKTOK_DRY_RUN", "true")

    async def _idemp_lookup(_k): return None
    async def _idemp_record(*_a, **_kw): return None

    monkeypatch.setattr("app.services.carousel_v2.idempotency.lookup", _idemp_lookup)
    monkeypatch.setattr("app.services.carousel_v2.idempotency.record", _idemp_record)

    captured = {}

    async def _fake_upsert(generation_id, **fields):
        captured["fields"] = fields

    monkeypatch.setattr(gs, "upsert_state", _fake_upsert)

    out = await publish_act.publish_to_tiktok(designed_ctx)
    assert out["dry_run"] is True
    assert captured["fields"]["status"] in ("publishing", "published")
    assert captured["fields"]["engagement_metrics_json"]["image_count"] == 1
    assert captured["fields"]["published_at"] is not None


@pytest.fixture
def designed_ctx(workflow_ctx):
    """Same shape as test_activities_stages_6_to_11.designed_ctx — avoid a
    shared-fixture import dance.
    """
    workflow_ctx["slides"] = [
        {"slide_num": 1, "role": "hook", "text": "Hook line",
         "transition_to_next": None, "cited_fact_ids": [], "template": "hook"},
    ]
    workflow_ctx["chosen_hook"] = workflow_ctx["slides"][0]["text"]
    return workflow_ctx
