"""
`email_to_tasks` must not re-file the same action items every day.

Nothing marks the source messages read, so each daily run saw the identical
unread inbox, paid for an LLM extraction per message, and created the same tasks
again in a fresh sprint. By 2026-08-06 that had produced three sprints holding 23
tasks, of which "Re-request access to demo@jhu-wd-sandbox.edu" appeared five
times and the AI-Interviewer workflow review five more (Fix-163).

Two independent defences, because they fail differently: the processed-id set
stops the re-extraction (and its cost), and the title check stops a paraphrase of
an already-filed action from landing twice.
"""

import pytest

from app.services.legion_integration_service import LegionIntegrationService


class _FakeLegion:
    def __init__(self, existing=()):
        self._existing = [{"title": t} for t in existing]
        self.created = []

    async def list_tasks(self, sprint_id, **kw):
        return list(self._existing)

    async def create_task(self, sprint_id, task_data):
        self.created.append(task_data["title"])
        self._existing.append({"title": task_data["title"]})
        return {"id": len(self.created)}


@pytest.mark.asyncio
async def test_existing_titles_are_normalised():
    svc = LegionIntegrationService()
    legion = _FakeLegion(["[Email]  Re-Request   ACCESS ", "[Email] Review burn report"])

    titles = await svc._existing_task_titles(legion, 1)

    assert "[email] re-request access" in titles
    assert "[email] review burn report" in titles


@pytest.mark.asyncio
async def test_existing_titles_survives_a_failing_client():
    """A Legion blip must not silently disable duplicate suppression's caller."""

    class _Broken:
        async def list_tasks(self, sprint_id, **kw):
            raise RuntimeError("legion down")

    svc = LegionIntegrationService()
    assert await svc._existing_task_titles(_Broken(), 1) == set()


@pytest.mark.asyncio
async def test_processed_ids_round_trip(monkeypatch):
    """Ids persist across runs, newest wins, and the set stays bounded."""
    store = {}

    async def fake_load(self):
        return set(store.get("ids", []))

    async def fake_save(self, previous, newly):
        merged = [e for e in previous if e not in set(newly)] + list(newly)
        store["ids"] = merged[-self._PROCESSED_EMAIL_MEMORY :]

    monkeypatch.setattr(LegionIntegrationService, "_load_processed_email_ids", fake_load)
    monkeypatch.setattr(LegionIntegrationService, "_save_processed_email_ids", fake_save)

    svc = LegionIntegrationService()
    await svc._save_processed_email_ids(set(), ["m1", "m2"])
    assert await svc._load_processed_email_ids() == {"m1", "m2"}

    await svc._save_processed_email_ids({"m1", "m2"}, ["m3"])
    assert await svc._load_processed_email_ids() == {"m1", "m2", "m3"}


@pytest.mark.asyncio
async def test_processed_set_is_bounded():
    svc = LegionIntegrationService()
    limit = svc._PROCESSED_EMAIL_MEMORY
    previous = {f"old{i}" for i in range(limit)}
    merged = [e for e in previous if e not in {"new"}] + ["new"]
    trimmed = merged[-limit:]

    assert len(trimmed) == limit
    assert "new" in trimmed, "the newest id must survive the trim"
