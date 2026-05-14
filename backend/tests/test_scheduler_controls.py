from datetime import datetime, timezone

import pytest

from app.services import email_voice_session_service
from app.services import scheduler_service as scheduler_module
from app.services.email_voice_session_service import EmailVoiceSessionService, _SessionContext
from app.services.scheduler_service import SchedulerService, get_default_job_enabled


async def _noop_job() -> None:
    return None


def _small_schedule() -> dict:
    return {
        "gmail_check": {
            "cron": "*/5 * * * *",
            "description": "Gmail sync",
            "enabled": True,
        },
        "reachy_email_nudge": {
            "cron": "*/5 * * * *",
            "description": "Zero email voice",
            "enabled": True,
        },
        "tiktok_niche_deep_dive": {
            "cron": "0 * * * *",
            "description": "TikTok niche deep dive",
            "enabled": True,
        },
    }


async def _started_service(monkeypatch, overrides: dict[str, bool] | None = None):
    monkeypatch.setattr(scheduler_module, "DAILY_SCHEDULE", _small_schedule())

    service = SchedulerService()
    saves: list[dict[str, bool]] = []

    async def load_overrides() -> dict[str, bool]:
        return dict(overrides or {})

    async def save_overrides() -> None:
        saves.append(dict(service._enabled_overrides))

    monkeypatch.setattr(service, "_load_enabled_overrides", load_overrides)
    monkeypatch.setattr(service, "_save_enabled_overrides", save_overrides)
    monkeypatch.setattr(service, "_get_handler", lambda _job_name: _noop_job)

    await service.start()
    return service, saves


@pytest.mark.asyncio
async def test_default_disabled_jobs_are_registered_and_paused(monkeypatch):
    service, _saves = await _started_service(monkeypatch)
    try:
        status = service.get_status()
        jobs = {job["id"]: job for job in status["jobs"]}

        assert jobs["gmail_check"]["registered"] is True
        assert jobs["gmail_check"]["enabled"] is True
        assert jobs["gmail_check"]["next_run"] is not None

        assert jobs["reachy_email_nudge"]["registered"] is True
        assert jobs["reachy_email_nudge"]["default_enabled"] is False
        assert jobs["reachy_email_nudge"]["enabled"] is False
        assert jobs["reachy_email_nudge"]["next_run"] is None

        assert jobs["tiktok_niche_deep_dive"]["registered"] is True
        assert jobs["tiktok_niche_deep_dive"]["default_enabled"] is False
        assert jobs["tiktok_niche_deep_dive"]["enabled"] is False
        assert jobs["tiktok_niche_deep_dive"]["next_run"] is None
    finally:
        await service.stop()


@pytest.mark.asyncio
async def test_persisted_override_can_enable_default_disabled_job_and_bulk_disable(monkeypatch):
    service, saves = await _started_service(monkeypatch, {"tiktok_niche_deep_dive": True})
    try:
        enabled_job = {job["id"]: job for job in service.get_status()["jobs"]}["tiktok_niche_deep_dive"]
        assert enabled_job["enabled"] is True
        assert enabled_job["next_run"] is not None

        result = await service.set_jobs_enabled(["tiktok_niche_deep_dive"], False)
        disabled_job = {job["id"]: job for job in service.get_status()["jobs"]}["tiktok_niche_deep_dive"]

        assert result["success"] is True
        assert result["count"] == 1
        assert disabled_job["enabled"] is False
        assert disabled_job["next_run"] is None
        assert saves[-1]["tiktok_niche_deep_dive"] is False
    finally:
        await service.stop()


@pytest.mark.asyncio
async def test_unknown_scheduler_job_returns_error_without_saving(monkeypatch):
    service, saves = await _started_service(monkeypatch)
    try:
        result = await service.set_job_enabled("missing_job", True)
        bulk = await service.set_jobs_enabled(["gmail_check", "missing_job"], False)

        assert result["success"] is False
        assert "Unknown job" in result["error"]
        assert bulk["success"] is False
        assert bulk["unknown_jobs"] == ["missing_job"]
        assert saves == []
    finally:
        await service.stop()


@pytest.mark.asyncio
async def test_disabling_reachy_email_nudge_clears_voice_session(monkeypatch):
    service, _saves = await _started_service(monkeypatch, {"reachy_email_nudge": True})

    class FakeEmailSession:
        def __init__(self) -> None:
            self.reasons: list[str] = []

        async def clear_silently(self, *, reason: str = "cleared") -> dict:
            self.reasons.append(reason)
            return {"state": "idle", "cleared": 1, "reason": reason}

    fake_session = FakeEmailSession()
    monkeypatch.setattr(
        email_voice_session_service,
        "get_email_voice_session_service",
        lambda: fake_session,
    )

    try:
        result = await service.set_job_enabled("reachy_email_nudge", False)

        assert result["success"] is True
        assert result["enabled"] is False
        assert fake_session.reasons == ["scheduler_disabled"]
    finally:
        await service.stop()


@pytest.mark.asyncio
async def test_email_voice_suppresses_announced_ids_and_clears_silently():
    service = EmailVoiceSessionService()
    service._announced_at["email-1"] = datetime.now(timezone.utc)

    added = await service.enqueue(["email-1", "email-2"])
    assert added == 1

    service._state = "awaiting_decision"
    service._ctx = _SessionContext(email_id="email-2", sender_label="Ada", subject="Status")
    service._queue.remove("email-2")
    service._queue.append("email-3")

    cleared = await service.clear_silently(reason="scheduler_disabled")
    status = service.status()
    added_again = await service.enqueue(["email-2"])

    assert cleared == {"state": "idle", "cleared": 2, "reason": "scheduler_disabled"}
    assert status["state"] == "idle"
    assert status["queue_length"] == 0
    assert status["active_email_id"] is None
    assert status["suppressed_count"] == 2
    assert added_again == 0


def test_scheduler_default_enabled_policy():
    assert get_default_job_enabled("reachy_email_nudge") is False
    assert get_default_job_enabled("tiktok_shop_research") is False
    assert get_default_job_enabled("gmail_check", {"enabled": True}) is True
    assert get_default_job_enabled("enhancement_scan", {"enabled": False}) is False
