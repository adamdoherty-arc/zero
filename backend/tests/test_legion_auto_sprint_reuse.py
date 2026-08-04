"""
Auto-created Legion containers must be reused, not re-filed daily.

`_get_or_create_sprint` asked `get_current_sprint`, which matches only
status="active". The containers it creates are filed "planned" and never
started, so the lookup missed on every run and a new "<title> - <date>" sprint
was opened each day. Four had accumulated for project 7 by 2026-08-04 with
nothing bounding the growth.
"""

import pytest

from app.services.legion_integration_service import LegionIntegrationService


class _FakeLegion:
    def __init__(self, planned=None):
        self._planned = planned or []
        self.created = []

    async def get_current_sprint(self, project_id):
        return None

    async def list_sprints(self, project_id=None, status=None, limit=None):
        return list(self._planned) if status == "planned" else []

    async def create_sprint(self, data):
        self.created.append(data)
        return {"id": 999, "name": "new"}


@pytest.mark.asyncio
async def test_reuses_the_newest_matching_open_container():
    legion = _FakeLegion([
        {"id": 13277, "name": "Plan-148: Auto: Email Action Items - 2026-08-01"},
        {"id": 13303, "name": "Plan-152: Auto: Email Action Items - 2026-08-03"},
        {"id": 13293, "name": "Plan-150: Auto: Email Action Items - 2026-08-02"},
    ])
    svc = LegionIntegrationService()

    got = await svc._get_or_create_sprint(legion, 7, "Plan", "Auto: Email Action Items")

    assert got["id"] == 13303, "must reuse the most recent matching container"
    assert legion.created == [], "must not open another container"


@pytest.mark.asyncio
async def test_does_not_reuse_a_different_kind_of_container():
    legion = _FakeLegion([
        {"id": 13275, "name": "Enhancement-122: Auto: Enhancement Signals - 2026-08-01"},
    ])
    svc = LegionIntegrationService()

    await svc._get_or_create_sprint(legion, 7, "Plan", "Auto: Email Action Items")

    assert len(legion.created) == 1, "a non-matching container must not be hijacked"
    assert legion.created[0]["category"] == "Plan"


@pytest.mark.asyncio
async def test_creates_a_container_when_none_is_open():
    legion = _FakeLegion([])
    svc = LegionIntegrationService()

    await svc._get_or_create_sprint(legion, 7, "Plan", "Auto: Email Action Items")

    assert len(legion.created) == 1
    assert legion.created[0]["source_system"] == "zero_legion_integration"
