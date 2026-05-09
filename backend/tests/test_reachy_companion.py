import pytest

from app.models.reachy_companion import CompanionEventCreate, CompanionPolicyPatch
from app.services.reachy_companion_service import ReachyCompanionService
from app.services.reachy_motion_policy import body_motion_allowed, body_motion_locked_payload


@pytest.mark.asyncio
async def test_privacy_mode_enforces_consent_gates(tmp_path):
    svc = ReachyCompanionService(tmp_path)

    policy = await svc.set_mode("privacy", reason="test", apply_actions=False)

    assert policy.mode == "privacy"
    assert policy.mic_enabled is False
    assert policy.camera_enabled is False
    assert policy.proactive_enabled is False
    assert policy.cloud_realtime_allowed is False
    assert svc.action_allowed("mic_listen")["allowed"] is False
    assert svc.action_allowed("camera_read")["allowed"] is False
    assert svc.action_allowed("alert")["allowed"] is True


def test_event_bus_persists_typed_events(tmp_path):
    svc = ReachyCompanionService(tmp_path)

    event = svc.record_event(
        CompanionEventCreate(
            type="phone_seen",
            source="test",
            summary="Phone detected near keyboard.",
            payload={"confidence": 0.91},
            importance=0.7,
        )
    )

    reloaded = ReachyCompanionService(tmp_path)
    events = reloaded.list_events()
    assert events[0].id == event.id
    assert events[0].type == "phone_seen"
    assert events[0].payload["confidence"] == 0.91


@pytest.mark.asyncio
async def test_mode_policy_keeps_sleep_body_and_memory_quiet(tmp_path):
    svc = ReachyCompanionService(tmp_path)

    policy = await svc.set_mode("sleep", reason="test", apply_actions=False)
    patched = svc.update_policy(CompanionPolicyPatch(mic_enabled=True, memory_write_allowed=True))

    assert policy.mode == "sleep"
    assert patched.mode == "sleep"
    assert patched.mic_enabled is False
    assert patched.body_motion_enabled is False
    assert patched.memory_write_allowed is False
    assert svc.action_allowed("body_motion")["allowed"] is False
    assert svc.action_allowed("memory_write")["allowed"] is False


@pytest.mark.asyncio
async def test_focus_skill_is_enabled_by_focus_policy(tmp_path):
    svc = ReachyCompanionService(tmp_path)
    await svc.set_mode("focus", reason="test", apply_actions=False)

    skills = {skill.id: skill for skill in svc.list_skills()}

    assert skills["focus_guardian"].enabled is False
    assert "body_motion" in (skills["focus_guardian"].blocked_reason or "")
    assert skills["phone_detox"].enabled is True
    assert skills["morning_briefing"].enabled is False


@pytest.mark.asyncio
async def test_companion_modes_keep_body_motion_opt_in(tmp_path):
    svc = ReachyCompanionService(tmp_path)

    ambient = await svc.set_mode("ambient", reason="test", apply_actions=False)
    meeting = await svc.set_mode("meeting", reason="test", apply_actions=False)

    assert ambient.body_motion_enabled is False
    assert meeting.body_motion_enabled is False
    assert svc.action_allowed("body_motion")["allowed"] is False


@pytest.mark.asyncio
async def test_body_status_treats_null_daemon_error_as_reachable(tmp_path, monkeypatch):
    class FakeReachyService:
        async def get_daemon_status(self):
            return {
                "state": "running",
                "error": None,
                "backend_status": {
                    "ready": False,
                    "motor_control_mode": "disabled",
                },
            }

        async def get_full_state(self, *, timeout: float, quiet: bool):
            return {"control_mode": "disabled", "body_yaw": 0.0}

    monkeypatch.setattr(
        "app.services.reachy_service.get_reachy_service",
        lambda: FakeReachyService(),
    )
    svc = ReachyCompanionService(tmp_path)

    status = await svc._body_status({"running": True})

    assert status["connected"] is True
    assert status["ready"] is False
    assert status["detail"] == "Robot body is reachable, but motors are disabled/asleep."


@pytest.mark.asyncio
async def test_body_status_uses_live_state_for_enabled_motor_readiness(tmp_path, monkeypatch):
    class FakeReachyService:
        async def get_daemon_status(self):
            return {
                "state": "running",
                "error": None,
                "backend_status": {
                    "ready": False,
                    "motor_control_mode": "disabled",
                },
            }

        async def get_full_state(self, *, timeout: float, quiet: bool):
            return {"control_mode": "enabled", "body_yaw": 0.0}

    monkeypatch.setattr(
        "app.services.reachy_service.get_reachy_service",
        lambda: FakeReachyService(),
    )
    svc = ReachyCompanionService(tmp_path)

    status = await svc._body_status({"running": True})

    assert status["connected"] is True
    assert status["ready"] is True
    assert status["detail"] == "Robot body is reachable; motor control is enabled."


def test_motion_policy_fails_closed_when_companion_policy_denies(monkeypatch):
    class FakeCompanion:
        def action_allowed(self, action: str):
            assert action == "body_motion"
            return {"allowed": False, "reason": "body_motion_disabled"}

    monkeypatch.setattr(
        "app.services.reachy_companion_service.get_reachy_companion_service",
        lambda: FakeCompanion(),
    )

    policy = body_motion_allowed(surface="test")
    payload = body_motion_locked_payload(surface="test")

    assert policy["allowed"] is False
    assert policy["reason"] == "body_motion_disabled"
    assert payload["error"] == "body_motion_locked"
    assert payload["surface"] == "test"


@pytest.mark.asyncio
async def test_presence_starts_are_blocked_when_body_motion_locked(monkeypatch):
    from app.services.reachy_presence_service import ReachyPresenceService

    monkeypatch.setattr(
        "app.services.reachy_presence_service.body_motion_allowed",
        lambda *, surface="unknown": {"allowed": False, "reason": "body_motion_disabled"},
    )
    monkeypatch.setattr(
        "app.services.reachy_presence_service.body_motion_locked_payload",
        lambda *, surface="unknown": {"error": "body_motion_locked", "surface": surface},
    )

    svc = ReachyPresenceService()

    pomodoro = await svc.pomodoro_start()
    meeting = await svc.start_meeting_mode("m-1")

    assert pomodoro["error"] == "body_motion_locked"
    assert pomodoro["active"] is False
    assert meeting["error"] == "body_motion_locked"
    assert meeting["active"] is False


@pytest.mark.asyncio
async def test_radio_and_move_replay_are_blocked_when_body_motion_locked(monkeypatch):
    from app.services.reachy_move_recorder import ReachyMoveRecorder
    from app.services.reachy_radio_service import ReachyRadioService

    locked = lambda *, surface="unknown": {"allowed": False, "reason": "body_motion_disabled"}
    payload = lambda *, surface="unknown": {"error": "body_motion_locked", "surface": surface}
    monkeypatch.setattr("app.services.reachy_radio_service.body_motion_allowed", locked)
    monkeypatch.setattr("app.services.reachy_radio_service.body_motion_locked_payload", payload)
    monkeypatch.setattr("app.services.reachy_move_recorder.body_motion_allowed", locked)
    monkeypatch.setattr("app.services.reachy_move_recorder.body_motion_locked_payload", payload)

    radio = await ReachyRadioService().start(bpm=120)
    recorder = await ReachyMoveRecorder().play("user", "wave")

    assert radio["error"] == "body_motion_locked"
    assert recorder["error"] == "body_motion_locked"
