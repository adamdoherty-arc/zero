from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks

from app.services.content_production_control_service import (
    AFFECTED_JOB_IDS,
    ContentProductionControlService,
    ContentProductionPolicy,
)


def test_content_production_policy_defaults_to_paused():
    policy = ContentProductionPolicy()

    assert policy.paused is True
    assert "hard freeze" in policy.reason
    assert policy.affected_job_ids == list(AFFECTED_JOB_IDS)


@pytest.mark.asyncio
async def test_content_production_captures_scheduler_states(monkeypatch):
    service = ContentProductionControlService()

    async def snapshot():
        return [
            {"id": "media_auto_research", "enabled": True},
            {"id": "character_content_generation", "enabled": False},
        ]

    monkeypatch.setattr(service, "_scheduler_jobs_snapshot", snapshot)

    states = await service._capture_job_states()

    assert states["media_auto_research"] is True
    assert states["character_content_generation"] is False
    assert set(states) == set(AFFECTED_JOB_IDS)


def test_content_production_restore_previous_states_or_all_enabled():
    service = ContentProductionControlService()
    policy = ContentProductionPolicy(
        previous_job_states={
            "media_auto_research": False,
            "character_content_generation": True,
        }
    )

    restored = service._restore_states_from_policy(policy, True)
    enabled = service._restore_states_from_policy(policy, False)

    assert restored["media_auto_research"] is False
    assert restored["character_content_generation"] is True
    assert all(enabled.values())


@pytest.mark.asyncio
async def test_content_production_middleware_blocks_writes_and_allows_reads(monkeypatch):
    from httpx import ASGITransport, AsyncClient

    from app.main import app
    import app.routers.character_content as character_router
    import app.services.content_production_control_service as control_module

    monkeypatch.setenv("ZERO_GATEWAY_TOKEN", "test-token")

    class FakeControl:
        async def get_policy(self):
            return ContentProductionPolicy(reason="test freeze")

    class FakeCharacterService:
        async def get_stats(self):
            return {
                "total_characters": 0,
                "characters_researched": 0,
                "total_carousels": 0,
                "carousels_by_status": {},
                "total_published": 0,
                "total_views": 0,
                "total_likes": 0,
                "avg_engagement_rate": 0,
                "top_characters": [],
                "top_angles": [],
            }

    monkeypatch.setattr(
        control_module,
        "get_content_production_control_service",
        lambda: FakeControl(),
    )
    monkeypatch.setattr(
        character_router,
        "get_character_content_service",
        lambda: FakeCharacterService(),
    )

    headers = {"Authorization": "Bearer test-token"}
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        blocked = await client.post(
            "/api/characters/batch-smart",
            json={"count": 1},
            headers=headers,
        )
        read_only = await client.get("/api/characters/stats", headers=headers)

    assert blocked.status_code == 423
    assert blocked.json()["error"]["details"]["paused"] is True
    assert read_only.status_code == 200


@pytest.mark.asyncio
async def test_paused_image_candidate_read_does_not_enqueue_discovery(monkeypatch):
    import app.routers.character_content as character_router
    import app.services.content_production_control_service as control_module

    class FakeCharacterService:
        async def list_slide_image_candidates(self, carousel_id, slide_index, limit=20):
            return {
                "character_id": "character-1",
                "needs_discover": True,
                "candidates": [
                    {
                        "id": "image-1",
                        "url": "https://example.test/image.jpg",
                        "quality_score": 0.8,
                    }
                ],
            }

        async def discover_more_character_images(self, character_id):
            raise AssertionError("background discovery should not be scheduled")

    class FakeControl:
        async def is_paused(self):
            return True

    monkeypatch.setattr(
        character_router,
        "get_character_content_service",
        lambda: FakeCharacterService(),
    )
    monkeypatch.setattr(
        control_module,
        "get_content_production_control_service",
        lambda: FakeControl(),
    )

    background_tasks = BackgroundTasks()
    response = await character_router.list_slide_image_candidates(
        "carousel-1",
        0,
        background_tasks,
    )

    assert len(response) == 1
    assert background_tasks.tasks == []
