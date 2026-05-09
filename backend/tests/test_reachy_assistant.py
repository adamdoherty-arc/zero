from __future__ import annotations

import json
from datetime import datetime

import pytest
from fastapi import HTTPException

from app.routers import reachy
from app.services.reachy_service import ReachyService
from app.services.reachy_realtime import tools as tool_registry
from app.services.reachy_realtime.bg_tool_manager import BackgroundToolManager
from app.services.reachy_realtime.common import MotionDispatcher, ToolDependencies


@pytest.fixture(autouse=True)
def _no_daemon_hardware_faults(monkeypatch):
    reachy._LAST_STATE_PROBE = None
    reachy._LAST_STATE_PROBE_AT = 0.0
    reachy._LAST_HARDWARE_FAULTS = None
    reachy._LAST_HARDWARE_FAULTS_AT = 0.0

    async def fake_faults():
        return {"available": True, "active": False, "faults": []}

    monkeypatch.setattr(reachy, "_daemon_hardware_faults_safe", fake_faults)


class _FakeReachyService:
    def __init__(
        self,
        connected: bool = False,
        daemon_status: dict | None = None,
        state_probe: dict | None = None,
        running_moves: list | dict | None = None,
    ):
        self.connected = connected
        self.daemon_status = daemon_status
        self.state_probe = state_probe
        self.running_moves = running_moves if running_moves is not None else []
        self.calls: list[tuple[str, dict | None]] = []

    async def is_connected(self) -> bool:
        return self.connected

    async def get_daemon_status(self, **_kwargs) -> dict:
        if self.daemon_status is not None:
            return self.daemon_status
        return {"state": "running"} if self.connected else {"error": "Robot not connected"}

    def get_status_info(self) -> dict:
        return {"base_url": "http://host.docker.internal:8000"}

    async def get_full_state(self, **_kwargs) -> dict:
        if self.state_probe is not None:
            return self.state_probe
        return (
            {"control_mode": "enabled", "head_pose": {"x": 0, "y": 0, "z": 0}}
            if self.connected
            else {"error": "Robot state not responding"}
        )

    async def set_motor_mode(self, mode: str) -> dict:
        self.calls.append(("set_motor_mode", {"mode": mode}))
        if isinstance(self.state_probe, dict):
            self.state_probe["control_mode"] = mode
        if isinstance(self.daemon_status, dict):
            backend_status = self.daemon_status.setdefault("backend_status", {})
            if isinstance(backend_status, dict):
                backend_status["motor_control_mode"] = mode
        return {"status": f"motors changed to {mode} mode"}

    async def wake_up(self) -> dict:
        self.calls.append(("wake_up", None))
        return {"uuid": "fake-wake"}

    async def is_moving(self) -> list | dict:
        return self.running_moves

    async def stop_move(self, move_uuid: str | None = None) -> dict:
        self.calls.append(("stop_move", {"uuid": move_uuid} if move_uuid else None))
        return {"stopped": True, "uuid": move_uuid}

    async def stop_all_moves(self) -> dict:
        self.calls.append(("stop_all_moves", None))
        return {"ok": True, "running": self.running_moves, "uuids": [], "stops": []}

    async def settle_neutral(self, *, duration: float = 1.0) -> dict:
        self.calls.append(("settle_neutral", {"duration": duration}))
        return {"uuid": "neutral-pose"}


class _FakeVoiceLoop:
    def __init__(self, persona: str = "assistant"):
        self.persona = persona

    def get_active_persona_id(self) -> str:
        return self.persona

    def set_persona(self, persona: str) -> bool:
        self.persona = persona
        return True


class _FakePresence:
    def __init__(self):
        self.ambient_enabled = False
        self.meeting_active = False
        self.pomodoro_active = False

    def ambient_state(self) -> dict:
        return {"enabled": self.ambient_enabled, "jobs": []}

    def ambient_start(self) -> dict:
        self.ambient_enabled = True
        return self.ambient_state()

    def ambient_stop(self) -> dict:
        self.ambient_enabled = False
        return self.ambient_state()

    def meeting_state(self) -> dict:
        return {"active": self.meeting_active}

    async def stop_meeting_mode(self, *, play_ack: bool = True) -> dict:
        self.meeting_active = False
        state = self.meeting_state()
        state["play_ack"] = play_ack
        return state

    def pomodoro_state(self) -> dict:
        return {"active": self.pomodoro_active, "phase": "focus" if self.pomodoro_active else None}

    async def pomodoro_start(self, focus_minutes: int = 25, break_minutes: int = 5) -> dict:
        self.pomodoro_active = True
        return {
            "active": True,
            "phase": "focus",
            "focus_minutes": focus_minutes,
            "break_minutes": break_minutes,
        }

    async def pomodoro_stop(self, *, play_ack: bool = True) -> dict:
        self.pomodoro_active = False
        state = self.pomodoro_state()
        state["play_ack"] = play_ack
        return state


class _FakeReachyClientService(ReachyService):
    def __init__(self, running):
        super().__init__()
        self.running = running
        self.stopped: list[str] = []

    async def is_moving(self) -> list | dict:
        return self.running

    async def stop_move(self, move_uuid: str | None = None) -> dict:
        if move_uuid:
            self.stopped.append(move_uuid)
        return {"ok": True, "uuid": move_uuid}


def _patch_common(
    monkeypatch,
    *,
    connected: bool = False,
    persona: str = "assistant",
    daemon_status: dict | None = None,
    state_probe: dict | None = None,
) -> _FakePresence:
    presence = _FakePresence()
    service = _FakeReachyService(connected, daemon_status, state_probe)
    monkeypatch.setattr(
        reachy,
        "get_reachy_service",
        lambda: service,
    )
    monkeypatch.setattr(reachy, "get_voice_loop_service", lambda: _FakeVoiceLoop(persona))
    monkeypatch.setattr(reachy, "get_reachy_presence_service", lambda: presence)
    monkeypatch.setattr(
        reachy,
        "_realtime_config_safe",
        lambda: {
            "backend": "local",
            "preferred_backend": "local",
            "realtime_available": True,
            "profile": persona,
        },
    )
    return presence


@pytest.mark.asyncio
async def test_stop_all_moves_ignores_stale_local_uuid_when_daemon_reports_empty():
    service = _FakeReachyClientService(running=[])
    service._active_move_uuid = "stale-neutral"

    payload = await service.stop_all_moves()

    assert payload["ok"] is True
    assert payload["uuids"] == []
    assert service.stopped == []
    assert service._active_move_uuid is None


@pytest.mark.asyncio
async def test_stop_all_moves_falls_back_to_local_uuid_when_running_probe_fails():
    service = _FakeReachyClientService(running={"error": "probe failed"})
    service._active_move_uuid = "known-active"

    payload = await service.stop_all_moves()

    assert payload["ok"] is True
    assert payload["uuids"] == ["known-active"]
    assert service.stopped == ["known-active"]


def test_assistant_state_prioritizes_repair_required():
    steps = [
        reachy._assistant_step("zero_api", "Zero API", "ready"),
        reachy._assistant_step("host_agent", "Host", "repair_required"),
        reachy._assistant_step("reachy_daemon", "Daemon", "offline"),
    ]
    assert reachy._derive_assistant_state(steps) == "repair_required"


def test_assistant_state_prioritizes_hardware_degraded_over_daemon_starting():
    steps = [
        reachy._assistant_step("zero_api", "Zero API", "ready"),
        reachy._assistant_step("host_agent", "Host", "ready"),
        reachy._assistant_step("reachy_daemon", "Daemon", "starting"),
        reachy._assistant_step("robot", "Robot", "degraded"),
        reachy._assistant_step("voice_backend", "Voice", "ready"),
        reachy._assistant_step("persona", "Persona", "ready"),
    ]
    assert reachy._derive_assistant_state(steps) == "degraded"


def test_assistant_state_ready_when_all_steps_ready():
    steps = [
        reachy._assistant_step("zero_api", "Zero API", "ready"),
        reachy._assistant_step("host_agent", "Host", "ready"),
        reachy._assistant_step("reachy_daemon", "Daemon", "ready"),
    ]
    assert reachy._derive_assistant_state(steps) == "ready"


def test_pose_jitter_marks_shaky_without_motion_source():
    jitter = reachy._jitter_from_signatures([
        {"head_roll": 0.0, "head_yaw": 0.0, "body_yaw": 0.0},
        {"head_roll": 0.041, "head_yaw": 0.01, "body_yaw": 0.0},
    ])
    assert jitter["shaky"] is True
    assert jitter["head_delta_rad"] > 0.03


@pytest.mark.asyncio
async def test_reachy_status_probes_body_when_daemon_status_falls_back(monkeypatch):
    service = _FakeReachyService(
        connected=True,
        daemon_status={
            "type": "daemon_status",
            "state": "running",
            "connected": True,
            "via": "host_agent_supervisor",
            "daemon_route": "host_agent_supervisor",
            "daemon_direct_reachable": False,
            "status_stale": True,
            "backend_status": {"ready": None, "motor_control_mode": None},
        },
        state_probe={
            "control_mode": "disabled",
            "head_pose": {"x": 0, "y": 0, "z": 0},
            "body_yaw": 0,
        },
    )

    async def fake_host_get(path: str, *, timeout: float = 3.0, attempts: int = 2):
        if path == "/daemon/status":
            return {"running": True, "pid": 1234, "uptime_seconds": 180}
        if path == "/daemon/watchdog":
            return {"enabled": True}
        return {}

    monkeypatch.setattr(reachy, "get_reachy_service", lambda: service)
    monkeypatch.setattr(reachy, "get_reachy_presence_service", lambda: _FakePresence())
    monkeypatch.setattr(reachy, "_host_agent_get_safe", fake_host_get)

    payload = await reachy.get_status()

    assert payload["connected"] is True
    assert payload["robot_ready"] is False
    assert payload["body_control_mode"] == "disabled"
    assert payload["state_probe_reachable"] is True
    assert payload["daemon_direct_reachable"] is False
    assert payload["status_stale"] is False
    assert payload["daemon"]["status_stale"] is True
    assert payload["recommended_action"]["id"] == "wake_robot"
    assert "disabled/asleep" in payload["robot_detail"]
    assert "Docker" not in payload["robot_detail"]


@pytest.mark.asyncio
async def test_reachy_status_uses_body_state_when_daemon_metadata_times_out(monkeypatch):
    service = _FakeReachyService(
        connected=True,
        daemon_status={
            "error": "ReadTimeout",
            "connected": False,
            "via": "direct_error",
            "daemon_route": "direct",
            "daemon_direct_reachable": False,
            "status_stale": True,
        },
        state_probe={
            "control_mode": "enabled",
            "head_pose": {"x": 0, "y": 0, "z": 0},
            "body_yaw": 0,
        },
    )

    async def fake_host_get(path: str, *, timeout: float = 3.0, attempts: int = 2):
        if path == "/daemon/status":
            return None
        if path == "/daemon/watchdog":
            return {"enabled": True}
        return {}

    monkeypatch.setattr(reachy, "get_reachy_service", lambda: service)
    monkeypatch.setattr(reachy, "get_reachy_presence_service", lambda: _FakePresence())
    monkeypatch.setattr(reachy, "_host_agent_get_safe", fake_host_get)

    payload = await reachy.get_status()

    assert payload["connected"] is True
    assert payload["daemon_connected"] is True
    assert payload["daemon_status_running"] is True
    assert payload["robot_ready"] is True
    assert payload["body_control_mode"] == "enabled"
    assert payload["state_probe_reachable"] is True
    assert payload["daemon_direct_reachable"] is False
    assert payload["status_stale"] is False
    assert payload["recommended_action"]["id"] == "none"
    assert payload["daemon"]["direct_error"] == "ReadTimeout"


def test_extract_motor_hardware_faults_from_daemon_logs():
    payload = {
        "lines": [
            "2026-05-03 15:16:25,011 ERROR Motor 'left_antenna' hardware errors: ['Overload Error']",
            "2026-05-03 15:16:26,062 ERROR Motor 'left_antenna' hardware errors: ['Overload Error']",
            "[WARN] Motor 'body_rotation' (ID 10) not found on the bus. Check that the motor is properly connected.",
            "[WARN] Motor 'stewart_1' (ID 11) not found on the bus. Check that the motor is properly connected.",
            "[WARN] Motor 'stewart_2' (ID 12) not found on the bus. Check that the motor is properly connected.",
            "Failed to start daemon: No motors detected. Check if the power supply is connected and turned on!",
        ]
    }

    faults = reachy._extract_motor_hardware_faults(
        payload,
        now=datetime(2026, 5, 3, 15, 16, 30, tzinfo=reachy._LOCAL_TZ),
    )

    assert faults["active"] is True
    assert faults["faults"][0]["motor"] == "left_antenna"
    assert faults["faults"][0]["count"] == 2
    assert faults["power_issue"] is True
    assert faults["issues"][0]["id"] == "motors_unpowered"


def test_extract_motor_hardware_faults_clears_motor_power_after_clean_start():
    payload = {
        "lines": [
            "[WARN] Motor 'body_rotation' (ID 10) not found on the bus. Check that the motor is properly connected.",
            "[WARN] Motor 'stewart_1' (ID 11) not found on the bus. Check that the motor is properly connected.",
            "[WARN] Motor 'stewart_2' (ID 12) not found on the bus. Check that the motor is properly connected.",
            "Failed to start daemon: No motors detected. Check if the power supply is connected and turned on!",
            "2026-05-06 13:13:02,485 INFO [reachy_mini.daemon.daemon] Daemon started successfully.",
        ]
    }

    faults = reachy._extract_motor_hardware_faults(
        payload,
        now=datetime(2026, 5, 6, 13, 13, 10, tzinfo=reachy._LOCAL_TZ),
    )

    assert faults["active"] is False
    assert faults["power_issue"] is False
    assert faults["issues"] == []
    assert faults["stale"] is True
    assert faults["cleared_by_clean_daemon_start"] is True


def test_extract_motor_hardware_faults_marks_old_log_faults_stale():
    payload = {
        "lines": [
            "2026-05-04 17:43:41,831 ERROR Motor 'stewart_3' hardware errors: ['Overload Error']",
            "2026-05-04 17:44:13,982 ERROR Motor 'stewart_3' hardware errors: ['Overload Error']",
            "--- daemon exited pid=123 code=1 ---",
        ]
    }

    faults = reachy._extract_motor_hardware_faults(
        payload,
        now=datetime(2026, 5, 4, 19, 59, 0, tzinfo=reachy._LOCAL_TZ),
    )

    assert faults["active"] is False
    assert faults["stale"] is True
    assert faults["faults"][0]["motor"] == "stewart_3"
    assert faults["faults"][0]["active"] is False
    assert faults["faults"][0]["stale"] is True
    assert faults["last_fault_age_seconds"] > reachy._HARDWARE_FAULT_ACTIVE_WINDOW_S


def test_clean_daemon_start_clears_prior_log_fault_latch():
    faults = reachy._extract_motor_hardware_faults(
        {
            "lines": [
                "2026-05-04 20:23:00,440 ERROR Motor 'stewart_3' hardware errors: ['Overload Error']",
            ]
        },
        now=datetime(2026, 5, 4, 20, 59, 30, tzinfo=reachy._LOCAL_TZ),
    )

    cleared = reachy._clear_faults_after_clean_daemon_start(
        faults,
        {
            "running": True,
            "started_at": "2026-05-05T00:59:08.688689+00:00",
        },
    )

    assert faults["active"] is True
    assert cleared["active"] is False
    assert cleared["stale"] is True
    assert cleared["cleared_by_clean_daemon_start"] is True
    assert cleared["faults"][0]["active"] is False


def test_assistant_hardware_fault_check_ignores_stale_fault_history():
    payload = {
        "hardware_issues": {
            "available": True,
            "active": False,
            "stale": True,
            "faults": [{"motor": "stewart_3", "error": "['Overload Error']"}],
        },
        "motion_sources": [
            {
                "id": "hardware_faults",
                "active": False,
                "raw": {
                    "active": False,
                    "stale": True,
                    "faults": [{"motor": "stewart_3", "error": "['Overload Error']"}],
                },
            }
        ],
    }

    assert reachy._assistant_has_recent_hardware_fault(payload) is False
    assert reachy._assistant_has_stale_hardware_fault_history(payload) is True


def test_merge_host_known_issues_surfaces_motor_power_issue():
    faults = reachy._extract_motor_hardware_faults({"lines": ["--- daemon exited pid=123 code=1 ---"]})
    merged = reachy._merge_host_known_issues(
        faults,
        {
            "count": 1,
            "items": [
                {
                    "id": "motors_unpowered",
                    "severity": "error",
                    "title": "Reachy motors are not powered",
                    "hint": "The USB serial bridge is visible, but the motor bus is empty.",
                }
            ],
        },
    )

    assert merged["available"] is True
    assert merged["active"] is True
    assert merged["power_issue"] is True
    assert merged["issues"][0]["id"] == "motors_unpowered"
    assert "motor bus is empty" in merged["issues"][0]["detail"]


@pytest.mark.asyncio
async def test_motion_sources_mark_enabled_hardware_fault_as_shaky(monkeypatch):
    service = _FakeReachyService(
        connected=True,
        daemon_status={"type": "daemon_status", "state": "running"},
        state_probe={"control_mode": "enabled", "head_pose": {"roll": 0, "pitch": 0, "yaw": 0}},
    )

    async def fake_faults():
        return {
            "available": True,
            "active": True,
            "faults": [{"motor": "left_antenna", "error": "['Overload Error']", "count": 4}],
        }

    monkeypatch.setattr(reachy, "_daemon_hardware_faults_safe", fake_faults)

    payload = await reachy._motion_sources_payload(service=service, state_probe=service.state_probe)

    assert payload["body_activity"] == "shaky"
    assert "hardware_faults" in payload["active_source_ids"]


@pytest.mark.asyncio
async def test_motion_sources_do_not_mark_scanning_head_tracking_as_moving(monkeypatch):
    service = _FakeReachyService(
        connected=True,
        daemon_status={"type": "daemon_status", "state": "running"},
        state_probe={"control_mode": "enabled", "head_pose": {"roll": 0, "pitch": 0, "yaw": 0}},
    )

    class FakeHeadTracking:
        def status(self):
            return {
                "running": True,
                "state": "scanning",
                "detail": "No face detected in the current Reachy camera frame.",
                "moves": 0,
            }

    from app.services import reachy_head_tracking_service

    monkeypatch.setattr(
        reachy_head_tracking_service,
        "get_reachy_head_tracking_service",
        lambda: FakeHeadTracking(),
    )

    payload = await reachy._motion_sources_payload(service=service, state_probe=service.state_probe)
    source = next(src for src in payload["sources"] if src["id"] == "head_tracking")

    assert source["enabled"] is True
    assert source["active"] is False
    assert "head_tracking" not in payload["active_source_ids"]
    assert payload["body_activity"] == "still"


@pytest.mark.asyncio
async def test_assistant_status_host_down_returns_repair_command(monkeypatch):
    _patch_common(monkeypatch)

    async def fake_get(path: str, *, timeout: float = 3.0, attempts: int = 2):
        return None

    monkeypatch.setattr(reachy, "_host_agent_get_safe", fake_get)

    payload = await reachy._assistant_status_payload()
    assert payload["state"] == "repair_required"
    assert payload["repair_command"].endswith("scripts\\start-zero.ps1")
    host_step = next(step for step in payload["steps"] if step["id"] == "host_agent")
    assert host_step["state"] == "repair_required"


@pytest.mark.asyncio
async def test_assistant_status_marks_stuck_daemon_offline(monkeypatch):
    _patch_common(
        monkeypatch,
        daemon_status={"error": "All connection attempts failed", "connected": False},
    )

    async def fake_get(path: str, *, timeout: float = 3.0, attempts: int = 2):
        if path == "/health":
            return {"ok": True}
        if path == "/daemon/status":
            return {"running": True, "pid": 1234, "uptime_seconds": 180}
        if path == "/daemon/watchdog":
            return {"enabled": True}
        return {}

    monkeypatch.setattr(reachy, "_host_agent_get_safe", fake_get)

    payload = await reachy._assistant_status_payload()
    daemon_step = next(step for step in payload["steps"] if step["id"] == "reachy_daemon")
    assert daemon_step["state"] == "offline"
    assert ":8000 is not responding" in daemon_step["detail"]


@pytest.mark.asyncio
async def test_assistant_status_marks_daemon_backend_error_degraded(monkeypatch):
    _patch_common(
        monkeypatch,
        daemon_status={
            "type": "daemon_status",
            "state": "error",
            "error": "No motors detected. Check if the power supply is connected and turned on!",
            "version": "1.6.4",
        },
    )

    async def fake_get(path: str, *, timeout: float = 3.0):
        if path == "/health":
            return {"ok": True}
        if path == "/daemon/status":
            return {"running": True, "pid": 1234, "uptime_seconds": 180}
        if path == "/daemon/watchdog":
            return {"enabled": True}
        return {}

    monkeypatch.setattr(reachy, "_host_agent_get_safe", fake_get)

    payload = await reachy._assistant_status_payload()
    assert payload["state"] == "degraded"
    daemon_step = next(step for step in payload["steps"] if step["id"] == "reachy_daemon")
    robot_step = next(step for step in payload["steps"] if step["id"] == "robot")
    assert daemon_step["state"] == "degraded"
    assert "No motors detected" in daemon_step["detail"]
    assert robot_step["state"] == "degraded"
    assert "No motors detected" in payload["robot_detail"]
    assert payload["hardware_issues"]["power_issue"] is True
    assert payload["recommended_action"]["id"] == "check_motor_power"


@pytest.mark.asyncio
async def test_assistant_status_uses_supervisor_blocker_from_status_fallback(monkeypatch):
    _patch_common(
        monkeypatch,
        daemon_status={
            "type": "daemon_status",
            "state": "running",
            "connected": True,
            "via": "host_agent_supervisor",
            "direct_error": "No motors detected. Check if the power supply is connected and turned on!",
            "supervisor": {
                "running": True,
                "probe_healthy": False,
                "probe_blocker": {
                    "id": "motors_unpowered",
                    "detail": "No motors detected. Check if the power supply is connected and turned on!",
                },
                "listening_pid": 1234,
            },
        },
        state_probe={"error": "Request failed: 503", "status": 503},
    )

    async def fake_get(path: str, *, timeout: float = 3.0, attempts: int = 2):
        if path == "/health":
            return {"ok": True}
        if path == "/daemon/status":
            return {
                "running": True,
                "pid": 1234,
                "probe_blocker": {
                    "id": "motors_unpowered",
                    "detail": "No motors detected. Check if the power supply is connected and turned on!",
                },
                "listening_pid": 1234,
            }
        if path == "/daemon/watchdog":
            return {"enabled": True}
        return {}

    monkeypatch.setattr(reachy, "_host_agent_get_safe", fake_get)

    payload = await reachy._assistant_status_payload(fast=True)

    assert payload["state"] == "degraded"
    assert "No motors detected" in payload["robot_detail"]
    assert payload["hardware_issues"]["power_issue"] is True
    assert payload["recommended_action"]["id"] == "check_motor_power"


@pytest.mark.asyncio
async def test_assistant_status_surfaces_motor_power_issue_after_daemon_stops(monkeypatch):
    _patch_common(
        monkeypatch,
        daemon_status={"error": "Robot not connected", "connected": False},
    )

    async def fake_get(path: str, *, timeout: float = 3.0):
        if path == "/health":
            return {"ok": True}
        if path == "/daemon/status":
            return {"running": False, "pid": None, "uptime_seconds": None}
        if path == "/daemon/watchdog":
            return {"enabled": False}
        return {}

    async def fake_faults():
        return {
            "available": True,
            "active": True,
            "power_issue": True,
            "faults": [],
            "issues": [
                {
                    "id": "motors_unpowered",
                    "title": "Reachy motor bus is not detected",
                    "detail": "USB serial is visible, but the daemon cannot see the motor bus.",
                }
            ],
        }

    monkeypatch.setattr(reachy, "_host_agent_get_safe", fake_get)
    monkeypatch.setattr(reachy, "_daemon_hardware_faults_safe", fake_faults)

    payload = await reachy._assistant_status_payload()

    daemon_step = next(step for step in payload["steps"] if step["id"] == "reachy_daemon")
    robot_step = next(step for step in payload["steps"] if step["id"] == "robot")
    assert payload["state"] == "degraded"
    assert payload["hardware_issues"]["power_issue"] is True
    assert daemon_step["state"] == "degraded"
    assert "motor bus" in daemon_step["detail"]
    assert robot_step["state"] == "degraded"
    assert "motor bus is not detected" in robot_step["detail"]


@pytest.mark.asyncio
async def test_assistant_status_surfaces_recent_overload_after_daemon_stops(monkeypatch):
    _patch_common(
        monkeypatch,
        daemon_status={"error": "Robot not connected", "connected": False},
    )

    async def fake_get(path: str, *, timeout: float = 3.0):
        if path == "/health":
            return {"ok": True}
        if path == "/daemon/status":
            return {"running": False, "pid": None, "uptime_seconds": None}
        if path == "/daemon/watchdog":
            return {"enabled": False}
        return {}

    async def fake_faults():
        return {
            "available": True,
            "active": True,
            "power_issue": False,
            "faults": [
                {
                    "motor": "stewart_3",
                    "error": "['Overload Error']",
                    "count": 44,
                    "last_line": "Motor 'stewart_3' hardware errors: ['Overload Error']",
                }
            ],
            "issues": [],
        }

    monkeypatch.setattr(reachy, "_host_agent_get_safe", fake_get)
    monkeypatch.setattr(reachy, "_daemon_hardware_faults_safe", fake_faults)

    payload = await reachy._assistant_status_payload()

    daemon_step = next(step for step in payload["steps"] if step["id"] == "reachy_daemon")
    watchdog_step = next(step for step in payload["steps"] if step["id"] == "watchdog")
    robot_step = next(step for step in payload["steps"] if step["id"] == "robot")
    assert payload["state"] == "degraded"
    assert "hardware_faults" in payload["active_source_ids"]
    assert payload["body_activity"] == "unknown"
    assert daemon_step["state"] == "degraded"
    assert "overload" in daemon_step["detail"].lower()
    assert "protection" in watchdog_step["detail"]
    assert robot_step["state"] == "degraded"
    assert "stewart_3" in robot_step["detail"]


@pytest.mark.asyncio
async def test_assistant_status_accepts_healthy_body_when_daemon_status_is_stale_error(monkeypatch):
    _patch_common(
        monkeypatch,
        daemon_status={
            "type": "daemon_status",
            "state": "error",
            "backend_status": {
                "ready": False,
                "motor_control_mode": "enabled",
                "last_alive": None,
                "error": None,
            },
            "version": "1.6.4",
        },
        state_probe={
            "control_mode": "enabled",
            "head_pose": {"roll": 0, "pitch": 0, "yaw": 0},
            "body_yaw": 0,
            "antennas_position": [0, 0],
        },
    )

    async def fake_get(path: str, *, timeout: float = 3.0):
        if path == "/health":
            return {"ok": True}
        if path == "/daemon/status":
            return {"running": True, "pid": 1234, "uptime_seconds": 180}
        if path == "/daemon/watchdog":
            return {"enabled": True}
        return {}

    monkeypatch.setattr(reachy, "_host_agent_get_safe", fake_get)

    payload = await reachy._assistant_status_payload()
    daemon_step = next(step for step in payload["steps"] if step["id"] == "reachy_daemon")
    robot_step = next(step for step in payload["steps"] if step["id"] == "robot")
    assert payload["state"] == "ready"
    assert payload["connected"] is True
    assert payload["daemon_connected"] is True
    assert payload["daemon_status_running"] is True
    assert payload["robot_ready"] is True
    assert daemon_step["state"] == "ready"
    assert "body state is responding" in daemon_step["detail"]
    assert robot_step["state"] == "ready"


@pytest.mark.asyncio
async def test_assistant_status_marks_disabled_body_degraded_not_ready(monkeypatch):
    _patch_common(
        monkeypatch,
        connected=True,
        daemon_status={
            "type": "daemon_status",
            "state": "running",
            "backend_status": {
                "ready": False,
                "motor_control_mode": "disabled",
                "last_alive": None,
                "error": None,
            },
        },
        state_probe={"control_mode": "disabled", "head_pose": {"x": 0, "y": 0, "z": 0}},
    )

    async def fake_get(path: str, *, timeout: float = 3.0):
        if path == "/health":
            return {"ok": True}
        if path == "/daemon/status":
            return {"running": True, "pid": 1234, "uptime_seconds": 180}
        if path == "/daemon/watchdog":
            return {"enabled": True}
        return {}

    monkeypatch.setattr(reachy, "_host_agent_get_safe", fake_get)

    payload = await reachy._assistant_status_payload()
    robot_step = next(step for step in payload["steps"] if step["id"] == "robot")
    assert payload["state"] == "degraded"
    assert payload["connected"] is True
    assert payload["robot_ready"] is False
    assert payload["body_control_mode"] == "disabled"
    assert robot_step["state"] == "degraded"
    assert "disabled" in robot_step["detail"]


@pytest.mark.asyncio
async def test_assistant_status_marks_body_shaky_degraded(monkeypatch):
    _patch_common(
        monkeypatch,
        connected=True,
        daemon_status={"type": "daemon_status", "state": "running"},
        state_probe={"control_mode": "enabled", "head_pose": {"roll": 0, "pitch": 0, "yaw": 0}},
    )

    async def fake_get(path: str, *, timeout: float = 3.0):
        if path == "/health":
            return {"ok": True}
        if path == "/daemon/status":
            return {"running": True, "pid": 1234, "uptime_seconds": 180}
        if path == "/daemon/watchdog":
            return {"enabled": True}
        return {}

    async def fake_motion_sources(**_kwargs):
        return {
            "state": "degraded",
            "sources": [],
            "active_source_ids": [],
            "body_activity": "shaky",
            "pose_jitter": {"available": True, "samples": 2, "shaky": True, "head_delta_rad": 0.04},
        }

    monkeypatch.setattr(reachy, "_host_agent_get_safe", fake_get)
    monkeypatch.setattr(reachy, "_motion_sources_payload", fake_motion_sources)

    payload = await reachy._assistant_status_payload()
    robot_step = next(step for step in payload["steps"] if step["id"] == "robot")
    assert payload["state"] == "degraded"
    assert payload["body_activity"] == "shaky"
    assert robot_step["state"] == "degraded"
    assert "Press Settle" in robot_step["detail"]


@pytest.mark.asyncio
async def test_assistant_activate_defaults_to_voice_only_and_leaves_daemon_unchanged(monkeypatch):
    _patch_common(monkeypatch, connected=False, persona="companion")
    calls: list[tuple[str, dict | None]] = []

    async def fake_get(path: str, *, timeout: float = 3.0):
        if path == "/health":
            return {"ok": True}
        if path == "/daemon/status":
            return {"running": False, "pid": None}
        if path == "/daemon/watchdog":
            return {"enabled": False}
        return {}

    async def fake_post(path: str, *, json: dict | None = None, timeout: float = 10.0):
        calls.append((path, json))
        return {"ok": True, "path": path}

    import app.services.reachy_realtime.config_store as config_store

    monkeypatch.setattr(reachy, "_host_agent_get_safe", fake_get)
    monkeypatch.setattr(reachy, "_host_agent_post_safe", fake_post)
    monkeypatch.setattr(config_store, "update_config", lambda patch: {"profile": patch.get("profile")})

    payload = await reachy.assistant_activate(reachy.AssistantActivationRequest())
    assert payload["actions"]
    assert not any(path == "/daemon/watchdog" for path, _body in calls)
    assert not any(path == "/daemon/stop" for path, _body in calls)
    assert not any(path == "/daemon/start" for path, _body in calls)
    daemon_action = next(action for action in payload["actions"] if action["id"] == "reachy_daemon")
    settle_action = next(action for action in payload["actions"] if action["id"] == "settle")
    assert daemon_action["ok"] is True
    assert "voice-only activation does not require hardware" in daemon_action["detail"]
    assert settle_action["ok"] is True
    assert "explicit opt-in" in settle_action["detail"]


@pytest.mark.asyncio
async def test_assistant_activate_voice_only_does_not_stop_running_daemon(monkeypatch):
    _patch_common(monkeypatch, connected=True, persona="companion")
    calls: list[tuple[str, dict | None]] = []

    async def fake_get(path: str, *, timeout: float = 3.0):
        if path == "/health":
            return {"ok": True}
        if path == "/daemon/status":
            return {"running": True, "pid": 1234, "uptime_seconds": 180}
        if path == "/daemon/watchdog":
            return {"enabled": False}
        return {}

    async def fake_post(path: str, *, json: dict | None = None, timeout: float = 10.0):
        calls.append((path, json))
        return {"ok": True, "path": path}

    import app.services.reachy_realtime.config_store as config_store

    monkeypatch.setattr(reachy, "_host_agent_get_safe", fake_get)
    monkeypatch.setattr(reachy, "_host_agent_post_safe", fake_post)
    monkeypatch.setattr(config_store, "update_config", lambda patch: {"profile": patch.get("profile")})

    payload = await reachy.assistant_activate(reachy.AssistantActivationRequest())

    assert ("/daemon/watchdog", {"enabled": True}) in calls
    assert not any(path == "/daemon/stop" for path, _body in calls)
    daemon_action = next(action for action in payload["actions"] if action["id"] == "reachy_daemon")
    assert daemon_action["ok"] is True
    assert "Daemon left running" in daemon_action["detail"]


@pytest.mark.asyncio
async def test_assistant_activate_restarts_unreachable_running_daemon(monkeypatch):
    _patch_common(
        monkeypatch,
        connected=False,
        daemon_status={"error": "All connection attempts failed", "connected": False},
    )
    calls: list[tuple[str, dict | None]] = []

    async def fake_get(path: str, *, timeout: float = 3.0):
        if path == "/health":
            return {"ok": True}
        if path == "/daemon/status":
            return {"running": True, "pid": 1234, "uptime_seconds": 180}
        if path == "/daemon/watchdog":
            return {"enabled": True}
        return {}

    async def fake_post(path: str, *, json: dict | None = None, timeout: float = 10.0):
        calls.append((path, json))
        return {"ok": True, "path": path}

    import app.services.reachy_realtime.config_store as config_store

    monkeypatch.setattr(reachy, "_host_agent_get_safe", fake_get)
    monkeypatch.setattr(reachy, "_host_agent_post_safe", fake_post)
    monkeypatch.setattr(reachy, "body_motion_allowed", lambda *, surface="unknown": {"allowed": True})
    monkeypatch.setattr(config_store, "update_config", lambda patch: {"profile": patch.get("profile")})

    await reachy.assistant_activate(
        reachy.AssistantActivationRequest(start_daemon=True, enable_body_motion=True)
    )
    assert any(path == "/daemon/restart" for path, _body in calls)


@pytest.mark.asyncio
async def test_assistant_activate_defaults_to_still_ready_without_wake(monkeypatch):
    service = _FakeReachyService(
        connected=True,
        daemon_status={"type": "daemon_status", "state": "running"},
        state_probe={"control_mode": "enabled", "head_pose": {"x": 0, "y": 0, "z": 0}},
    )
    presence = _FakePresence()
    calls: list[tuple[str, dict | None]] = []

    async def fake_get(path: str, *, timeout: float = 3.0):
        if path == "/health":
            return {"ok": True}
        if path == "/daemon/status":
            return {"running": True, "pid": 1234, "uptime_seconds": 180}
        if path == "/daemon/watchdog":
            return {"enabled": True}
        return {}

    async def fake_post(path: str, *, json: dict | None = None, timeout: float = 10.0):
        calls.append((path, json))
        return {"ok": True, "path": path}

    async def fake_settle(request):
        return {
            "ok": True,
            "actions": [],
            "active_source_ids": [],
            "body_activity": "still",
            "pose_jitter": {"available": True, "samples": 2, "shaky": False},
        }

    import app.services.reachy_realtime.config_store as config_store

    monkeypatch.setattr(reachy, "get_reachy_service", lambda: service)
    monkeypatch.setattr(reachy, "get_voice_loop_service", lambda: _FakeVoiceLoop("assistant"))
    monkeypatch.setattr(reachy, "get_reachy_presence_service", lambda: presence)
    monkeypatch.setattr(reachy, "_host_agent_get_safe", fake_get)
    monkeypatch.setattr(reachy, "_host_agent_post_safe", fake_post)
    monkeypatch.setattr(reachy, "_settle_assistant_body", fake_settle)
    monkeypatch.setattr(config_store, "update_config", lambda patch: {"profile": patch.get("profile")})

    payload = await reachy.assistant_activate(reachy.AssistantActivationRequest())
    assert payload["actions"]
    assert ("wake_up", None) not in service.calls
    assert any(action["id"] == "settle" and action["ok"] for action in payload["actions"])
    assert payload["recent_activity"][0]["event"] == "activate"


@pytest.mark.asyncio
async def test_wake_up_enables_motors_before_wake_motion(monkeypatch):
    service = _FakeReachyService(
        connected=True,
        daemon_status={
            "type": "daemon_status",
            "state": "running",
            "backend_status": {"motor_control_mode": "disabled"},
        },
        state_probe={"control_mode": "disabled", "head_pose": {"x": 0, "y": 0, "z": 0}},
    )

    monkeypatch.setattr(reachy, "get_reachy_service", lambda: service)
    monkeypatch.setattr(
        reachy,
        "body_motion_allowed",
        lambda *, surface="unknown": {"allowed": True},
    )

    payload = await reachy.wake_up()

    assert payload["ok"] is True
    assert payload["body_control_mode"] == "enabled"
    assert service.calls[:2] == [
        ("set_motor_mode", {"mode": "enabled"}),
        ("wake_up", None),
    ]


@pytest.mark.asyncio
async def test_assistant_activate_pauses_watchdog_when_motor_power_is_missing(monkeypatch):
    service = _FakeReachyService(
        connected=False,
        daemon_status={"error": "Robot not connected", "connected": False},
    )
    presence = _FakePresence()
    calls: list[tuple[str, dict | None]] = []

    async def fake_status(actions=None):
        return {
            "state": "degraded",
            "steps": [
                reachy._assistant_step("zero_api", "Zero API", "ready"),
                reachy._assistant_step("host_agent", "Host", "ready"),
                reachy._assistant_step("reachy_daemon", "Daemon", "degraded"),
                reachy._assistant_step("watchdog", "Watchdog", "ready"),
                reachy._assistant_step("robot", "Robot", "degraded"),
                reachy._assistant_step("voice_backend", "Voice", "ready"),
                reachy._assistant_step("persona", "Persona", "ready"),
            ],
            "actions": actions or [],
            "daemon": {"running": True, "pid": 1234},
            "hardware_issues": {"power_issue": True},
            "motion_sources": [{"id": "hardware_faults", "raw": {"power_issue": True}}],
            "body_activity": "unknown",
            "recent_activity": [],
        }

    async def fake_post(path: str, *, json: dict | None = None, timeout: float = 10.0):
        calls.append((path, json))
        return {"ok": True, "path": path}

    import app.services.reachy_realtime.config_store as config_store

    monkeypatch.setattr(reachy, "get_reachy_service", lambda: service)
    monkeypatch.setattr(reachy, "get_voice_loop_service", lambda: _FakeVoiceLoop("assistant"))
    monkeypatch.setattr(reachy, "get_reachy_presence_service", lambda: presence)
    monkeypatch.setattr(reachy, "_assistant_status_payload", fake_status)
    monkeypatch.setattr(reachy, "_host_agent_post_safe", fake_post)
    monkeypatch.setattr(reachy, "body_motion_allowed", lambda *, surface="unknown": {"allowed": True})
    monkeypatch.setattr(config_store, "update_config", lambda patch: {"profile": patch.get("profile")})

    payload = await reachy.assistant_activate(
        reachy.AssistantActivationRequest(enable_body_motion=True)
    )

    assert ("/daemon/watchdog", {"enabled": False}) in calls
    assert not any(path == "/daemon/stop" for path, _json in calls)
    assert not any(path in {"/daemon/start", "/daemon/restart"} for path, _json in calls)
    daemon_action = next(action for action in payload["actions"] if action["id"] == "reachy_daemon")
    assert "left running for diagnostics" in daemon_action["detail"]
    settle_action = next(action for action in payload["actions"] if action["id"] == "settle")
    assert settle_action["ok"] is False
    assert "motor power" in settle_action["detail"]


@pytest.mark.asyncio
async def test_daemon_management_allowed_when_body_motion_locked(monkeypatch):
    calls: list[tuple[str, str]] = []

    async def fake_forward(method: str, path: str, **_kwargs):
        calls.append((method, path))
        return {"ok": True, "path": path}

    monkeypatch.setattr(reachy, "_host_agent_forward", fake_forward)
    monkeypatch.setattr(
        reachy,
        "body_motion_allowed",
        lambda *, surface="unknown": {"allowed": False, "reason": "body_motion_disabled"},
    )

    start_payload = await reachy.daemon_start()
    restart_payload = await reachy.daemon_restart()

    assert start_payload["path"] == "/daemon/start"
    assert restart_payload["path"] == "/daemon/restart"
    assert calls == [("POST", "/daemon/start"), ("POST", "/daemon/restart")]


@pytest.mark.asyncio
async def test_movement_stays_blocked_when_body_motion_locked(monkeypatch):
    monkeypatch.setattr(
        reachy,
        "body_motion_allowed",
        lambda *, surface="unknown": {"allowed": False, "reason": "body_motion_disabled"},
    )

    with pytest.raises(HTTPException) as exc:
        await reachy.move_head(reachy.MoveRequest())

    assert exc.value.status_code == 423
    assert exc.value.detail["error"] == "body_motion_locked"
    assert exc.value.detail["surface"] == "move_head"


@pytest.mark.asyncio
async def test_move_head_preserves_current_head_translation(monkeypatch):
    service = ReachyService.__new__(ReachyService)
    captured: dict[str, object] = {}

    async def fake_get_full_state(**kwargs):
        captured["state_kwargs"] = kwargs
        return {"head_pose": {"x": 0.12, "y": -0.03, "z": 0.04}}

    async def fake_goto(**kwargs):
        captured["goto_kwargs"] = kwargs
        return {"uuid": "move-1"}

    monkeypatch.setattr(service, "get_full_state", fake_get_full_state)
    monkeypatch.setattr(service, "goto", fake_goto)

    result = await service.move_head(roll=1.0, pitch=2.0, yaw=3.0, duration=0.4)

    assert result == {"uuid": "move-1"}
    assert captured["state_kwargs"] == {
        "with_body_yaw": False,
        "with_antenna_positions": False,
        "with_doa": False,
        "timeout": 2.0,
        "quiet": True,
    }
    goto_kwargs = captured["goto_kwargs"]
    assert goto_kwargs["duration"] == 0.4
    assert goto_kwargs["head_pose"]["x"] == 0.12
    assert goto_kwargs["head_pose"]["y"] == -0.03
    assert goto_kwargs["head_pose"]["z"] == 0.04
    assert goto_kwargs["head_pose"]["yaw"] == pytest.approx(0.0523598776)


@pytest.mark.asyncio
async def test_daemon_retry_scan_reports_motor_bus_missing(monkeypatch):
    calls: list[str] = []

    async def fake_get_safe(path: str, **_kwargs):
        if path == "/daemon/status":
            return {"running": True}
        return {}

    async def fake_forward(method: str, path: str, **_kwargs):
        calls.append(f"{method} {path}")
        return {"ok": True, "pid": 1234}

    async def fake_wait(_service, **_kwargs):
        return {"ok": True, "detail": "Daemon API is ready."}

    async def fake_status(actions=None):
        return {
            "state": "degraded",
            "actions": actions or [],
            "robot_ready": False,
            "robot_detail": "Reachy USB is visible, but the motor bus is not detected.",
            "hardware_issues": {
                "active": True,
                "power_issue": True,
                "issues": [{"id": "motors_unpowered"}],
            },
            "body_activity": "unknown",
            "recent_activity": [],
        }

    async def fake_sleep(_seconds: float):
        return None

    monkeypatch.setattr(reachy, "_host_agent_get_safe", fake_get_safe)
    monkeypatch.setattr(reachy, "_host_agent_forward", fake_forward)
    monkeypatch.setattr(reachy, "_wait_for_daemon_ready", fake_wait)
    monkeypatch.setattr(reachy, "_assistant_status_payload", fake_status)
    monkeypatch.setattr(reachy, "get_reachy_service", lambda: object())
    monkeypatch.setattr(reachy.asyncio, "sleep", fake_sleep)

    payload = await reachy.daemon_retry_scan(reachy.DaemonRetryScanRequest(reason="test"))

    assert calls == ["POST /daemon/restart"]
    assert payload["ok"] is False
    assert "motor power/bus is missing" in payload["detail"]
    assert payload["hardware_issues"]["power_issue"] is True


@pytest.mark.asyncio
async def test_assistant_activate_blocks_daemon_start_after_recent_overload(monkeypatch):
    service = _FakeReachyService(
        connected=False,
        daemon_status={"error": "Robot not connected", "connected": False},
    )
    presence = _FakePresence()
    calls: list[tuple[str, dict | None]] = []

    async def fake_status(actions=None):
        return {
            "state": "degraded",
            "steps": [
                reachy._assistant_step("zero_api", "Zero API", "ready"),
                reachy._assistant_step("host_agent", "Host", "ready"),
                reachy._assistant_step("reachy_daemon", "Daemon", "degraded"),
                reachy._assistant_step("watchdog", "Watchdog", "degraded"),
                reachy._assistant_step("robot", "Robot", "degraded"),
                reachy._assistant_step("voice_backend", "Voice", "ready"),
                reachy._assistant_step("persona", "Persona", "ready"),
            ],
            "actions": actions or [],
            "daemon": {"running": False, "pid": None},
            "hardware_issues": {
                "active": True,
                "power_issue": False,
                "faults": [{"motor": "stewart_3", "error": "['Overload Error']", "count": 44}],
            },
            "motion_sources": [
                {
                    "id": "hardware_faults",
                    "active": True,
                    "raw": {
                        "active": True,
                        "faults": [{"motor": "stewart_3", "error": "['Overload Error']", "count": 44}],
                    },
                }
            ],
            "body_activity": "shaky",
            "recent_activity": [],
        }

    async def fake_post(path: str, *, json: dict | None = None, timeout: float = 10.0):
        calls.append((path, json))
        return {"ok": True, "path": path}

    import app.services.reachy_realtime.config_store as config_store

    monkeypatch.setattr(reachy, "get_reachy_service", lambda: service)
    monkeypatch.setattr(reachy, "get_voice_loop_service", lambda: _FakeVoiceLoop("assistant"))
    monkeypatch.setattr(reachy, "get_reachy_presence_service", lambda: presence)
    monkeypatch.setattr(reachy, "_assistant_status_payload", fake_status)
    monkeypatch.setattr(reachy, "_host_agent_post_safe", fake_post)
    monkeypatch.setattr(reachy, "body_motion_allowed", lambda *, surface="unknown": {"allowed": True})
    monkeypatch.setattr(config_store, "update_config", lambda patch: {"profile": patch.get("profile")})

    payload = await reachy.assistant_activate(
        reachy.AssistantActivationRequest(start_daemon=True, enable_body_motion=True)
    )

    assert ("/daemon/watchdog", {"enabled": False}) in calls
    assert not any(path in {"/daemon/start", "/daemon/restart"} for path, _json in calls)
    daemon_action = next(action for action in payload["actions"] if action["id"] == "reachy_daemon")
    settle_action = next(action for action in payload["actions"] if action["id"] == "settle")
    assert daemon_action["ok"] is False
    assert "actuator" in daemon_action["detail"]
    assert settle_action["ok"] is False
    assert "actuator" in settle_action["detail"]


@pytest.mark.asyncio
async def test_assistant_activate_allows_start_after_stale_overload(monkeypatch):
    service = _FakeReachyService(
        connected=False,
        daemon_status={"error": "Robot not connected", "connected": False},
    )
    presence = _FakePresence()
    calls: list[tuple[str, dict | None]] = []

    async def fake_status(actions=None):
        return {
            "state": "offline",
            "steps": [
                reachy._assistant_step("zero_api", "Zero API", "ready"),
                reachy._assistant_step("host_agent", "Host", "ready"),
                reachy._assistant_step("reachy_daemon", "Daemon", "offline"),
                reachy._assistant_step("watchdog", "Watchdog", "degraded"),
                reachy._assistant_step("robot", "Robot", "offline"),
                reachy._assistant_step("voice_backend", "Voice", "ready"),
                reachy._assistant_step("persona", "Persona", "ready"),
            ],
            "actions": actions or [],
            "daemon": {"running": False, "pid": None},
            "hardware_issues": {
                "active": False,
                "stale": True,
                "power_issue": False,
                "faults": [{"motor": "stewart_3", "error": "['Overload Error']", "count": 44}],
            },
            "motion_sources": [
                {
                    "id": "hardware_faults",
                    "active": False,
                    "raw": {
                        "active": False,
                        "stale": True,
                        "faults": [{"motor": "stewart_3", "error": "['Overload Error']", "count": 44}],
                    },
                }
            ],
            "body_activity": "unknown",
            "recent_activity": [],
        }

    async def fake_post(path: str, *, json: dict | None = None, timeout: float = 10.0):
        calls.append((path, json))
        return {"ok": True, "path": path}

    import app.services.reachy_realtime.config_store as config_store

    monkeypatch.setattr(reachy, "get_reachy_service", lambda: service)
    monkeypatch.setattr(reachy, "get_voice_loop_service", lambda: _FakeVoiceLoop("assistant"))
    monkeypatch.setattr(reachy, "get_reachy_presence_service", lambda: presence)
    monkeypatch.setattr(reachy, "_assistant_status_payload", fake_status)
    monkeypatch.setattr(reachy, "_host_agent_post_safe", fake_post)
    monkeypatch.setattr(reachy, "body_motion_allowed", lambda *, surface="unknown": {"allowed": True})
    monkeypatch.setattr(config_store, "update_config", lambda patch: {"profile": patch.get("profile")})

    await reachy.assistant_activate(
        reachy.AssistantActivationRequest(start_daemon=True, enable_body_motion=True)
    )

    assert ("/daemon/watchdog", {"enabled": False}) in calls
    assert any(path == "/daemon/start" for path, _json in calls)


@pytest.mark.asyncio
async def test_assistant_settle_stops_sources_and_neutralizes(monkeypatch):
    service = _FakeReachyService(
        connected=True,
        daemon_status={"type": "daemon_status", "state": "running"},
        state_probe={"control_mode": "enabled", "head_pose": {"roll": 0, "pitch": 0, "yaw": 0}},
    )
    presence = _FakePresence()

    async def fake_suspend_all_realtime_motion(reason: str = "settle"):
        return {"active_sessions": 1, "suspended": 1, "reason": reason}

    monkeypatch.setattr(reachy, "get_reachy_service", lambda: service)
    monkeypatch.setattr(reachy, "get_reachy_presence_service", lambda: presence)
    monkeypatch.setattr(reachy, "body_motion_allowed", lambda *, surface="unknown": {"allowed": True})

    import app.services.reachy_realtime.session as session_module
    monkeypatch.setattr(session_module, "suspend_all_realtime_motion", fake_suspend_all_realtime_motion)

    reachy._ASSISTANT_ACTIVITY.clear()
    payload = await reachy.assistant_settle(
        reachy.AssistantSettleRequest(reason="test", neutral_pose="default")
    )
    assert payload["ok"] is True
    assert payload["state"] == "ready"
    assert ("stop_all_moves", None) in service.calls
    assert any(name == "settle_neutral" for name, _body in service.calls)
    assert next(action for action in payload["actions"] if action["id"] == "meeting")["result"]["play_ack"] is False
    assert next(action for action in payload["actions"] if action["id"] == "pomodoro")["result"]["play_ack"] is False
    assert payload["body_activity"] in {"still", "unknown"}
    assert payload["recent_activity"][0]["event"] == "settle"


@pytest.mark.asyncio
async def test_assistant_settle_keeps_motors_enabled_for_transient_jitter(monkeypatch):
    service = _FakeReachyService(
        connected=True,
        daemon_status={"type": "daemon_status", "state": "running"},
        state_probe={"control_mode": "enabled", "head_pose": {"roll": 0, "pitch": 0, "yaw": 0}},
    )
    presence = _FakePresence()
    motion_payloads = [
        {
            "state": "degraded",
            "sources": [],
            "active_source_ids": [],
            "body_activity": "shaky",
            "pose_jitter": {"available": True, "samples": 3, "shaky": True},
        },
        {
            "state": "ready",
            "sources": [],
            "active_source_ids": [],
            "body_activity": "still",
            "pose_jitter": {"available": True, "samples": 3, "shaky": False},
        },
    ]

    async def fake_motion_sources(**_kwargs):
        return motion_payloads.pop(0)

    async def fake_sleep(_seconds: float):
        return None

    monkeypatch.setattr(reachy, "get_reachy_service", lambda: service)
    monkeypatch.setattr(reachy, "get_reachy_presence_service", lambda: presence)
    monkeypatch.setattr(reachy, "_motion_sources_payload", fake_motion_sources)
    monkeypatch.setattr(reachy.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(reachy, "body_motion_allowed", lambda *, surface="unknown": {"allowed": True})

    payload = await reachy.assistant_settle(
        reachy.AssistantSettleRequest(reason="test", keep_motors_enabled=True)
    )

    assert payload["ok"] is True
    assert payload["body_activity"] == "still"
    assert not any(action["id"] == "safe_motor_pause" for action in payload["actions"])
    assert ("set_motor_mode", {"mode": "disabled"}) not in service.calls


@pytest.mark.asyncio
async def test_assistant_settle_pauses_motors_when_jitter_remains(monkeypatch):
    service = _FakeReachyService(
        connected=True,
        daemon_status={"type": "daemon_status", "state": "running"},
        state_probe={"control_mode": "enabled", "head_pose": {"roll": 0, "pitch": 0, "yaw": 0}},
    )
    presence = _FakePresence()
    shaky_payload = {
        "state": "degraded",
        "sources": [],
        "active_source_ids": [],
        "body_activity": "shaky",
        "pose_jitter": {"available": True, "samples": 3, "shaky": True},
    }
    motion_payloads = [
        shaky_payload,
        shaky_payload,
        shaky_payload,
        {
            "state": "ready",
            "sources": [],
            "active_source_ids": [],
            "body_activity": "still",
            "pose_jitter": {"available": True, "samples": 3, "shaky": False},
        },
    ]

    async def fake_motion_sources(**_kwargs):
        return motion_payloads.pop(0)

    async def fake_sleep(_seconds: float):
        return None

    monkeypatch.setattr(reachy, "get_reachy_service", lambda: service)
    monkeypatch.setattr(reachy, "get_reachy_presence_service", lambda: presence)
    monkeypatch.setattr(reachy, "_motion_sources_payload", fake_motion_sources)
    monkeypatch.setattr(reachy.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(reachy, "body_motion_allowed", lambda *, surface="unknown": {"allowed": True})

    payload = await reachy.assistant_settle(
        reachy.AssistantSettleRequest(reason="test", keep_motors_enabled=True)
    )

    assert payload["ok"] is True
    assert payload["body_activity"] == "still"
    assert any(action["id"] == "neutral_pose_retry" for action in payload["actions"])
    assert any(action["id"] == "safe_motor_pause" for action in payload["actions"])
    assert ("set_motor_mode", {"mode": "disabled"}) in service.calls


@pytest.mark.asyncio
async def test_assistant_settle_disables_motors_on_hardware_fault(monkeypatch):
    service = _FakeReachyService(
        connected=True,
        daemon_status={"type": "daemon_status", "state": "running"},
        state_probe={"control_mode": "enabled", "head_pose": {"roll": 0, "pitch": 0, "yaw": 0}},
    )
    presence = _FakePresence()

    async def fake_faults():
        return {
            "available": True,
            "active": True,
            "faults": [{"motor": "left_antenna", "error": "['Overload Error']", "count": 7}],
        }

    async def fake_post(path: str, *, json: dict | None = None, timeout: float = 10.0):
        return {"ok": True, "path": path}

    async def fake_sleep(_seconds: float):
        return None

    monkeypatch.setattr(reachy, "get_reachy_service", lambda: service)
    monkeypatch.setattr(reachy, "get_reachy_presence_service", lambda: presence)
    monkeypatch.setattr(reachy, "_daemon_hardware_faults_safe", fake_faults)
    monkeypatch.setattr(reachy, "_host_agent_post_safe", fake_post)
    monkeypatch.setattr(reachy.asyncio, "sleep", fake_sleep)

    payload = await reachy.assistant_settle(reachy.AssistantSettleRequest(reason="test"))

    assert payload["ok"] is True
    assert ("set_motor_mode", {"mode": "disabled"}) in service.calls
    assert not any(name == "settle_neutral" for name, _body in service.calls)
    assert next(action for action in payload["actions"] if action["id"] == "hardware_faults")["ok"] is True


@pytest.mark.asyncio
async def test_assistant_settle_catches_delayed_overload_after_neutral(monkeypatch):
    service = _FakeReachyService(
        connected=True,
        daemon_status={"type": "daemon_status", "state": "running"},
        state_probe={"control_mode": "enabled", "head_pose": {"roll": 0, "pitch": 0, "yaw": 0}},
    )
    presence = _FakePresence()
    active_fault = {
        "available": True,
        "active": True,
        "power_issue": False,
        "faults": [{"motor": "stewart_3", "error": "['Overload Error']", "count": 4}],
    }
    fault_payloads = [
        {"available": True, "active": False, "faults": [], "power_issue": False},
        active_fault,
    ]
    host_posts: list[tuple[str, dict | None]] = []

    async def fake_faults():
        return fault_payloads.pop(0) if fault_payloads else active_fault

    async def fake_motion_sources(**kwargs):
        hardware = kwargs.get("hardware_faults") or {}
        active = bool(hardware.get("active"))
        return {
            "state": "degraded" if active else "ready",
            "sources": [{"id": "hardware_faults", "active": active, "raw": hardware}],
            "active_source_ids": ["hardware_faults"] if active else [],
            "body_activity": "unknown" if active else "still",
            "pose_jitter": {"available": True, "samples": 3, "shaky": False},
        }

    async def fake_post(path: str, *, json: dict | None = None, timeout: float = 10.0):
        host_posts.append((path, json))
        return {"ok": True, "path": path}

    async def fake_sleep(_seconds: float):
        return None

    monkeypatch.setattr(reachy, "get_reachy_service", lambda: service)
    monkeypatch.setattr(reachy, "get_reachy_presence_service", lambda: presence)
    monkeypatch.setattr(reachy, "_daemon_hardware_faults_safe", fake_faults)
    monkeypatch.setattr(reachy, "_motion_sources_payload", fake_motion_sources)
    monkeypatch.setattr(reachy, "_host_agent_post_safe", fake_post)
    monkeypatch.setattr(reachy.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(reachy, "body_motion_allowed", lambda *, surface="unknown": {"allowed": True})

    payload = await reachy.assistant_settle(
        reachy.AssistantSettleRequest(reason="test", keep_motors_enabled=True, neutral_pose="default")
    )

    assert payload["ok"] is False
    assert ("set_motor_mode", {"mode": "disabled"}) in service.calls
    assert ("/daemon/watchdog", {"enabled": False}) in host_posts
    assert any(path == "/daemon/stop" for path, _json in host_posts)
    assert next(action for action in payload["actions"] if action["id"] == "hardware_faults")["ok"] is True


def test_assistant_tool_specs_are_available_for_profile():
    names = {spec["name"] for spec in tool_registry.get_tool_specs(enabled=["get_schedule"])}
    assert "get_schedule" in names
    assert "task_status" in names


@pytest.mark.asyncio
async def test_start_focus_timer_tool(monkeypatch):
    presence = _FakePresence()

    import app.services.reachy_presence_service as presence_module

    monkeypatch.setattr(presence_module, "get_reachy_presence_service", lambda: presence)
    deps = ToolDependencies(motion=MotionDispatcher())
    result = await tool_registry.dispatch(
        "start_focus_timer",
        json.dumps({"focus_minutes": 30, "break_minutes": 7}),
        deps,
        BackgroundToolManager(),
    )
    assert result["active"] is True
    assert result["focus_minutes"] == 30
    assert result["break_minutes"] == 7
