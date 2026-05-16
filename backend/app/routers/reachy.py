"""
Reachy Mini robot API endpoints.

Thin HTTP layer over app.services.reachy_service. The service talks to the
Pollen Robotics Reachy Mini desktop daemon's REST API.
"""

import asyncio
import copy
import os
import re
import time
from collections import deque
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, HTTPException, Query, Response, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import Any, Literal, Optional
import httpx
import structlog

from app.infrastructure.config import get_settings
from app.services.reachy_service import (
    get_reachy_service,
    get_recent_motions,
    EMOTION_MOVES,
)
from app.services.reachy_motion_policy import body_motion_allowed, body_motion_locked_payload
from app.services.reachy_motion_library import (
    ALL_CLIPS,
    DANCE_CLIPS,
    EMOTION_CLIPS,
    categories,
    clip_to_dict,
    get_clip,
    resolve_motion,
)
from app.services.reachy_personas import (
    PERSONAS,
    get_persona,
    persona_to_dict,
)
from app.services.reachy_emotion_parser import parse_and_strip
from app.services.reachy_presence_service import get_reachy_presence_service
from app.services.reachy_sequence_service import get_reachy_sequence_service
from app.services.voice_loop_service import get_voice_loop_service
from app.models.reachy_sequence import (
    SequenceCreate,
    SequenceUpdate,
)

router = APIRouter()
logger = structlog.get_logger()
_ASSISTANT_ACTIVITY: deque[dict[str, Any]] = deque(maxlen=12)
_LAST_HARDWARE_FAULTS: dict[str, Any] | None = None
_LAST_HARDWARE_FAULTS_AT: float = 0.0
_HARDWARE_FAULT_CACHE_TTL_S = 15 * 60
_HARDWARE_FAULT_ACTIVE_WINDOW_S = 60 * 60
_LAST_STATE_PROBE: dict[str, Any] | None = None
_LAST_STATE_PROBE_AT: float = 0.0
_STATE_PROBE_CACHE_TTL_S = 5.0
_STATE_PROBE_FRESH_CACHE_S = float(os.getenv("ZERO_REACHY_STATE_PROBE_FRESH_SECONDS", "1.0"))
_STATE_PROBE_STALE_CACHE_S = max(
    1.0,
    float(os.getenv("ZERO_REACHY_STATE_PROBE_STALE_SECONDS", "2.0")),
)
_STATE_PROBE_LOCK = asyncio.Lock()
_HOST_AGENT_GOOD_CACHE: dict[str, tuple[float, dict]] = {}
_HOST_AGENT_STALE_CACHE_S = float(os.getenv("ZERO_HOST_AGENT_STALE_CACHE_SECONDS", "5.0"))
_REACHY_STATUS_FAST_CACHE: tuple[float, int, dict[str, Any]] | None = None
_REACHY_STATUS_FAST_CACHE_S = float(os.getenv("ZERO_REACHY_STATUS_CACHE_S", "0.75"))
_ASSISTANT_STATUS_FAST_CACHE: tuple[float, dict[str, Any]] | None = None
_ASSISTANT_STATUS_FAST_CACHE_S = float(os.getenv("ZERO_REACHY_ASSISTANT_STATUS_CACHE_S", "1.0"))
_CONTEXT_DEBUG_CACHE: dict[tuple[str | None, bool], tuple[float, dict[str, Any]]] = {}
_CONTEXT_DEBUG_CACHE_S = float(os.getenv("ZERO_REACHY_CONTEXT_DEBUG_CACHE_S", "60.0"))
_CONTEXT_DEBUG_TIMEOUT_S = float(os.getenv("ZERO_REACHY_CONTEXT_DEBUG_TIMEOUT_S", "0.75"))

def _configured_local_timezone() -> ZoneInfo:
    zone_name = os.getenv("ZERO_LOCAL_TIMEZONE", "America/Chicago")
    try:
        return ZoneInfo(zone_name)
    except ZoneInfoNotFoundError:
        logger.warning("invalid_local_timezone", zone_name=zone_name)
        return ZoneInfo("UTC")


_LOCAL_TZ = _configured_local_timezone()


def _body_motion_http_guard(surface: str) -> None:
    if body_motion_allowed(surface=surface).get("allowed"):
        return
    raise HTTPException(423, body_motion_locked_payload(surface=surface))


# --- Request Models ---

class MoveRequest(BaseModel):
    roll: float = Field(0.0, description="Roll angle in degrees")
    pitch: float = Field(0.0, description="Pitch angle in degrees")
    yaw: float = Field(0.0, description="Yaw angle in degrees")
    duration: float = Field(1.0, description="Movement duration in seconds")


class LookAtRequest(BaseModel):
    x: float = Field(..., description="X coordinate in meters")
    y: float = Field(..., description="Y coordinate in meters")
    z: float = Field(..., description="Z coordinate in meters")
    duration: float = Field(1.0, description="Movement duration in seconds")


class AntennasRequest(BaseModel):
    left_angle: float = Field(0.0, description="Left antenna angle in degrees")
    right_angle: float = Field(0.0, description="Right antenna angle in degrees")
    duration: float = Field(0.5, description="Movement duration in seconds")


class EmotionRequest(BaseModel):
    emotion: str = Field(..., description="Emotion clip name or alias (e.g. 'happy', 'cheerful1', 'thank you')")


class DanceRequest(BaseModel):
    dance: str = Field(..., description="Dance clip name or alias (e.g. 'simple_nod', 'jackson_square', 'spin')")


class MotionPlayRequest(BaseModel):
    name: str = Field(..., description="Clip name, alias, or free-form LLM tag")
    kind: Optional[Literal["emotion", "dance"]] = Field(None, description="Constrain resolution to one library")


class SayRequest(BaseModel):
    text: str = Field(..., description="Text to speak", max_length=2000)


class PlaySoundRequest(BaseModel):
    file: str = Field(..., description="Filename previously uploaded to the daemon")


class VolumeRequest(BaseModel):
    volume: int = Field(..., ge=0, le=100)


class MotorModeRequest(BaseModel):
    mode: str = Field(..., description="MotorControlMode value, e.g. 'enabled' or 'disabled'")


# --- Status / State ---

def _host_agent_base() -> str | None:
    url = (
        get_settings().host_agent_url
        or os.getenv("ZERO_HOST_AGENT_URL")
        or os.getenv("HOST_AGENT_URL")
        or "http://host.docker.internal:18796"
    )
    return url.rstrip("/") if url else None


async def _host_agent_forward(
    method: str,
    path: str,
    *,
    json: dict | None = None,
    params: dict | None = None,
    timeout: float = 10.0,
    auth_header: str | None = None,
) -> dict:
    base = _host_agent_base()
    if not base:
        raise HTTPException(503, "ZERO_HOST_AGENT_URL not configured")
    headers: dict[str, str] = {}
    if auth_header:
        headers["Authorization"] = auth_header
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.request(
                method,
                f"{base}{path}",
                json=json,
                params=params,
                headers=headers or None,
            )
            if resp.status_code >= 400:
                raise HTTPException(resp.status_code, resp.text)
            return resp.json() if resp.content else {}
    except httpx.RequestError as e:
        logger.warning("host_agent_unreachable", url=base, path=path, error=str(e))
        raise HTTPException(
            503,
            {
                "status": "host_agent_unreachable",
                "url": base,
                "path": path,
                "detail": str(e) or type(e).__name__,
            },
        )


async def _host_agent_get_safe(path: str, *, timeout: float = 3.0, attempts: int = 2) -> dict | None:
    """Non-raising variant. Returns a structured `host_agent_unreachable` payload
    (rather than None) when host_agent is unavailable AND no cached response is
    fresh enough — so the UI can render an explicit failure state instead of
    silently rendering 'nothing happened'.
    """
    base = _host_agent_base()
    if not base:
        return {
            "status": "host_agent_unreachable",
            "detail": "ZERO_HOST_AGENT_URL not configured",
            "stale": True,
        }
    last_error: str | None = None
    for attempt in range(max(1, attempts)):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(f"{base}{path}")
                if resp.status_code >= 400:
                    last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
                    if attempt >= max(1, attempts) - 1:
                        break
                    await asyncio.sleep(0.15)
                    continue
                payload = resp.json() if resp.content else {}
                if isinstance(payload, dict):
                    _HOST_AGENT_GOOD_CACHE[path] = (time.monotonic(), dict(payload))
                return payload
        except Exception as e:
            last_error = str(e) or type(e).__name__
            if attempt >= max(1, attempts) - 1:
                break
            await asyncio.sleep(0.15)

    cached = _HOST_AGENT_GOOD_CACHE.get(path)
    if cached is not None:
        ts, payload = cached
        age = time.monotonic() - ts
        if age <= _HOST_AGENT_STALE_CACHE_S:
            stale_payload = dict(payload)
            stale_payload["status_stale"] = True
            stale_payload["cache_age_seconds"] = round(age, 3)
            stale_payload["last_error"] = last_error
            return stale_payload
    logger.warning(
        "host_agent_unreachable_no_cache",
        url=base,
        path=path,
        error=last_error,
    )
    return {
        "status": "host_agent_unreachable",
        "url": base,
        "path": path,
        "detail": last_error or "unknown",
        "stale": True,
    }


def _host_agent_cached(path: str, *, max_age_s: float | None = None) -> dict | None:
    cached = _HOST_AGENT_GOOD_CACHE.get(path)
    if cached is None:
        return None
    ts, payload = cached
    age = time.monotonic() - ts
    if max_age_s is not None and age > max_age_s:
        return None
    out = dict(payload)
    out["status_stale"] = True
    out["cache_age_seconds"] = round(age, 3)
    return out


async def _host_agent_post_safe(
    path: str,
    *,
    json: dict | None = None,
    timeout: float = 10.0,
) -> dict:
    """Non-raising POST variant used by the assistant startup workflow."""
    try:
        return await _host_agent_forward("POST", path, json=json, timeout=timeout)
    except HTTPException as e:
        return {"error": e.detail, "status_code": e.status_code}
    except Exception as e:
        return {"error": str(e), "status_code": 500}


ASSISTANT_REPAIR_COMMAND = (
    r"powershell.exe -ExecutionPolicy Bypass -File C:\code\zero\scripts\start-zero.ps1"
)
ASSISTANT_SETTLE_TIMEOUT_S = 20.0


class AssistantActivationRequest(BaseModel):
    persona: str = Field("companion", min_length=1, max_length=64)
    voice_mode: Literal["live"] = "live"
    enable_ambient: bool = False
    start_daemon: bool = False
    wake_robot: bool = False
    enable_body_motion: bool = False


class AssistantSettleRequest(BaseModel):
    keep_motors_enabled: bool = False
    neutral_pose: Literal["default", "skip"] = "skip"
    reason: str = Field("user", min_length=1, max_length=80)


def _record_assistant_activity(
    event: str,
    detail: str,
    *,
    ok: bool = True,
    state: str | None = None,
    body_activity: str | None = None,
) -> None:
    _ASSISTANT_ACTIVITY.appendleft({
        "at": time.time(),
        "event": event,
        "detail": detail,
        "ok": ok,
        "state": state,
        "body_activity": body_activity,
    })


def _recent_assistant_activity() -> list[dict[str, Any]]:
    return list(_ASSISTANT_ACTIVITY)


def _assistant_step(
    step_id: str,
    label: str,
    state: Literal["ready", "repair_required", "starting", "degraded", "offline"],
    detail: str = "",
    action: str | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": step_id,
        "label": label,
        "state": state,
        "detail": detail,
    }
    if action:
        out["action"] = action
    return out


def _derive_assistant_state(steps: list[dict[str, Any]]) -> str:
    states = {str(s.get("id")): str(s.get("state")) for s in steps}
    if states.get("host_agent") == "repair_required":
        return "repair_required"
    if any(s.get("state") == "degraded" for s in steps):
        return "degraded"
    if states.get("reachy_daemon") in {"starting"}:
        return "starting"
    if states.get("reachy_daemon") == "offline":
        return "offline"
    if all(s.get("state") == "ready" for s in steps):
        return "ready"
    return "offline"


def _assistant_has_motor_power_issue(payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    hardware = payload.get("hardware_issues")
    if isinstance(hardware, dict) and hardware.get("power_issue"):
        return True
    for source in payload.get("motion_sources") or []:
        if not isinstance(source, dict) or source.get("id") != "hardware_faults":
            continue
        raw = source.get("raw")
        if isinstance(raw, dict) and raw.get("power_issue"):
            return True
    return False


def _assistant_has_recent_hardware_fault(payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    hardware = payload.get("hardware_issues")
    if isinstance(hardware, dict) and (hardware.get("active") or hardware.get("power_issue")):
        return True
    for source in payload.get("motion_sources") or []:
        if not isinstance(source, dict) or source.get("id") != "hardware_faults":
            continue
        raw = source.get("raw")
        if source.get("active"):
            return True
        if isinstance(raw, dict) and (raw.get("active") or raw.get("power_issue")):
            return True
    return False


def _assistant_has_stale_hardware_fault_history(payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    candidates: list[dict[str, Any]] = []
    hardware = payload.get("hardware_issues")
    if isinstance(hardware, dict):
        candidates.append(hardware)
    for source in payload.get("motion_sources") or []:
        if not isinstance(source, dict) or source.get("id") != "hardware_faults":
            continue
        raw = source.get("raw")
        if isinstance(raw, dict):
            candidates.append(raw)
    return any(
        bool(item.get("stale") and item.get("faults") and not item.get("active") and not item.get("power_issue"))
        for item in candidates
    )


def _short_error(value: Any) -> str:
    text = str(value or "")
    return text if len(text) <= 220 else text[:217] + "..."


def _daemon_api_running(daemon_api: dict[str, Any]) -> bool:
    return daemon_api.get("state") == "running"


def _daemon_api_reachable(daemon_api: dict[str, Any]) -> bool:
    return bool(daemon_api) and daemon_api.get("connected") is not False and (
        _daemon_api_running(daemon_api)
        or daemon_api.get("type") == "daemon_status"
        or daemon_api.get("state") is not None
        or daemon_api.get("version") is not None
    )


def _daemon_reachable_from_state(
    daemon_api: dict[str, Any],
    *,
    supervisor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Represent a usable daemon when /api/state/full is fresher than /api/daemon/status."""
    backend_status = daemon_api.get("backend_status") if isinstance(daemon_api, dict) else None
    if not isinstance(backend_status, dict):
        backend_status = {
            "ready": None,
            "motor_control_mode": None,
            "detail": "Body state is reachable; daemon status metadata is retrying.",
        }
    direct_error = daemon_api.get("error") if isinstance(daemon_api, dict) else None
    if not direct_error and isinstance(daemon_api, dict):
        direct_error = daemon_api.get("direct_error")
    return {
        "type": "daemon_status",
        "state": "running",
        "connected": True,
        "via": daemon_api.get("via") if isinstance(daemon_api, dict) and daemon_api.get("via") else "state_probe",
        "daemon_route": daemon_api.get("daemon_route") if isinstance(daemon_api, dict) and daemon_api.get("daemon_route") else "state_probe",
        "daemon_direct_reachable": bool(isinstance(daemon_api, dict) and daemon_api.get("daemon_direct_reachable")),
        "status_stale": False,
        "direct_error": direct_error,
        "supervisor": supervisor if supervisor else daemon_api.get("supervisor") if isinstance(daemon_api, dict) else None,
        "backend_status": backend_status,
    }


def _direct_daemon_reachable(daemon_api: dict[str, Any]) -> bool:
    if daemon_api.get("daemon_direct_reachable") is True:
        return True
    return bool(daemon_api.get("via") == "direct" and _daemon_api_reachable(daemon_api))


async def _daemon_status_fast(
    service: Any,
    *,
    timeout: float = 0.35,
) -> dict[str, Any]:
    """Bound daemon metadata collection so UI polling cannot stall behind it."""
    task = asyncio.create_task(
        service.get_daemon_status(timeout=0.30, supervisor_timeout=0.20, quiet=True)
    )
    try:
        return await asyncio.wait_for(task, timeout=timeout)
    except Exception as e:
        task.cancel()
        return {
            "error": _short_error(e) or type(e).__name__,
            "connected": False,
            "via": "metadata_timeout",
            "daemon_route": "direct",
            "daemon_direct_reachable": False,
            "status_stale": True,
        }


def _daemon_error_text(daemon_api: dict[str, Any]) -> str | None:
    backend_status = daemon_api.get("backend_status")
    if isinstance(backend_status, dict) and backend_status.get("error"):
        return _short_error(backend_status.get("error"))
    if daemon_api.get("error"):
        return _short_error(daemon_api.get("error"))
    if daemon_api.get("direct_error"):
        return _short_error(daemon_api.get("direct_error"))
    supervisor = daemon_api.get("supervisor")
    if isinstance(supervisor, dict):
        blocker = supervisor.get("probe_blocker")
        if isinstance(blocker, dict) and blocker.get("detail"):
            return _short_error(blocker.get("detail"))
    detail = daemon_api.get("detail")
    if isinstance(detail, str) and detail:
        return _short_error(detail)
    return None


def _daemon_motor_power_issue(daemon_api: dict[str, Any]) -> bool:
    text = " ".join(
        str(value or "")
        for value in (
            _daemon_error_text(daemon_api),
            daemon_api.get("state"),
            daemon_api.get("detail"),
        )
    ).lower()
    return (
        "no motors detected" in text
        or "motor bus" in text
        or ("power supply" in text and "motor" in text)
    )


def _hardware_faults_with_daemon_error(
    hardware_faults: dict[str, Any],
    daemon_api: dict[str, Any],
) -> dict[str, Any]:
    if not _daemon_motor_power_issue(daemon_api):
        return hardware_faults
    merged = dict(hardware_faults or {})
    issues = [
        issue
        for issue in merged.get("issues", [])
        if isinstance(issue, dict)
    ]
    if not any(issue.get("id") == "motors_unpowered" for issue in issues):
        issues.append({
            "id": "motors_unpowered",
            "severity": "error",
            "title": "Reachy motor bus is not detected",
            "detail": (
                _daemon_error_text(daemon_api)
                or "USB serial is visible, but the daemon cannot see the motor bus. "
                "Check Reachy's motor power supply and motor/power connector."
            ),
        })
    merged.update({
        "available": True,
        "active": True,
        "power_issue": True,
        "stale": False,
        "issues": issues,
        "detail": issues[-1].get("detail") if issues else _daemon_error_text(daemon_api),
    })
    return merged


def _looks_like_robot_state(value: dict[str, Any]) -> bool:
    if not isinstance(value, dict) or value.get("error"):
        return False
    return any(
        key in value
        for key in (
            "head_pose",
            "body_yaw",
            "antenna_positions",
            "antennas_position",
            "control_mode",
            "doa",
        )
    )


def _robot_control_mode(
    daemon_api: dict[str, Any],
    state_probe: dict[str, Any] | None = None,
) -> str | None:
    if isinstance(state_probe, dict) and state_probe.get("control_mode") is not None:
        return str(state_probe.get("control_mode")).lower()
    backend_status = daemon_api.get("backend_status")
    if isinstance(backend_status, dict) and backend_status.get("motor_control_mode") is not None:
        return str(backend_status.get("motor_control_mode")).lower()
    return None


def _robot_ready_detail(
    daemon_api: dict[str, Any],
    state_probe: dict[str, Any],
    *,
    daemon_api_reachable: bool,
) -> tuple[bool, bool, str, str | None]:
    """Return (body_connected, body_ready, detail, control_mode)."""
    control_mode = _robot_control_mode(daemon_api, state_probe)
    if _looks_like_robot_state(state_probe):
        if control_mode == "disabled":
            return (
                True,
                False,
                "Robot body is reachable, but motors are disabled/asleep.",
                control_mode,
            )
        if control_mode:
            return (
                True,
                True,
                f"Robot body is reachable; motor control is {control_mode}.",
                control_mode,
            )
        return True, True, "Robot body state is responding.", control_mode

    daemon_error = _daemon_error_text(daemon_api)
    if daemon_error:
        return False, False, daemon_error, control_mode
    if isinstance(state_probe, dict) and state_probe.get("error"):
        return False, False, f"Body state probe failed: {_short_error(state_probe.get('error'))}", control_mode
    if daemon_api_reachable:
        return False, False, "Daemon API is reachable, but body state is not responding.", control_mode
    return False, False, "Robot body is unavailable until the daemon API is reachable.", control_mode


async def _fast_state_probe(
    service: Any,
    *,
    timeout: float = 0.8,
    allow_cached: bool = True,
) -> tuple[dict[str, Any], bool, bool, float | None]:
    """Read body state for UI polling without letting audio/DoA stalls freeze the console."""
    global _LAST_STATE_PROBE, _LAST_STATE_PROBE_AT

    def _cached_probe(age: float, *, stale: bool) -> dict[str, Any]:
        cached = dict(_LAST_STATE_PROBE or {})
        if stale:
            cached["stale"] = True
            cached["stale_age_seconds"] = round(age, 3)
        else:
            cached["cached_recent"] = True
            cached["cache_age_seconds"] = round(age, 3)
        return cached

    if allow_cached and _LAST_STATE_PROBE and _LAST_STATE_PROBE_AT:
        age = time.monotonic() - _LAST_STATE_PROBE_AT
        if age <= _STATE_PROBE_FRESH_CACHE_S:
            return _cached_probe(age, stale=False), True, False, age

    async def _read() -> dict[str, Any]:
        try:
            return await service.get_full_state(
                with_doa=False,
                timeout=timeout,
                quiet=True,
            )
        except TypeError as e:
            if "unexpected keyword" not in str(e):
                raise
            return await service.get_full_state(timeout=timeout, quiet=True)

    async with _STATE_PROBE_LOCK:
        if allow_cached and _LAST_STATE_PROBE and _LAST_STATE_PROBE_AT:
            age = time.monotonic() - _LAST_STATE_PROBE_AT
            if age <= _STATE_PROBE_FRESH_CACHE_S:
                return _cached_probe(age, stale=False), True, False, age

        try:
            state = await asyncio.wait_for(_read(), timeout=timeout + min(0.10, max(0.04, timeout * 0.5)))
        except Exception as e:
            state = {"error": str(e) or type(e).__name__, "connected": False}

        if _looks_like_robot_state(state):
            _LAST_STATE_PROBE = dict(state)
            _LAST_STATE_PROBE_AT = time.monotonic()
            return state, True, False, 0.0

        if allow_cached and _LAST_STATE_PROBE and _LAST_STATE_PROBE_AT:
            age = time.monotonic() - _LAST_STATE_PROBE_AT
            if age <= _STATE_PROBE_STALE_CACHE_S:
                cached = _cached_probe(age, stale=True)
                cached["refresh_error"] = state.get("error") if isinstance(state, dict) else None
                return cached, True, True, age

        return state if isinstance(state, dict) else {}, False, False, None


def _reachy_recommended_action(
    *,
    body_connected: bool,
    body_ready: bool,
    control_mode: str | None,
    daemon_api_reachable: bool,
    hardware_fault_active: bool = False,
    hardware_power_issue: bool = False,
) -> dict[str, Any]:
    if hardware_power_issue:
        return {
            "id": "check_motor_power",
            "label": "Check motor power",
            "detail": "Reachy USB is visible, but the motor bus is not detected. Check motor power and the motor/power connector, then retry hardware scan.",
        }
    if hardware_fault_active:
        return {
            "id": "inspect_hardware",
            "label": "Inspect hardware",
            "detail": "Body motion is protected until the active hardware fault is cleared.",
        }
    if body_connected and not body_ready and control_mode == "disabled":
        return {
            "id": "wake_robot",
            "label": "Wake Zero",
            "detail": "The daemon and body are reachable; enable motors before moving.",
        }
    if not daemon_api_reachable and not body_connected:
        return {
            "id": "start_daemon",
            "label": "Start daemon",
            "detail": "Start or restart the Zero robot daemon before probing the body.",
        }
    return {
        "id": "none",
        "label": "No action",
        "detail": "Zero robot status is consistent.",
    }


def _realtime_config_safe() -> dict[str, Any]:
    try:
        from app.routers.reachy_realtime import _enriched_config
        from app.services.reachy_realtime.config_store import load_config_masked
        return _enriched_config(load_config_masked())
    except Exception as e:
        logger.debug("assistant_realtime_config_unavailable", error=str(e))
        return {
            "backend": "local",
            "preferred_backend": "local",
            "realtime_available": True,
            "profile": "assistant",
        }


def _extract_move_count(value: Any) -> int:
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        for key in ("running", "moves", "active", "items", "value"):
            nested = value.get(key)
            if nested is not None:
                return _extract_move_count(nested)
        if any(value.get(key) for key in ("uuid", "id", "move_uuid")):
            return 1
    return 0


def _state_float(state: dict[str, Any], key: str) -> float | None:
    value = state.get(key)
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _pose_signature(state: dict[str, Any]) -> dict[str, float]:
    head = state.get("head_pose") if isinstance(state.get("head_pose"), dict) else {}
    antennas = state.get("antenna_positions") or state.get("antennas_position") or []
    sig: dict[str, float] = {}
    if isinstance(head, dict):
        for key in ("roll", "pitch", "yaw"):
            value = head.get(key)
            if isinstance(value, (int, float)):
                sig[f"head_{key}"] = float(value)
    body = _state_float(state, "body_yaw")
    if body is not None:
        sig["body_yaw"] = body
    if isinstance(antennas, list):
        for idx, value in enumerate(antennas[:2]):
            if isinstance(value, (int, float)):
                sig[f"antenna_{idx}"] = float(value)
    return sig


def _jitter_from_signatures(signatures: list[dict[str, float]]) -> dict[str, Any]:
    if len(signatures) < 2:
        return {"available": False, "samples": len(signatures), "shaky": False}
    keys = set().union(*(sig.keys() for sig in signatures))
    deltas: dict[str, float] = {}
    for key in keys:
        vals = [sig[key] for sig in signatures if key in sig]
        if len(vals) >= 2:
            deltas[key] = max(vals) - min(vals)
    head_delta = max(
        (deltas.get("head_roll", 0.0), deltas.get("head_pitch", 0.0), deltas.get("head_yaw", 0.0)),
        default=0.0,
    )
    body_delta = deltas.get("body_yaw", 0.0)
    antenna_delta = max((deltas.get("antenna_0", 0.0), deltas.get("antenna_1", 0.0)), default=0.0)
    shaky = head_delta > 0.03 or body_delta > 0.02 or antenna_delta > 0.04
    return {
        "available": bool(deltas),
        "samples": len(signatures),
        "shaky": shaky,
        "head_delta_rad": head_delta,
        "body_yaw_delta_rad": body_delta,
        "antenna_delta_rad": antenna_delta,
        "deltas": deltas,
    }


_MOTOR_HARDWARE_ERROR_RE = re.compile(
    r"Motor\s+'(?P<motor>[^']+)'\s+hardware errors:\s*(?P<errors>.*)$",
    re.IGNORECASE,
)
_MOTOR_NOT_FOUND_RE = re.compile(
    r"Motor\s+'(?P<motor>[^']+)'\s+\(ID\s+(?P<id>\d+)\)\s+not found on the bus",
    re.IGNORECASE,
)
_NO_MOTORS_RE = re.compile(
    r"No motors detected|motor bus is empty|motors are not powered",
    re.IGNORECASE,
)
_DAEMON_STARTED_SUCCESSFULLY_RE = re.compile(
    r"Daemon started successfully",
    re.IGNORECASE,
)
_DAEMON_LOG_TIMESTAMP_RE = re.compile(
    r"^(?P<stamp>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2},\d{3})"
)


def _daemon_log_timestamp(line: str) -> datetime | None:
    match = _DAEMON_LOG_TIMESTAMP_RE.match(line)
    if not match:
        return None
    try:
        return datetime.strptime(match.group("stamp"), "%Y-%m-%d %H:%M:%S,%f").replace(tzinfo=_LOCAL_TZ)
    except ValueError:
        return None


def _fault_age_seconds(last_at: datetime | None, now: datetime) -> float | None:
    if not last_at:
        return None
    return max(0.0, (now - last_at).total_seconds())


def _parse_iso_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _extract_motor_hardware_faults(
    log_payload: dict[str, Any] | None,
    *,
    now: datetime | None = None,
    active_window_s: float = _HARDWARE_FAULT_ACTIVE_WINDOW_S,
) -> dict[str, Any]:
    lines = log_payload.get("lines") if isinstance(log_payload, dict) else None
    if not isinstance(lines, list):
        return {"available": False, "active": False, "faults": [], "issues": [], "power_issue": False}

    now = now or datetime.now(_LOCAL_TZ)
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    missing_motors: dict[str, dict[str, Any]] = {}
    no_motors_at: datetime | None = None
    saw_no_motors_unknown_age = False
    last_no_motors_index = -1
    last_missing_index = -1
    last_clean_start_index = -1
    for idx, line in enumerate(lines):
        text = str(line or "")
        line_at = _daemon_log_timestamp(text)
        if _DAEMON_STARTED_SUCCESSFULLY_RE.search(text):
            last_clean_start_index = idx
        if _NO_MOTORS_RE.search(text):
            last_no_motors_index = idx
            if line_at:
                no_motors_at = max(no_motors_at, line_at) if no_motors_at else line_at
            else:
                saw_no_motors_unknown_age = True
        missing_match = _MOTOR_NOT_FOUND_RE.search(text)
        if missing_match:
            last_missing_index = idx
            motor = missing_match.group("motor").strip()
            item = missing_motors.setdefault(
                motor,
                {
                    "motor": motor,
                    "id": missing_match.group("id"),
                    "count": 0,
                    "last_line": "",
                    "last_at": None,
                    "last_age_seconds": None,
                    "active": True,
                    "stale": False,
                },
            )
            item["count"] += 1
            item["last_line"] = text
            if line_at:
                prior = item.get("last_at")
                item["last_at"] = max(prior, line_at) if isinstance(prior, datetime) else line_at
        match = _MOTOR_HARDWARE_ERROR_RE.search(text)
        if not match:
            continue
        motor = match.group("motor").strip()
        errors = match.group("errors").strip()
        if not errors and idx + 1 < len(lines):
            next_text = str(lines[idx + 1] or "").strip()
            if "error" in next_text.lower():
                errors = next_text
        if not errors:
            errors = "Unknown motor hardware error"
        key = (motor, errors)
        item = by_key.setdefault(
            key,
            {
                "motor": motor,
                "error": errors,
                "count": 0,
                "last_line": "",
                "last_at": None,
                "last_age_seconds": None,
                "active": True,
                "stale": False,
            },
        )
        item["count"] += 1
        item["last_line"] = text
        if line_at:
            prior = item.get("last_at")
            item["last_at"] = max(prior, line_at) if isinstance(prior, datetime) else line_at

    fault_items: list[dict[str, Any]] = []
    active_faults = False
    latest_fault_at: datetime | None = None
    for item in by_key.values():
        last_at = item.get("last_at") if isinstance(item.get("last_at"), datetime) else None
        age = _fault_age_seconds(last_at, now)
        active = age is None or age <= active_window_s
        latest_fault_at = max(latest_fault_at, last_at) if latest_fault_at and last_at else (last_at or latest_fault_at)
        item["last_age_seconds"] = age
        item["active"] = active
        item["stale"] = not active
        if last_at:
            item["last_at"] = last_at.isoformat()
        active_faults = active_faults or active
        fault_items.append(item)

    clean_start_after_missing = last_clean_start_index > max(last_no_motors_index, last_missing_index)
    missing_items: list[dict[str, Any]] = []
    active_missing = False
    for item in missing_motors.values():
        last_at = item.get("last_at") if isinstance(item.get("last_at"), datetime) else None
        age = _fault_age_seconds(last_at, now)
        active = (age is None or age <= active_window_s) and not clean_start_after_missing
        item["last_age_seconds"] = age
        item["active"] = active
        item["stale"] = not active
        if clean_start_after_missing:
            item["cleared_by_clean_daemon_start"] = True
        if last_at:
            item["last_at"] = last_at.isoformat()
        active_missing = active_missing or active
        missing_items.append(item)

    no_motors_age = _fault_age_seconds(no_motors_at, now)
    no_motors_active = (
        saw_no_motors_unknown_age
        or (no_motors_age is not None and no_motors_age <= active_window_s)
    ) and not clean_start_after_missing
    faults = sorted(fault_items, key=lambda item: item["count"], reverse=True)
    missing = sorted(missing_items, key=lambda item: item["motor"])
    power_issue = no_motors_active or (len(missing) >= 3 and active_missing)
    stale = bool(faults or missing or no_motors_at) and not (active_faults or power_issue)
    issues: list[dict[str, Any]] = []
    if power_issue:
        issues.append({
            "id": "motors_unpowered",
            "severity": "error",
            "title": "Reachy motor bus is not detected",
            "detail": (
                "USB serial is visible, but the daemon cannot see the motor bus. "
                "Check Reachy's motor power supply and motor/power connector."
            ),
            "missing_motors": missing,
        })
    return {
        "available": True,
        "active": active_faults or power_issue,
        "faults": faults,
        "issues": issues,
        "power_issue": power_issue,
        "stale": stale,
        "active_window_seconds": active_window_s,
        "last_fault_at": latest_fault_at.isoformat() if latest_fault_at else None,
        "last_fault_age_seconds": _fault_age_seconds(latest_fault_at, now),
        "no_motors_age_seconds": no_motors_age,
        "cleared_by_clean_daemon_start": clean_start_after_missing,
        "line_count": len(lines),
    }


def _merge_host_known_issues(
    hardware_faults: dict[str, Any],
    known_issues_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    """Fold host_agent structured issue hints into daemon-log hardware faults."""
    if not isinstance(known_issues_payload, dict):
        return hardware_faults
    items = known_issues_payload.get("items")
    if not isinstance(items, list):
        return hardware_faults

    issues = [
        issue
        for issue in hardware_faults.get("issues", [])
        if isinstance(issue, dict)
    ]
    issue_ids = {str(issue.get("id")) for issue in issues}
    power_issue = bool(hardware_faults.get("power_issue"))

    for item in items:
        if not isinstance(item, dict):
            continue
        issue_id = str(item.get("id") or "")
        if issue_id == "motors_unpowered":
            power_issue = True
            if issue_id not in issue_ids:
                issues.append({
                    "id": issue_id,
                    "severity": item.get("severity") or "error",
                    "title": "Reachy motor bus is not detected",
                    "detail": (
                        item.get("hint")
                        or "USB serial is visible, but the daemon cannot see the motor bus. "
                        "Check Reachy's motor power supply and motor/power connector."
                    ),
                })
                issue_ids.add(issue_id)

    if power_issue:
        hardware_faults = dict(hardware_faults)
        hardware_faults["available"] = True
        hardware_faults["active"] = True
        hardware_faults["power_issue"] = True
        hardware_faults["stale"] = False
        hardware_faults["issues"] = issues
    return hardware_faults


def _clear_faults_after_clean_daemon_start(
    hardware_faults: dict[str, Any],
    supervisor_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    """Ignore fault log lines that happened before the currently running daemon.

    Daemon logs are daily append-only files. If an overload happened, the user
    physically fixes the robot, and the daemon starts cleanly later in the same
    day, the old line is still in the tail and must not keep body controls
    latched forever. A new overload after this start will still be active.
    """
    if not isinstance(supervisor_payload, dict) or not supervisor_payload.get("running"):
        return hardware_faults
    if hardware_faults.get("power_issue"):
        return hardware_faults
    started_at = _parse_iso_datetime(supervisor_payload.get("started_at"))
    last_fault_at = _parse_iso_datetime(hardware_faults.get("last_fault_at"))
    if not started_at or not last_fault_at or last_fault_at >= started_at:
        return hardware_faults
    if not hardware_faults.get("faults"):
        return hardware_faults

    cleared = dict(hardware_faults)
    cleared["active"] = False
    cleared["stale"] = True
    cleared["cleared_by_clean_daemon_start"] = True
    cleared["cleared_by_daemon_started_at"] = started_at.isoformat()
    cleared["detail"] = "Previous motor fault happened before the current clean daemon start."
    cleared["faults"] = [
        {
            **fault,
            "active": False,
            "stale": True,
            "cleared_by_clean_daemon_start": True,
        }
        if isinstance(fault, dict)
        else fault
        for fault in hardware_faults.get("faults", [])
    ]
    return cleared


async def _daemon_hardware_faults_safe(
    *,
    supervisor: dict[str, Any] | None = None,
    fast: bool = False,
) -> dict[str, Any]:
    global _LAST_HARDWARE_FAULTS, _LAST_HARDWARE_FAULTS_AT
    if (
        _LAST_HARDWARE_FAULTS
        and time.monotonic() - _LAST_HARDWARE_FAULTS_AT < _HARDWARE_FAULT_CACHE_TTL_S
    ):
        cached = dict(_LAST_HARDWARE_FAULTS)
        if supervisor and supervisor.get("running"):
            cached = _clear_faults_after_clean_daemon_start(cached, supervisor)
            if not cached.get("active"):
                _LAST_HARDWARE_FAULTS = None
                _LAST_HARDWARE_FAULTS_AT = 0.0
                return cached
        else:
            cached["cached"] = True
            return cached

    logs_tail = 80 if fast else 160
    request_timeout = 0.75 if fast else 2.0
    logs_task = _host_agent_get_safe(f"/daemon/logs?tail={logs_tail}", timeout=request_timeout)
    issues_task = _host_agent_get_safe("/daemon/issues", timeout=request_timeout)
    supervisor_task = (
        asyncio.sleep(0, result=supervisor)
        if supervisor is not None
        else _host_agent_get_safe("/daemon/status", timeout=request_timeout)
    )
    logs, known_issues, supervisor_payload = await asyncio.gather(
        logs_task,
        issues_task,
        supervisor_task,
    )
    if fast and not isinstance(logs, dict) and not isinstance(known_issues, dict):
        return {
            "available": False,
            "active": False,
            "faults": [],
            "issues": [],
            "power_issue": False,
            "stale": False,
            "skipped": True,
            "detail": "Skipped on fast status path because daemon logs were unavailable.",
        }
    hardware_faults = _extract_motor_hardware_faults(logs)
    hardware_faults = _merge_host_known_issues(hardware_faults, known_issues)
    hardware_faults = _clear_faults_after_clean_daemon_start(hardware_faults, supervisor_payload)
    if hardware_faults.get("active"):
        _LAST_HARDWARE_FAULTS = hardware_faults
        _LAST_HARDWARE_FAULTS_AT = time.monotonic()
        return hardware_faults
    if hardware_faults.get("available") or hardware_faults.get("cleared_by_clean_daemon_start"):
        _LAST_HARDWARE_FAULTS = None
        _LAST_HARDWARE_FAULTS_AT = 0.0

    if (
        _LAST_HARDWARE_FAULTS
        and time.monotonic() - _LAST_HARDWARE_FAULTS_AT < _HARDWARE_FAULT_CACHE_TTL_S
    ):
        cached = dict(_LAST_HARDWARE_FAULTS)
        cached = _clear_faults_after_clean_daemon_start(cached, supervisor_payload)
        if not cached.get("active"):
            _LAST_HARDWARE_FAULTS = None
            _LAST_HARDWARE_FAULTS_AT = 0.0
            return cached
        cached["cached"] = True
        return cached
    return hardware_faults


async def _daemon_hardware_faults_for_supervisor(
    supervisor: dict[str, Any] | None,
    *,
    fast: bool = False,
) -> dict[str, Any]:
    """Call the hardware-fault helper with compatibility for test fakes."""
    try:
        return await _daemon_hardware_faults_safe(supervisor=supervisor, fast=fast)
    except TypeError as e:
        if "unexpected keyword" not in str(e):
            raise
        if fast:
            return {
                "available": False,
                "active": False,
                "faults": [],
                "issues": [],
                "power_issue": False,
                "stale": False,
                "skipped": True,
            }
        return await _daemon_hardware_faults_safe()



async def _measure_pose_jitter(
    service: Any,
    *,
    initial_state: dict[str, Any] | None = None,
    samples: int = 3,
    interval_s: float = 0.12,
) -> dict[str, Any]:
    signatures: list[dict[str, float]] = []
    if initial_state and _looks_like_robot_state(initial_state):
        signatures.append(_pose_signature(initial_state))
    for idx in range(max(0, samples - len(signatures))):
        state = await service.get_full_state(timeout=2.0, quiet=True)
        if _looks_like_robot_state(state):
            signatures.append(_pose_signature(state))
        if idx < samples - 1:
            await asyncio.sleep(interval_s)
    return _jitter_from_signatures(signatures)


async def _motion_sources_payload(
    *,
    service: Any | None = None,
    state_probe: dict[str, Any] | None = None,
    include_jitter: bool = True,
    hardware_faults: dict[str, Any] | None = None,
    daemon_api_reachable: bool | None = None,
    skip_daemon_move: bool = False,
) -> dict[str, Any]:
    service = service or get_reachy_service()
    sources: list[dict[str, Any]] = []

    if skip_daemon_move:
        running_moves = {"skipped": True, "detail": "Skipped on fast status path."}
    elif daemon_api_reachable is False:
        running_moves = {"error": "Daemon API is not running.", "connected": False}
    else:
        running_moves = await service.is_moving()
    running_move_count = _extract_move_count(running_moves)
    sources.append({
        "id": "daemon_move",
        "label": "Daemon move",
        "active": running_move_count > 0,
        "detail": f"{running_move_count} running move(s)" if running_move_count else "No queued daemon move.",
        "raw": running_moves,
    })

    try:
        from app.services.reachy_realtime.session import realtime_motion_snapshot
        realtime = realtime_motion_snapshot()
    except Exception as e:
        realtime = {"active": False, "error": str(e)}
    sources.append({
        "id": "realtime_body_motion",
        "label": "Live voice body motion",
        "active": bool(realtime.get("active")),
        "enabled": bool(realtime.get("body_motion_enabled")),
        "detail": (
            f"{realtime.get('motion_active_sessions', 0)} realtime session(s) moving the body."
            if realtime.get("active")
            else "Paused by default."
        ),
        "raw": realtime,
    })

    try:
        from app.services.reachy_head_tracking_service import get_reachy_head_tracking_service
        head_tracking = get_reachy_head_tracking_service().status()
    except Exception as e:
        head_tracking = {"running": False, "state": "unavailable", "detail": str(e), "error": str(e)}
    head_tracking_state = str(head_tracking.get("state") or "")
    head_tracking_running = bool(head_tracking.get("running"))
    head_tracking_moving = head_tracking_state == "tracking"
    sources.append({
        "id": "head_tracking",
        "label": "Face tracking",
        "active": head_tracking_moving,
        "enabled": head_tracking_running,
        "detail": str(head_tracking.get("detail") or "Face tracking off."),
        "raw": head_tracking,
    })

    try:
        presence = get_reachy_presence_service()
        ambient = presence.ambient_state()
        meeting = presence.meeting_state()
        pomodoro = presence.pomodoro_state()
    except Exception as e:
        ambient = {"enabled": False, "error": str(e)}
        meeting = {"active": False, "error": str(e)}
        pomodoro = {"active": False, "error": str(e)}
    sources.extend([
        {
            "id": "ambient",
            "label": "Ambient presence",
            "active": bool(ambient.get("active") or ambient.get("motion_active")),
            "enabled": bool(ambient.get("enabled")),
            "detail": (
                "Ambient motion active."
                if ambient.get("active") or ambient.get("motion_active")
                else "Ambient motion enabled."
                if ambient.get("enabled")
                else "Ambient motion off."
            ),
            "raw": ambient,
        },
        {
            "id": "meeting",
            "label": "Meeting gaze",
            "active": bool(meeting.get("active")),
            "detail": "Meeting speaker-tracking active." if meeting.get("active") else "Meeting mode off.",
            "raw": meeting,
        },
        {
            "id": "pomodoro",
            "label": "Focus timer gestures",
            "active": bool(pomodoro.get("active")),
            "detail": "Pomodoro gestures active." if pomodoro.get("active") else "Pomodoro off.",
            "raw": pomodoro,
        },
    ])

    try:
        from app.services.reachy_radio_service import get_reachy_radio_service
        radio = get_reachy_radio_service().status()
    except Exception as e:
        radio = {"active": False, "error": str(e)}
    sources.append({
        "id": "radio",
        "label": "Radio dance mode",
        "active": bool(radio.get("active")),
        "detail": "Radio dance mode active." if radio.get("active") else "Radio off.",
        "raw": radio,
    })

    control_mode = _robot_control_mode({}, state_probe or {})
    sources.append({
        "id": "motors",
        "label": "Motors",
        "active": control_mode == "enabled",
        "detail": f"Motor control is {control_mode or 'unknown'}.",
        "raw": {"control_mode": control_mode},
    })

    if hardware_faults is None:
        hardware_faults = await _daemon_hardware_faults_safe()
    faults = hardware_faults.get("faults") if isinstance(hardware_faults, dict) else []
    fault_labels = [
        f"{fault.get('motor')}: {fault.get('error')}"
        for fault in faults
        if isinstance(fault, dict)
    ]
    power_issue = bool(hardware_faults.get("power_issue")) if isinstance(hardware_faults, dict) else False
    recent_hardware_fault = bool(hardware_faults.get("active")) if isinstance(hardware_faults, dict) else False
    stale_hardware_fault = bool(hardware_faults.get("stale")) if isinstance(hardware_faults, dict) else False
    hardware_fault_active = power_issue or recent_hardware_fault
    sources.append({
        "id": "hardware_faults",
        "label": "Hardware faults",
        "active": hardware_fault_active,
        "detail": (
            "Motor bus is not detected. Check Reachy's motor power supply and motor/power connector."
            if power_issue
            else "Motor hardware fault: " + "; ".join(fault_labels[:2])
            if hardware_fault_active
            else "Previous motor overload is outside the protection window; inspect the actuator before retrying."
            if stale_hardware_fault
            else "No recent motor hardware faults in daemon logs."
        ),
        "raw": hardware_faults,
    })

    active_motion = any(src["active"] for src in sources if src["id"] not in {"motors", "hardware_faults"})
    pose_jitter = (
        await _measure_pose_jitter(service, initial_state=state_probe)
        if include_jitter and state_probe and _looks_like_robot_state(state_probe)
        else {"available": False, "samples": 0, "shaky": False}
    )
    body_activity = "moving" if active_motion else "still"
    if hardware_fault_active and not power_issue and control_mode == "enabled":
        body_activity = "shaky"
    elif pose_jitter.get("shaky") and not active_motion:
        body_activity = "shaky"
    elif not state_probe or not _looks_like_robot_state(state_probe):
        body_activity = "unknown"
    motion_state = (
        "degraded"
        if hardware_fault_active
        else
        "ready"
        if body_activity == "still"
        else "degraded"
        if body_activity in {"moving", "shaky"}
        else "offline"
    )

    return {
        "state": motion_state,
        "sources": sources,
        "active_source_ids": [src["id"] for src in sources if src["active"] and src["id"] != "motors"],
        "pose_jitter": pose_jitter,
        "body_activity": body_activity,
    }


async def _wait_for_daemon_moves_idle(
    service,
    *,
    timeout_s: float = 4.0,
    interval_s: float = 0.25,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    last_running: Any = None
    while time.monotonic() < deadline:
        last_running = await service.is_moving()
        if _extract_move_count(last_running) == 0:
            return {
                "ok": True,
                "detail": "Daemon move queue is idle.",
                "running": last_running,
            }
        await asyncio.sleep(interval_s)
    return {
        "ok": False,
        "detail": "Timed out waiting for daemon moves to finish.",
        "running": last_running,
    }


async def _wait_for_daemon_ready(
    service: Any,
    *,
    timeout_s: float = 45.0,
    interval_s: float = 2.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + max(0.0, timeout_s)
    last_daemon: dict[str, Any] = {}
    last_supervisor: dict[str, Any] | None = None
    while True:
        daemon_task = asyncio.create_task(
            service.get_daemon_status(timeout=1.0, supervisor_timeout=1.0, quiet=True)
        )
        state_probe = await service.get_full_state(timeout=2.0, quiet=True)
        last_daemon = await daemon_task
        if _looks_like_robot_state(state_probe) and not _daemon_api_reachable(last_daemon):
            last_daemon = _daemon_reachable_from_state(last_daemon, supervisor=last_supervisor)
        if _daemon_api_reachable(last_daemon) or _looks_like_robot_state(state_probe):
            return {"ok": True, "detail": "Daemon API is ready.", "daemon": last_daemon}
        last_supervisor = await _host_agent_get_safe("/daemon/status", timeout=5.0)
        if time.monotonic() >= deadline:
            return {
                "ok": False,
                "detail": "Timed out waiting for daemon API to become ready.",
                "daemon": last_daemon,
                "supervisor": last_supervisor,
            }
        await asyncio.sleep(interval_s)


async def _settle_assistant_body(request: AssistantSettleRequest) -> dict[str, Any]:
    service = get_reachy_service()
    actions: list[dict[str, Any]] = []

    async def _record(label: str, call) -> None:
        try:
            result = await call()
            result_ok = bool(result.get("ok")) if "ok" in result else "error" not in result
            actions.append({
                "id": label,
                "ok": result_ok,
                "detail": (
                    _short_error(result.get("error"))
                    if "error" in result
                    else str(result.get("detail") or ("ok" if result_ok else "reported failure"))
                ),
                "result": result,
            })
        except Exception as e:
            actions.append({"id": label, "ok": False, "detail": _short_error(e)})

    try:
        from app.services.reachy_realtime.session import suspend_all_realtime_motion
        realtime_result = await suspend_all_realtime_motion(reason=request.reason)
        actions.append({
            "id": "realtime_body_motion",
            "ok": True,
            "detail": "Paused realtime body motion.",
            "result": realtime_result,
        })
    except Exception as e:
        actions.append({"id": "realtime_body_motion", "ok": False, "detail": _short_error(e)})

    try:
        presence = get_reachy_presence_service()
        ambient_state = presence.ambient_stop()
        actions.append({"id": "ambient", "ok": True, "detail": "Ambient presence stopped.", "result": ambient_state})
        meeting_state = await presence.stop_meeting_mode(play_ack=False)
        actions.append({"id": "meeting", "ok": True, "detail": "Meeting gaze stopped.", "result": meeting_state})
        pomodoro_state = await presence.pomodoro_stop(play_ack=False)
        actions.append({"id": "pomodoro", "ok": True, "detail": "Focus gestures stopped.", "result": pomodoro_state})
    except Exception as e:
        actions.append({"id": "presence", "ok": False, "detail": _short_error(e)})

    try:
        from app.services.reachy_radio_service import get_reachy_radio_service
        radio_state = await get_reachy_radio_service().stop()
        actions.append({"id": "radio", "ok": True, "detail": "Radio dance mode stopped.", "result": radio_state})
    except Exception as e:
        actions.append({"id": "radio", "ok": False, "detail": _short_error(e)})

    await _record("daemon_moves", service.stop_all_moves)

    daemon_task = asyncio.create_task(
        service.get_daemon_status(timeout=1.0, supervisor_timeout=1.0, quiet=True)
    )
    initial_state_probe = await service.get_full_state(timeout=2.0, quiet=True)
    daemon = await daemon_task
    if _looks_like_robot_state(initial_state_probe) and not _daemon_api_reachable(daemon):
        daemon = _daemon_reachable_from_state(daemon)
    daemon_reachable = _daemon_api_reachable(daemon) or _looks_like_robot_state(initial_state_probe)
    if daemon_reachable:
        hardware_faults = await _daemon_hardware_faults_safe()
        hardware_fault_present = bool(
            hardware_faults.get("active") or hardware_faults.get("power_issue")
        )
        if hardware_fault_present:
            await _record("safe_motor_pause", lambda: service.set_motor_mode("disabled"))
            actions.append({
                "id": "hardware_faults",
                "ok": True,
                "detail": "Recent motor overload detected; skipped neutral pose and disabled motors for protection.",
                "result": hardware_faults,
            })
        elif request.keep_motors_enabled:
            await _record("robot_motors", lambda: service.set_motor_mode("enabled"))
        if request.neutral_pose == "default" and not hardware_fault_present:
            await _record("neutral_pose", lambda: service.settle_neutral(duration=1.0))
            idle_result = await _wait_for_daemon_moves_idle(service)
            actions.append({
                "id": "daemon_idle",
                "ok": bool(idle_result.get("ok")),
                "detail": str(idle_result.get("detail") or ""),
                "result": idle_result,
            })
            if not idle_result.get("ok"):
                await _record("daemon_moves_after_neutral", service.stop_all_moves)
        if not request.keep_motors_enabled and not hardware_fault_present:
            await _record("robot_motors", lambda: service.set_motor_mode("disabled"))
    else:
        actions.append({
            "id": "neutral_pose",
            "ok": False,
            "detail": "Skipped neutral pose because the daemon API is not running.",
            "result": daemon,
        })

    daemon_after_task = asyncio.create_task(
        service.get_daemon_status(timeout=1.0, supervisor_timeout=1.0, quiet=True)
    )
    state_probe = await service.get_full_state(timeout=3.0, quiet=True)
    daemon_after = await daemon_after_task
    if _looks_like_robot_state(state_probe) and not _daemon_api_reachable(daemon_after):
        daemon_after = _daemon_reachable_from_state(daemon_after)
    daemon_after_reachable = _daemon_api_reachable(daemon_after) or _looks_like_robot_state(state_probe)
    include_jitter = request.neutral_pose != "skip"
    motion = await _motion_sources_payload(
        service=service,
        state_probe=state_probe,
        include_jitter=include_jitter,
    )

    def _motion_unsettled(payload: dict[str, Any]) -> bool:
        active_motion_ids = [
            source_id
            for source_id in payload.get("active_source_ids") or []
            if source_id != "hardware_faults"
        ]
        return bool(
            payload.get("body_activity") in {"moving", "shaky"}
            or active_motion_ids
        )

    if (
        request.keep_motors_enabled
        and daemon_after_reachable
        and _motion_unsettled(motion)
    ):
        # The first jitter sample can land while the neutral pose is still
        # physically settling. Resample before disabling motors so "Start
        # Assistant" does not turn a healthy robot into an asleep one.
        await asyncio.sleep(0.8)
        state_probe = await service.get_full_state(timeout=3.0, quiet=True)
        motion = await _motion_sources_payload(
            service=service,
            state_probe=state_probe,
            include_jitter=include_jitter,
        )
        if _motion_unsettled(motion):
            await _record("neutral_pose_retry", lambda: service.settle_neutral(duration=0.8))
            idle_result = await _wait_for_daemon_moves_idle(service)
            actions.append({
                "id": "daemon_idle_retry",
                "ok": bool(idle_result.get("ok")),
                "detail": str(idle_result.get("detail") or ""),
                "result": idle_result,
            })
            await asyncio.sleep(0.5)
            state_probe = await service.get_full_state(timeout=3.0, quiet=True)
            motion = await _motion_sources_payload(
                service=service,
                state_probe=state_probe,
                include_jitter=include_jitter,
            )
        if _motion_unsettled(motion):
            await _record("safe_motor_pause", lambda: service.set_motor_mode("disabled"))
            await asyncio.sleep(3.0)
            state_probe = await service.get_full_state(timeout=3.0, quiet=True)
            motion = await _motion_sources_payload(
                service=service,
                state_probe=state_probe,
                include_jitter=include_jitter,
            )

    if request.keep_motors_enabled and daemon_after_reachable:
        # Some actuator overloads are reported a beat after the neutral pose
        # request returns. Hold the success response briefly so the console
        # does not tell the user the body is ready while the daemon is already
        # logging hardware errors.
        await asyncio.sleep(2.5)
        post_faults = await _daemon_hardware_faults_safe()
        if post_faults.get("active") or post_faults.get("power_issue"):
            await _record("safe_motor_pause", lambda: service.set_motor_mode("disabled"))
            stop_result = await _host_agent_post_safe("/daemon/stop", timeout=15.0)
            actions.append({
                "id": "reachy_daemon",
                "ok": "error" not in stop_result,
                "detail": "Stopped daemon after a fresh motor hardware fault."
                if "error" not in stop_result else _short_error(stop_result.get("error")),
                "result": stop_result,
            })
            actions.append({
                "id": "hardware_faults",
                "ok": True,
                "detail": "Fresh motor hardware fault detected after neutral pose.",
                "result": post_faults,
            })
            daemon_after = await service.get_daemon_status()
            daemon_after_reachable = _daemon_api_reachable(daemon_after)
            state_probe = await service.get_full_state(timeout=3.0, quiet=True) if daemon_after_reachable else {}
            motion = await _motion_sources_payload(
                service=service,
                state_probe=state_probe,
                include_jitter=daemon_after_reachable,
                hardware_faults=post_faults,
            )

    active_motion_after_settle = [
        source_id
        for source_id in motion["active_source_ids"]
        if source_id != "hardware_faults"
    ]
    hardware_fault_protected = any(
        action.get("ok") and action.get("id") in {"hardware_faults", "safe_motor_pause"}
        for action in actions
    )
    ok = (
        all(action.get("ok") for action in actions if action.get("id") not in {"radio", "presence"})
        and motion["body_activity"] == "still"
        and not active_motion_after_settle
        and (
            "hardware_faults" not in motion["active_source_ids"]
            or hardware_fault_protected
        )
    )
    return {
        "ok": ok,
        "reason": request.reason,
        "actions": actions,
        "state": motion["state"],
        "motion_sources": motion["sources"],
        "active_source_ids": motion["active_source_ids"],
        "body_activity": motion["body_activity"],
        "pose_jitter": motion["pose_jitter"],
        "robot_ready": _looks_like_robot_state(state_probe),
        "state_probe": state_probe,
    }


async def _assistant_status_payload(
    actions: list[dict[str, Any]] | None = None,
    *,
    fast: bool = False,
) -> dict:
    """Aggregate every moving piece the Reachy assistant launch depends on."""
    global _ASSISTANT_STATUS_FAST_CACHE
    cache_allowed = fast and actions is None
    if not cache_allowed:
        _ASSISTANT_STATUS_FAST_CACHE = None
    if cache_allowed and _ASSISTANT_STATUS_FAST_CACHE is not None:
        cached_at, cached_payload = _ASSISTANT_STATUS_FAST_CACHE
        if time.monotonic() - cached_at <= _ASSISTANT_STATUS_FAST_CACHE_S:
            payload = copy.deepcopy(cached_payload)
            payload["status_cached"] = True
            payload["status_cache_age_seconds"] = round(time.monotonic() - cached_at, 3)
            return payload

    service = get_reachy_service()
    info = service.get_status_info()

    if fast:
        host_health, supervisor = await asyncio.gather(
            _host_agent_get_safe("/health", timeout=0.25, attempts=1),
            _host_agent_get_safe("/daemon/status", timeout=0.25, attempts=1),
        )
    else:
        host_health, supervisor = await asyncio.gather(
            _host_agent_get_safe("/health", timeout=2.0),
            _host_agent_get_safe("/daemon/status", timeout=2.0),
        )
    if not host_health:
        supervisor = None
    daemon_running = bool((supervisor or {}).get("running"))
    supervisor_blocker = (supervisor or {}).get("probe_blocker")
    supervisor_port_owner = (supervisor or {}).get("listening_pid")
    supervisor_has_blocked_daemon = bool(supervisor_blocker and supervisor_port_owner)
    if host_health and supervisor is not None and not daemon_running and not supervisor_has_blocked_daemon:
        daemon_api = {"error": "Daemon process is stopped.", "connected": False}
        daemon_connected = False
        daemon_api_reachable = False
        state_probe = {}
        state_probe_reachable = False
        state_probe_stale = False
        state_probe_age = None
    else:
        daemon_task = asyncio.create_task(
            _daemon_status_fast(service) if fast else service.get_daemon_status(quiet=True)
        )
        if fast:
            state_probe, state_probe_reachable, state_probe_stale, state_probe_age = (
                await _fast_state_probe(service, timeout=0.5)
            )
        else:
            state_probe = await service.get_full_state(timeout=3.0, quiet=True)
            state_probe_reachable = _looks_like_robot_state(state_probe)
            state_probe_stale = False
            state_probe_age = 0.0 if state_probe_reachable else None
        daemon_api = await daemon_task
        if state_probe_reachable and not _daemon_api_reachable(daemon_api):
            daemon_api = _daemon_reachable_from_state(daemon_api, supervisor=supervisor)
        daemon_connected = _daemon_api_running(daemon_api) or state_probe_reachable
        daemon_api_reachable = _daemon_api_reachable(daemon_api) or state_probe_reachable
    body_connected, body_ready, robot_detail, body_control_mode = _robot_ready_detail(
        daemon_api,
        state_probe,
        daemon_api_reachable=daemon_api_reachable,
    )
    daemon_uptime = float((supervisor or {}).get("uptime_seconds") or 0)

    realtime = _realtime_config_safe()
    preferred_backend = realtime.get("preferred_backend") or realtime.get("backend") or "local"
    realtime_available = bool(realtime.get("realtime_available"))
    try:
        from app.services.reachy_realtime.session import realtime_session_snapshot
        realtime_session = realtime_session_snapshot()
    except Exception as e:
        realtime_session = {
            "session_phase": "idle",
            "stalled_reason": None,
            "input_health": {
                "source": "unknown",
                "ready": False,
                "rms": 0.0,
                "peak": 0.0,
                "empty_stt_count": 0,
                "confidence_state": "unknown",
                "last_error": str(e),
            },
            "output_health": {
                "sink": "unknown",
                "ready": False,
                "queued_ms": 0,
                "last_error": str(e),
            },
        }

    try:
        active_persona = get_voice_loop_service().get_active_persona_id()
    except Exception:
        active_persona = realtime.get("profile") or "companion"

    try:
        ambient = get_reachy_presence_service().ambient_state()
    except Exception as e:
        ambient = {"enabled": False, "error": str(e)}

    hardware_issues = _hardware_faults_with_daemon_error(
        await _daemon_hardware_faults_for_supervisor(supervisor, fast=fast),
        daemon_api,
    )
    motion = await _motion_sources_payload(
        service=service,
        state_probe=state_probe,
        include_jitter=False,
        hardware_faults=hardware_issues,
        daemon_api_reachable=daemon_api_reachable,
        skip_daemon_move=fast,
    )
    body_activity = motion["body_activity"]
    hardware_fault_source = next(
        (src for src in motion["sources"] if src.get("id") == "hardware_faults"),
        None,
    )
    hardware_fault_active = bool((hardware_fault_source or {}).get("active"))
    hardware_fault_raw = (
        hardware_fault_source.get("raw")
        if isinstance(hardware_fault_source, dict)
        else {}
    )
    hardware_power_issue = bool(
        _daemon_motor_power_issue(daemon_api)
        or (isinstance(hardware_fault_raw, dict) and hardware_fault_raw.get("power_issue"))
    )
    hardware_fault_history = bool(
        isinstance(hardware_fault_raw, dict) and hardware_fault_raw.get("faults")
    )
    hardware_fault_stale = bool(
        isinstance(hardware_fault_raw, dict)
        and hardware_fault_raw.get("stale")
        and hardware_fault_history
        and not hardware_fault_active
    )
    hardware_fault_recent = bool(hardware_fault_active and hardware_fault_history)
    if hardware_fault_active:
        body_ready = False
    robot_step_state: Literal["ready", "repair_required", "starting", "degraded", "offline"]
    robot_step_detail = robot_detail
    if hardware_power_issue:
        robot_step_state = "degraded"
        daemon_issue = _daemon_error_text(daemon_api)
        robot_step_detail = (
            f"{daemon_issue} Reachy USB is visible, but the motor bus is not detected. "
            "The body cannot move until motor power/connection is restored."
            if daemon_issue
            else (
                "Reachy USB is visible, but the motor bus is not detected. "
                "The body cannot move until motor power/connection is restored."
            )
        )
    elif hardware_fault_active:
        robot_step_state = "degraded"
        robot_step_detail = (
            f"{hardware_fault_source.get('detail')} Body motion is protected until the actuator/linkage is checked."
            if isinstance(hardware_fault_source, dict)
            else "Robot motor hardware fault detected; body motion is protected until the actuator/linkage is checked."
        )
    elif hardware_fault_recent:
        robot_step_state = "degraded"
        robot_step_detail = (
            f"{hardware_fault_source.get('detail')} Body motion is blocked until the actuator/linkage is checked."
            if isinstance(hardware_fault_source, dict)
            else "Recent robot motor hardware fault detected; body motion is blocked for protection."
        )
    elif hardware_fault_stale and not body_connected:
        robot_step_state = "offline"
        robot_step_detail = (
            "A previous motor overload is recorded outside the protection window. "
            "Inspect the actuator/linkage before retrying; Start Robot Assistant will retry carefully."
        )
    elif body_activity == "shaky":
        robot_step_state = "degraded"
        robot_step_detail = "Robot is reachable but residual motion/jitter was detected. Press Settle."
    elif hardware_fault_recent and body_control_mode == "disabled":
        robot_step_state = "degraded"
        robot_step_detail = (
            "Motors are disabled for protection after a recent motor overload. "
            "Assistant voice is still available."
        )
    elif body_ready:
        robot_step_state = "ready"
    elif daemon_api_reachable or body_connected:
        robot_step_state = "degraded"
    else:
        robot_step_state = "offline"
    robot_detail = robot_step_detail

    if not host_health:
        daemon_state: Literal["ready", "repair_required", "starting", "degraded", "offline"] = "offline"
        daemon_detail = "Cannot check until host_agent is up."
    elif daemon_connected:
        daemon_state = "ready"
        daemon_detail = (
            f"API reachable; state {daemon_api.get('state', 'running')}."
            if daemon_api.get("state") in {None, "running"}
            else (
                f"API reachable; body state is responding even though daemon status reports "
                f"{daemon_api.get('state', 'unknown')}."
            )
            if body_connected
            else f"API reachable; state {daemon_api.get('state', 'unknown')}."
        )
    elif daemon_api_reachable and body_connected:
        daemon_state = "ready"
        daemon_detail = (
            f"API reachable; body state is responding even though daemon status reports "
            f"{daemon_api.get('state', 'unknown')}."
        )
    elif daemon_api_reachable:
        daemon_state = "degraded"
        daemon_detail = (
            f"API reachable; {daemon_api.get('error')}"
            if daemon_api.get("error")
            else f"API reachable; state {daemon_api.get('state', 'unknown')}."
        )
    elif hardware_power_issue:
        daemon_state = "degraded"
        daemon_detail = "Stopped after Reachy motor bus was not detected."
    elif hardware_fault_recent:
        daemon_state = "degraded"
        daemon_detail = "Stopped after a recent Reachy motor hardware overload."
    elif hardware_fault_stale:
        daemon_state = "offline"
        daemon_detail = "Stopped after an older motor overload; inspect the actuator before retrying."
    elif daemon_running and daemon_uptime < 90:
        daemon_state = "starting"
        daemon_detail = f"Process pid {(supervisor or {}).get('pid')} is warming up."
    elif daemon_running:
        daemon_state = "offline"
        daemon_detail = f"Process pid {(supervisor or {}).get('pid')} exists, but :8000 is not responding."
    else:
        daemon_state = "offline"
        daemon_detail = "Stopped."

    steps = [
        _assistant_step("zero_api", "Zero API", "ready", "API is responding."),
        _assistant_step(
            "host_agent",
            "Windows host agent",
            "ready" if host_health else "repair_required",
            "Listening on the host-agent port." if host_health else "Host agent is not reachable.",
            None if host_health else ASSISTANT_REPAIR_COMMAND,
        ),
        _assistant_step(
            "reachy_daemon",
            "Zero robot daemon",
            daemon_state,
            daemon_detail,
        ),
        _assistant_step(
            "robot",
            "Robot connection",
            robot_step_state,
            robot_step_detail,
        ),
        _assistant_step(
            "voice_backend",
            "Live voice backend",
            "ready" if realtime_available else "degraded",
            f"Using {preferred_backend}.",
        ),
        _assistant_step(
            "persona",
            "Persona",
            "ready" if active_persona in {"assistant", "companion"} else "degraded",
            f"Active persona: {active_persona or 'unknown'}.",
        ),
    ]

    payload = {
        "state": _derive_assistant_state(steps),
        "steps": steps,
        "actions": actions or [],
        "repair_command": ASSISTANT_REPAIR_COMMAND,
        "connected": body_connected,
        "daemon_connected": daemon_api_reachable,
        "daemon_status_running": daemon_connected,
        "robot_ready": body_ready,
        "robot_detail": robot_detail,
        "body_control_mode": body_control_mode,
        "daemon_api": daemon_api,
        "state_probe": state_probe,
        "state_probe_reachable": state_probe_reachable,
        "state_probe_stale": state_probe_stale,
        "state_probe_age_seconds": (
            round(state_probe_age, 3) if isinstance(state_probe_age, (int, float)) else None
        ),
        "daemon": supervisor or {},
        "host_agent": host_health,
        "realtime": {**realtime, "session": realtime_session},
        "session_phase": realtime_session.get("session_phase", "idle"),
        "stalled_reason": realtime_session.get("stalled_reason"),
        "input_health": realtime_session.get("input_health"),
        "output_health": realtime_session.get("output_health"),
        "persona": active_persona,
        "ambient": ambient,
        "motion_sources": motion["sources"],
        "active_source_ids": motion["active_source_ids"],
        "body_activity": body_activity,
        "pose_jitter": motion["pose_jitter"],
        "hardware_issues": hardware_issues,
        "recommended_action": _reachy_recommended_action(
            body_connected=body_connected,
            body_ready=body_ready,
            control_mode=body_control_mode,
            daemon_api_reachable=daemon_api_reachable,
            hardware_fault_active=hardware_fault_active,
            hardware_power_issue=hardware_power_issue,
        ),
        "recent_activity": _recent_assistant_activity(),
        **info,
    }
    if cache_allowed:
        _ASSISTANT_STATUS_FAST_CACHE = (time.monotonic(), copy.deepcopy(payload))
    return payload


@router.get("/assistant/status")
async def assistant_status():
    return await _assistant_status_payload(fast=True)


@router.post("/assistant/settle")
async def assistant_settle(request: AssistantSettleRequest | None = None):
    """Stop robot-body motion sources and move Reachy to a calm neutral pose."""
    settle_request = request or AssistantSettleRequest()
    if settle_request.keep_motors_enabled or settle_request.neutral_pose != "skip":
        _body_motion_http_guard("assistant_settle")
    try:
        payload = await asyncio.wait_for(
            _settle_assistant_body(settle_request),
            timeout=ASSISTANT_SETTLE_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        service = get_reachy_service()
        state_probe = await service.get_full_state(timeout=2.0, quiet=True)
        motion = await _motion_sources_payload(
            service=service,
            state_probe=state_probe if _looks_like_robot_state(state_probe) else {},
            include_jitter=False,
            hardware_faults=await _daemon_hardware_faults_safe(fast=True),
        )
        active_motion_after_settle = [
            source_id
            for source_id in motion["active_source_ids"]
            if source_id != "hardware_faults"
        ]
        settled = motion["body_activity"] == "still" and not active_motion_after_settle
        payload = {
            "ok": settled,
            "reason": settle_request.reason,
            "actions": [
                {
                    "id": "settle_timeout",
                    "ok": settled,
                    "detail": (
                        "Settle exceeded 20 seconds, but Reachy now reports still."
                        if settled
                        else "Settle exceeded 20 seconds before all motion sources cleared."
                    ),
                }
            ],
            "state": motion["state"],
            "body_activity": motion["body_activity"],
            "active_source_ids": motion["active_source_ids"],
            "motion_sources": motion["sources"],
            "pose_jitter": motion["pose_jitter"],
            "state_probe": state_probe,
            "timed_out": True,
        }
    _record_assistant_activity(
        "settle",
        "Cleared motion sources and returned Reachy to neutral.",
        ok=bool(payload.get("ok")),
        state=str(payload.get("state") or ""),
        body_activity=str(payload.get("body_activity") or ""),
    )
    payload["recent_activity"] = _recent_assistant_activity()
    return payload


@router.get("/motion/sources")
async def motion_sources():
    service = get_reachy_service()
    supervisor = await _host_agent_get_safe("/daemon/status", timeout=1.0, attempts=1)
    supervisor_blocker = (supervisor or {}).get("probe_blocker")
    supervisor_has_blocked_daemon = bool(supervisor_blocker and (supervisor or {}).get("listening_pid"))
    if supervisor and not supervisor.get("running") and not supervisor_has_blocked_daemon:
        daemon_api_reachable = False
        state_probe = {}
    else:
        daemon_task = asyncio.create_task(_daemon_status_fast(service))
        state_probe, state_probe_reachable, _, _ = await _fast_state_probe(service, timeout=0.6)
        daemon = await daemon_task
        if state_probe_reachable and not _daemon_api_reachable(daemon):
            daemon = _daemon_reachable_from_state(daemon, supervisor=supervisor)
        daemon_api_reachable = _daemon_api_reachable(daemon) or state_probe_reachable
    return await _motion_sources_payload(
        service=service,
        state_probe=state_probe,
        include_jitter=False,
        hardware_faults=_hardware_faults_with_daemon_error(
            await _daemon_hardware_faults_for_supervisor(supervisor, fast=True),
            daemon if "daemon" in locals() else {},
        ),
        daemon_api_reachable=daemon_api_reachable,
    )


@router.post("/assistant/activate")
async def assistant_activate(request: AssistantActivationRequest):
    """Prepare Reachy for one-click live assistant mode without throwing 502s."""
    before = await _assistant_status_payload()
    actions: list[dict[str, Any]] = []
    if before["state"] == "repair_required":
        before["actions"] = [{
            "id": "host_agent_repair_required",
            "ok": False,
            "detail": "host_agent is unreachable; run the startup repair command on Windows.",
            "command": ASSISTANT_REPAIR_COMMAND,
        }]
        return before
    motor_power_issue = _assistant_has_motor_power_issue(before)
    hardware_fault_issue = _assistant_has_recent_hardware_fault(before)
    stale_hardware_fault_history = _assistant_has_stale_hardware_fault_history(before)
    body_motion_blocked = motor_power_issue or hardware_fault_issue
    body_motion_policy = body_motion_allowed(surface="assistant_activate")
    body_motion_requested = bool(request.enable_body_motion and body_motion_policy.get("allowed"))
    if request.enable_body_motion and not body_motion_requested:
        actions.append({
            "id": "body_motion_policy",
            "ok": False,
            "detail": body_motion_locked_payload(surface="assistant_activate")["detail"],
            "result": body_motion_policy,
        })

    try:
        from app.services.reachy_realtime.config_store import update_config
        if not get_voice_loop_service().set_persona(request.persona):
            raise ValueError(f"unknown persona: {request.persona}")
        update_config({"profile": request.persona})
        actions.append({"id": "persona", "ok": True, "detail": f"Selected {request.persona}."})
    except Exception as e:
        actions.append({"id": "persona", "ok": False, "detail": _short_error(e)})

    try:
        ambient_state = get_reachy_presence_service().ambient_stop()
        actions.append({"id": "ambient", "ok": True, "detail": "Ambient presence left off.", "state": ambient_state})
    except Exception as e:
        actions.append({"id": "ambient", "ok": False, "detail": _short_error(e)})

    daemon = before.get("daemon") or {}
    daemon_step = next((step for step in before.get("steps", []) if step.get("id") == "reachy_daemon"), {})
    daemon_step_state = daemon_step.get("state")
    start_wait: dict[str, Any] | None = None

    if body_motion_blocked:
        if daemon.get("running"):
            actions.append({
                "id": "reachy_daemon",
                "ok": True,
                "detail": (
                    "Daemon left running for diagnostics; movement is blocked until Reachy's motor bus is detected."
                    if motor_power_issue
                    else "Daemon left running for diagnostics; movement is blocked because Reachy reported a recent motor overload."
                ),
            })
        else:
            actions.append({
                "id": "reachy_daemon",
                "ok": False,
                "detail": (
                    "Daemon is stopped; retry hardware scan after Reachy's motor power/connection is restored."
                    if motor_power_issue
                    else "Daemon is stopped; inspect the overloaded actuator/linkage before retrying body motion."
                ),
            })
    elif request.start_daemon and not daemon.get("running"):
        start_result = await _host_agent_post_safe("/daemon/start", timeout=30.0)
        if "error" in start_result:
            service_for_wait = get_reachy_service()
            start_wait = await _wait_for_daemon_ready(
                service_for_wait,
                timeout_s=75.0,
                interval_s=2.0,
            )
        start_ok = "error" not in start_result or bool((start_wait or {}).get("ok"))
        actions.append({
            "id": "reachy_daemon",
            "ok": start_ok,
            "detail": (
                "Daemon start requested."
                if "error" not in start_result
                else "Daemon reported a start error, but the API became ready."
                if start_ok
                else _short_error(start_result.get("error"))
            ),
            "result": {"start": start_result, "wait": start_wait} if start_wait else start_result,
        })
        if start_wait is None:
            await asyncio.sleep(1.0)
    elif request.start_daemon and daemon_step_state == "offline":
        restart_result = await _host_agent_post_safe("/daemon/restart", timeout=40.0)
        if "error" in restart_result:
            service_for_wait = get_reachy_service()
            start_wait = await _wait_for_daemon_ready(
                service_for_wait,
                timeout_s=75.0,
                interval_s=2.0,
            )
        restart_ok = "error" not in restart_result or bool((start_wait or {}).get("ok"))
        actions.append({
            "id": "reachy_daemon",
            "ok": restart_ok,
            "detail": "Daemon restart requested because its API was unreachable."
            if "error" not in restart_result
            else "Daemon reported a restart error, but the API became ready."
            if restart_ok
            else _short_error(restart_result.get("error")),
            "result": {"restart": restart_result, "wait": start_wait} if start_wait else restart_result,
        })
        if start_wait is None:
            await asyncio.sleep(1.0)
    elif not body_motion_requested:
        actions.append({
            "id": "reachy_daemon",
            "ok": True,
            "detail": (
                "Daemon left running; voice-only activation does not command motion."
                if daemon.get("running")
                else "Daemon left stopped; voice-only activation does not require hardware."
            ),
        })
    else:
        actions.append({
            "id": "reachy_daemon",
            "ok": True,
            "detail": "Daemon already healthy or still warming up.",
        })

    service = get_reachy_service()
    fresh_daemon_task = asyncio.create_task(
        service.get_daemon_status(timeout=1.0, supervisor_timeout=1.0, quiet=True)
    )
    fresh_state_probe = await service.get_full_state(timeout=2.0, quiet=True)
    fresh_daemon = await fresh_daemon_task
    if _looks_like_robot_state(fresh_state_probe) and not _daemon_api_reachable(fresh_daemon):
        fresh_daemon = _daemon_reachable_from_state(fresh_daemon)
    if not body_motion_requested:
        actions.append({
            "id": "settle",
            "ok": True,
            "detail": "Skipped motor enable and neutral pose; body motion requires explicit opt-in.",
        })
    elif body_motion_blocked:
        actions.append({
            "id": "settle",
            "ok": False,
            "detail": (
                "Software motion is stopped; physical motor power/connection must be restored before the body can move."
                if motor_power_issue
                else "Software motion is stopped; inspect the overloaded actuator/linkage before moving the body again."
            ),
            "result": before.get("hardware_issues") or {},
        })
    elif _daemon_api_reachable(fresh_daemon):
        before_fault_source = next(
            (src for src in before.get("motion_sources", []) if src.get("id") == "hardware_faults"),
            {},
        )
        before_fault_raw = before_fault_source.get("raw") if isinstance(before_fault_source, dict) else {}
        protect_motors = bool(
            isinstance(before_fault_raw, dict)
            and (before_fault_raw.get("active") or before_fault_raw.get("power_issue"))
        )
        if protect_motors:
            motor_ok = False
            actions.append({
                "id": "robot_motors",
                "ok": True,
                "detail": "Skipped motor enable because a recent motor overload was detected.",
                "result": before_fault_raw,
            })
        else:
            motor_result = await service.set_motor_mode("enabled")
            motor_ok = "error" not in motor_result
            actions.append({
                "id": "robot_motors",
                "ok": motor_ok,
                "detail": "Motor control enabled." if motor_ok else _short_error(motor_result.get("error")),
                "result": motor_result,
            })
        if request.wake_robot and motor_ok:
            wake_result = await service.wake_up()
            actions.append({
                "id": "robot_wake",
                "ok": "error" not in wake_result,
                "detail": "Wake motion requested."
                if "error" not in wake_result
                else _short_error(wake_result.get("error")),
                "result": wake_result,
            })
            await asyncio.sleep(0.5)

        settle_result = await _settle_assistant_body(
            AssistantSettleRequest(reason="activation", keep_motors_enabled=not protect_motors)
        )
        actions.append({
            "id": "settle",
            "ok": bool(settle_result.get("ok")),
            "detail": "Robot settled into Still Ready posture.",
            "result": settle_result,
        })
        if stale_hardware_fault_history:
            latest_faults = await _daemon_hardware_faults_safe()
            latest_daemon = await service.get_daemon_status()
            if latest_faults.get("active") or latest_faults.get("power_issue"):
                stop_result = await _host_agent_post_safe("/daemon/stop", timeout=15.0)
                actions.append({
                    "id": "reachy_daemon",
                    "ok": "error" not in stop_result,
                    "detail": "Stopped daemon because the motor overload came back during retry."
                    if "error" not in stop_result else _short_error(stop_result.get("error")),
                    "result": {"stop": stop_result, "hardware_issues": latest_faults},
                })
            elif _daemon_api_reachable(latest_daemon):
                # Daemon is healthy after the retry; nothing else to do.
                pass
    else:
        actions.append({
            "id": "settle",
            "ok": False,
            "detail": "Skipped settle because the daemon API is not running yet.",
            "result": fresh_daemon,
        })

    if request.enable_ambient and body_motion_requested:
        try:
            ambient_state = get_reachy_presence_service().ambient_start()
            actions.append({"id": "ambient", "ok": True, "detail": "Ambient presence enabled.", "state": ambient_state})
        except Exception as e:
            actions.append({"id": "ambient", "ok": False, "detail": _short_error(e)})
    elif request.enable_ambient:
        actions.append({
            "id": "ambient",
            "ok": True,
            "detail": "Ambient presence left off because body motion is voice-only by default.",
        })

    final = await _assistant_status_payload(actions=actions)
    _record_assistant_activity(
        "activate",
        "Started Assistant Mode without enabling body motion."
        if not body_motion_requested
        else "Started Assistant Mode in Still Ready posture.",
        ok=final.get("state") == "ready",
        state=str(final.get("state") or ""),
        body_activity=str(final.get("body_activity") or ""),
    )
    final["recent_activity"] = _recent_assistant_activity()
    return final


@router.get("/status")
async def get_status():
    """Reachy Mini connection + daemon status + host_agent supervisor state."""
    global _REACHY_STATUS_FAST_CACHE
    service = get_reachy_service()
    service_cache_key = id(service)
    if _REACHY_STATUS_FAST_CACHE is not None:
        cached_at, cached_service_key, cached_payload = _REACHY_STATUS_FAST_CACHE
        if (
            cached_service_key == service_cache_key
            and time.monotonic() - cached_at <= _REACHY_STATUS_FAST_CACHE_S
        ):
            payload = copy.deepcopy(cached_payload)
            payload["status_cached"] = True
            payload["status_cache_age_seconds"] = round(time.monotonic() - cached_at, 3)
            return payload

    supervisor = _host_agent_cached("/daemon/status", max_age_s=_HOST_AGENT_STALE_CACHE_S)
    asyncio.create_task(_host_agent_get_safe("/daemon/status", timeout=0.5, attempts=1))

    daemon_task = asyncio.create_task(_daemon_status_fast(service))
    # Body state is the source of truth. Supervisor metadata is useful
    # diagnostics, but it must never sit on the UI status critical path.
    state_probe, state_probe_reachable, state_probe_stale, state_probe_age = (
        await _fast_state_probe(service, timeout=0.5)
    )
    daemon = await daemon_task
    if state_probe_reachable and not _daemon_api_reachable(daemon):
        daemon = _daemon_reachable_from_state(daemon, supervisor=supervisor)
    if (
        not state_probe_reachable
        and not _daemon_api_reachable(daemon)
        and supervisor
        and supervisor.get("running") is False
    ):
        daemon = {"error": "Daemon process is stopped.", "connected": False}
    daemon_connected = _daemon_api_running(daemon) or state_probe_reachable
    daemon_api_reachable = _daemon_api_reachable(daemon) or state_probe_reachable
    direct_daemon_api_reachable = _direct_daemon_reachable(daemon)
    body_connected, body_ready, robot_detail, body_control_mode = _robot_ready_detail(
        daemon,
        state_probe,
        daemon_api_reachable=daemon_api_reachable,
    )
    info = service.get_status_info()
    hardware_faults = _hardware_faults_with_daemon_error(
        await _daemon_hardware_faults_for_supervisor(supervisor, fast=True),
        daemon,
    )
    motion = await _motion_sources_payload(
        service=service,
        state_probe=state_probe,
        include_jitter=False,
        hardware_faults=hardware_faults,
        daemon_api_reachable=daemon_api_reachable or state_probe_reachable,
        skip_daemon_move=True,
    )
    hardware_fault_active = any(
        src.get("id") == "hardware_faults" and src.get("active")
        for src in motion["sources"]
    )
    fault_source = next(
        (src for src in motion["sources"] if src.get("id") == "hardware_faults"),
        {},
    )
    fault_raw = fault_source.get("raw") if isinstance(fault_source, dict) else {}
    hardware_fault_recent = bool(isinstance(fault_raw, dict) and fault_raw.get("active"))
    hardware_power_issue = bool(
        _daemon_motor_power_issue(daemon)
        or (isinstance(fault_raw, dict) and fault_raw.get("power_issue"))
    )
    if hardware_fault_active:
        body_ready = False
        robot_detail = str(fault_source.get("detail") or robot_detail)
    elif hardware_fault_recent and body_control_mode == "disabled":
        robot_detail = (
            "Motors are disabled for protection after a recent motor overload. "
            "Assistant voice is still available."
        )
    recommended_action = _reachy_recommended_action(
        body_connected=body_connected,
        body_ready=body_ready,
        control_mode=body_control_mode,
        daemon_api_reachable=daemon_api_reachable,
        hardware_fault_active=hardware_fault_active,
        hardware_power_issue=hardware_power_issue,
    )
    payload = {
        "connected": body_connected,
        "daemon_connected": daemon_api_reachable,
        "daemon_status_running": daemon_connected,
        "robot_ready": body_ready,
        "robot_detail": robot_detail,
        "body_control_mode": body_control_mode,
        "daemon_route": daemon.get("daemon_route") or daemon.get("via") or "direct",
        "daemon_direct_reachable": direct_daemon_api_reachable,
        "state_probe_reachable": state_probe_reachable,
        "status_stale": bool(state_probe_stale or (daemon.get("status_stale") and not state_probe_reachable)),
        "recommended_action": recommended_action,
        "daemon": daemon,
        "state_probe": state_probe,
        "state_probe_stale": state_probe_stale,
        "state_probe_age_seconds": (
            round(state_probe_age, 3) if isinstance(state_probe_age, (int, float)) else None
        ),
        "supervisor": supervisor,
        "motion_sources": motion["sources"],
        "active_source_ids": motion["active_source_ids"],
        "body_activity": motion["body_activity"],
        "pose_jitter": motion["pose_jitter"],
        **info,
    }
    if payload.get("status_stale"):
        _REACHY_STATUS_FAST_CACHE = None
    else:
        _REACHY_STATUS_FAST_CACHE = (time.monotonic(), service_cache_key, copy.deepcopy(payload))
    return payload


@router.get("/state")
async def get_state():
    """Full robot state (head pose, body yaw, antennas, DoA)."""
    return await get_reachy_service().get_full_state()


@router.get("/doa")
async def get_doa():
    """Direction of arrival (angle in radians, speech_detected bool)."""
    return await get_reachy_service().get_doa()


@router.get("/health-check")
async def health_check():
    return await get_reachy_service().health_check()


# --- Daemon supervisor (proxied to host_agent) ---

class DaemonRetryScanRequest(BaseModel):
    reason: str = Field("manual", min_length=1, max_length=80)


@router.get("/daemon/status")
async def daemon_status():
    return await _host_agent_forward("GET", "/daemon/status", timeout=5.0)


@router.get("/host-agent/status")
async def host_agent_status():
    """Fast probe of host_agent's /health for the UI offline banner.

    Returns `{reachable, url, last_error}`. Never raises — failure mode is
    `reachable: false` so the frontend can render the "stack offline" banner
    instead of an error toast.
    """
    base = _host_agent_base()
    if not base:
        return {
            "reachable": False,
            "url": None,
            "last_error": "host_agent_url_not_configured",
        }
    try:
        async with httpx.AsyncClient(timeout=0.5) as client:
            resp = await client.get(f"{base}/health")
            if resp.status_code < 400:
                return {"reachable": True, "url": base, "last_error": None}
            return {
                "reachable": False,
                "url": base,
                "last_error": f"HTTP {resp.status_code}",
            }
    except Exception as e:  # httpx.RequestError, ConnectError, TimeoutException
        return {
            "reachable": False,
            "url": base,
            "last_error": str(e) or type(e).__name__,
        }


@router.post("/daemon/start")
async def daemon_start():
    # Daemon lifecycle is a management operation, not body motion. It must
    # remain available while body motion is locked so the UI can recover from
    # a missing motor bus after the user fixes power or cabling.
    return await _host_agent_forward("POST", "/daemon/start", timeout=15.0)


@router.post("/daemon/stop")
async def daemon_stop():
    return await _host_agent_forward("POST", "/daemon/stop", timeout=15.0)


@router.post("/daemon/restart")
async def daemon_restart():
    # Restarting/probing the daemon does not command physical motion. Keep the
    # actual movement endpoints guarded, but allow this recovery control.
    return await _host_agent_forward("POST", "/daemon/restart", timeout=30.0)


@router.post("/daemon/retry-scan")
async def daemon_retry_scan(request: DaemonRetryScanRequest | None = None):
    """Restart/start the daemon once, then return fresh hardware status.

    This is the UI-safe recovery path for "motor bus missing" states. It does
    not enable motors, wake the body, or send movement; it only asks the daemon
    to rescan after the user fixes power/cabling.
    """
    req = request or DaemonRetryScanRequest()
    supervisor_before = await _host_agent_get_safe("/daemon/status", timeout=5.0)
    action = "restart" if (supervisor_before or {}).get("running") else "start"
    path = f"/daemon/{action}"
    action_result = await _host_agent_forward(
        "POST",
        path,
        timeout=40.0 if action == "restart" else 30.0,
    )
    await asyncio.sleep(1.0)
    wait_result = await _wait_for_daemon_ready(
        get_reachy_service(),
        timeout_s=30.0,
        interval_s=2.0,
    )
    assistant = await _assistant_status_payload(actions=[{
        "id": "hardware_scan",
        "ok": bool(wait_result.get("ok")),
        "detail": (
            f"Daemon {action} requested; refreshed hardware scan."
            if wait_result.get("ok")
            else str(wait_result.get("detail") or "Daemon scan did not become ready.")
        ),
        "result": {
            "reason": req.reason,
            "action": action,
            "daemon": action_result,
            "wait": wait_result,
        },
    }])
    hardware = assistant.get("hardware_issues") or {}
    motor_bus_missing = bool(
        isinstance(hardware, dict)
        and (
            hardware.get("power_issue")
            or any(
                isinstance(issue, dict) and issue.get("id") == "motors_unpowered"
                for issue in hardware.get("issues") or []
            )
        )
    )
    ok = bool(assistant.get("robot_ready")) and not motor_bus_missing
    detail = (
        "Motor bus detected; Reachy body is ready."
        if ok
        else (
            "USB/audio are visible; motor power/bus is missing. "
            "Check motor power/connector, then retry scan."
        )
        if motor_bus_missing
        else str(assistant.get("robot_detail") or wait_result.get("detail") or "Hardware scan completed.")
    )
    _record_assistant_activity(
        "hardware_scan",
        detail,
        ok=ok,
        state=str(assistant.get("state") or ""),
        body_activity=str(assistant.get("body_activity") or ""),
    )
    assistant["recent_activity"] = _recent_assistant_activity()
    return {
        "ok": ok,
        "action": action,
        "detail": detail,
        "daemon": action_result,
        "wait": wait_result,
        "assistant": assistant,
        "hardware_issues": hardware,
    }


@router.get("/daemon/logs")
async def daemon_logs(tail: int = Query(100, ge=1, le=500)):
    return await _host_agent_forward(
        "GET", "/daemon/logs", params={"tail": tail}, timeout=5.0,
    )


@router.get("/daemon/diagnostics")
async def daemon_diagnostics():
    return await _host_agent_forward("GET", "/daemon/diagnostics", timeout=15.0)


@router.post("/daemon/audio/reset")
async def daemon_audio_reset():
    return await _host_agent_forward("POST", "/daemon/audio/reset", timeout=10.0)


@router.post("/daemon/relink")
async def daemon_relink():
    """Manual recovery primitive: restart the Reachy daemon.

    Returns ``{action: "restarted", daemon, supervisor, detail}`` with the
    new pid + log path on success.
    """
    return await _host_agent_forward("POST", "/daemon/relink", timeout=45.0)


# --- Movement ---

@router.post("/move")
async def move_head(request: MoveRequest):
    _body_motion_http_guard("move_head")
    return await get_reachy_service().move_head(
        roll=request.roll,
        pitch=request.pitch,
        yaw=request.yaw,
        duration=request.duration,
    )


@router.post("/look")
async def look_at(request: LookAtRequest):
    _body_motion_http_guard("look_at")
    return await get_reachy_service().look_at(
        x=request.x, y=request.y, z=request.z, duration=request.duration,
    )


@router.post("/antennas")
async def set_antennas(request: AntennasRequest):
    _body_motion_http_guard("antennas")
    return await get_reachy_service().set_antennas(
        left_angle=request.left_angle,
        right_angle=request.right_angle,
        duration=request.duration,
    )


@router.post("/emotion")
async def play_emotion(request: EmotionRequest):
    _body_motion_http_guard("emotion")
    result = await get_reachy_service().play_emotion(request.emotion)
    if result.get("error", "").startswith("unknown emotion"):
        raise HTTPException(400, result)
    return result


@router.post("/dance")
async def play_dance(request: DanceRequest):
    _body_motion_http_guard("dance")
    result = await get_reachy_service().play_dance(request.dance)
    if result.get("error", "").startswith("unknown dance"):
        raise HTTPException(400, result)
    return result


# ---- Motion library (emotions + dances, with aliases + resolver) ----

@router.get("/motion/library")
async def motion_library(kind: Optional[Literal["emotion", "dance"]] = None):
    """
    List every clip the robot knows how to play. Returns the flat catalog, a
    kind-split, and a category-split for UI rendering.
    """
    if kind == "emotion":
        clips = EMOTION_CLIPS
    elif kind == "dance":
        clips = DANCE_CLIPS
    else:
        clips = ALL_CLIPS
    cats: dict[str, list[dict]] = {}
    for cat, items in categories().items():
        filtered = [clip_to_dict(c) for c in items if kind is None or c.kind == kind]
        if filtered:
            cats[cat] = filtered
    return {
        "total": len(clips),
        "emotions": len(EMOTION_CLIPS),
        "dances": len(DANCE_CLIPS),
        "clips": [clip_to_dict(c) for c in clips],
        "by_category": cats,
    }


@router.post("/motion/play")
async def motion_play(request: MotionPlayRequest):
    """Play any clip by name / alias / free-form tag. Kind is optional."""
    _body_motion_http_guard("motion_play")
    result = await get_reachy_service().play_motion(request.name, kind=request.kind)
    if result.get("error", "").startswith("unknown motion"):
        raise HTTPException(400, result)
    return result


@router.get("/motion/resolve")
async def motion_resolve(query: str, kind: Optional[Literal["emotion", "dance"]] = None):
    """
    Resolve a free-form tag to a concrete clip (or sequence) without playing
    it. Useful for letting the LLM or UI inspect what it would trigger.
    """
    seq = await get_reachy_sequence_service().resolve(query)
    if seq:
        return {
            "resolved_as": "sequence",
            "sequence": seq,
        }
    clip = resolve_motion(query, kind=kind)
    if not clip:
        raise HTTPException(404, {"error": f"no clip matches {query!r}", "kind": kind})
    return {"resolved_as": "clip", **clip_to_dict(clip)}


# ---- User motion sequences ----

@router.get("/sequences")
async def list_sequences():
    return {"sequences": await get_reachy_sequence_service().list_sequences()}


@router.get("/sequences/{id_or_name}")
async def get_sequence(id_or_name: str):
    seq = await get_reachy_sequence_service().get_sequence(id_or_name)
    if not seq:
        raise HTTPException(404, {"error": f"unknown sequence: {id_or_name}"})
    return seq


@router.post("/sequences")
async def create_sequence(request: SequenceCreate):
    try:
        return await get_reachy_sequence_service().create_sequence(
            name=request.name,
            description=request.description,
            steps=[s.model_dump() for s in request.steps],
            aliases=request.aliases,
        )
    except ValueError as e:
        raise HTTPException(400, {"error": str(e)})


@router.patch("/sequences/{sequence_id}")
async def update_sequence(sequence_id: int, request: SequenceUpdate):
    try:
        out = await get_reachy_sequence_service().update_sequence(
            sequence_id,
            name=request.name,
            description=request.description,
            steps=[s.model_dump() for s in request.steps] if request.steps is not None else None,
            aliases=request.aliases,
        )
    except ValueError as e:
        raise HTTPException(400, {"error": str(e)})
    if not out:
        raise HTTPException(404, {"error": f"unknown sequence id: {sequence_id}"})
    return out


@router.delete("/sequences/{sequence_id}")
async def delete_sequence(sequence_id: int):
    ok = await get_reachy_sequence_service().delete_sequence(sequence_id)
    if not ok:
        raise HTTPException(404, {"error": f"unknown sequence id: {sequence_id}"})
    return {"deleted": True, "id": sequence_id}


@router.get("/motion/recent")
async def motion_recent(limit: int = 10):
    """Last N clips the robot played, newest first. Ephemeral (in-memory)."""
    return {"motions": get_recent_motions(limit)}


@router.post("/sequences/{id_or_name}/play")
async def play_sequence(id_or_name: str):
    _body_motion_http_guard("sequence_play")
    result = await get_reachy_sequence_service().play_sequence(
        id_or_name, reachy_service=get_reachy_service(),
    )
    if result.get("error"):
        raise HTTPException(404, result)
    return result


# ---- Personas (Wave 2) ----

class PersonaSelectRequest(BaseModel):
    persona_id: str = Field(..., description="One of the ids from GET /reachy/personas")


class GestureParseRequest(BaseModel):
    text: str = Field(..., description="Raw LLM reply containing [emotion:..] or [dance:..] markers")


@router.get("/personas")
async def list_personas(include_prompt: bool = False):
    """List every persona the voice loop can wear."""
    vs = get_voice_loop_service()
    return {
        "active_id": vs.get_active_persona_id(),
        "personas": [persona_to_dict(p, include_prompt=include_prompt) for p in PERSONAS],
    }


# Must precede the /personas/{persona_id} catch-all below.
@router.get("/personas/stats")
async def persona_stats():
    from app.services.reachy_persona_state import get_reachy_persona_state
    return get_reachy_persona_state().get_stats()


@router.post("/personas/stats/reset")
async def persona_stats_reset(persona_id: Optional[str] = None):
    from app.services.reachy_persona_state import get_reachy_persona_state
    return get_reachy_persona_state().reset(persona_id)


# Must precede /personas/{persona_id} — FastAPI matches in declaration order.
@router.get("/personas/intros")
async def list_persona_intros():
    from app.services.reachy_persona_intros_service import (
        get_reachy_persona_intros_service,
    )
    return {"map": get_reachy_persona_intros_service().all()}


@router.get("/personas/{persona_id}")
async def get_persona_detail(persona_id: str):
    p = get_persona(persona_id)
    if not p:
        raise HTTPException(404, {"error": f"unknown persona: {persona_id}"})
    return persona_to_dict(p, include_prompt=True)


@router.post("/personas/select")
async def select_persona(request: PersonaSelectRequest):
    import asyncio as _asyncio
    vs = get_voice_loop_service()
    if not vs.set_persona(request.persona_id):
        # Allow filesystem-only personas (e.g. ``sally``) that aren't in the
        # in-memory PERSONAS tuple but DO exist as a directory under
        # ``backend/app/data/reachy_profiles/``. Without this, the realtime
        # profile catalog can hold a persona the legacy /personas API can't
        # accept — and the persona dropdown on Voice Settings can't switch
        # to her even though she's selectable from the realtime modal.
        try:
            from app.services.reachy_realtime.profiles import get_profile
            prof = get_profile(request.persona_id)
            if prof.id != request.persona_id:
                raise HTTPException(400, {"error": f"unknown persona: {request.persona_id}"})
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(400, {"error": f"unknown persona: {request.persona_id}"})

    # Mirror the choice into realtime config so Interactive Mode picks it up
    # without needing a second click in a different modal. We also pull in
    # the persona's bound voice + model so the live session actually SOUNDS
    # like the persona — without this, the saved realtime voice (Aria) was
    # winning over Sally's voice (Jenny) and the user heard the wrong voice.
    try:
        from app.services.reachy_realtime.config_store import update_config
        from app.services.reachy_realtime.profiles import get_profile
        patch: dict = {"profile": request.persona_id}
        try:
            prof = get_profile(request.persona_id)
            if prof.voice:
                patch["voice"] = prof.voice
            if prof.model:
                patch["model"] = prof.model
        except Exception:
            pass
        update_config(patch)
    except Exception as e:
        logger.debug("realtime_profile_mirror_skipped", error=str(e))

    # If the user assigned a signature intro sequence for this persona,
    # fire it on the robot in parallel — don't block the response.
    intro_sequence_id: Optional[int] = None
    try:
        from app.services.reachy_persona_intros_service import (
            get_reachy_persona_intros_service,
        )
        intros = get_reachy_persona_intros_service()
        seq_id = intros.get(request.persona_id)
        if seq_id is not None:
            intro_sequence_id = seq_id
            reachy = get_reachy_service()
            if await reachy.is_connected() and body_motion_allowed(surface="persona_intro").get("allowed"):
                _asyncio.create_task(
                    get_reachy_sequence_service().play_sequence(
                        str(seq_id), reachy_service=reachy,
                    )
                )
    except Exception as e:
        logger.debug("persona_intro_play_skipped", error=str(e))

    return {
        "active_id": vs.get_active_persona_id(),
        "intro_sequence_id": intro_sequence_id,
    }


# ---- Persona signature intros (sequences fired on persona switch) ----


class PersonaIntroRequest(BaseModel):
    sequence_id: int = Field(..., description="Sequence id from GET /sequences")


@router.post("/personas/{persona_id}/intro")
async def set_persona_intro(persona_id: str, request: PersonaIntroRequest):
    if not get_persona(persona_id):
        raise HTTPException(404, {"error": f"unknown persona: {persona_id}"})
    from app.services.reachy_persona_intros_service import (
        get_reachy_persona_intros_service,
    )
    intros = get_reachy_persona_intros_service()
    intros.set(persona_id, request.sequence_id)
    return {"persona_id": persona_id, "sequence_id": request.sequence_id}


@router.delete("/personas/{persona_id}/intro")
async def clear_persona_intro(persona_id: str):
    from app.services.reachy_persona_intros_service import (
        get_reachy_persona_intros_service,
    )
    intros = get_reachy_persona_intros_service()
    ok = intros.clear(persona_id)
    if not ok:
        raise HTTPException(404, {"error": f"no intro set for: {persona_id}"})
    return {"cleared": persona_id}


@router.post("/personas/{persona_id}/preview")
async def preview_persona(persona_id: str):
    """
    Synthesize the persona's signature greeting in its own voice and, when
    Reachy is connected, play it through Reachy's own speaker (not the
    browser's). Also fires the persona's signature gesture in parallel.

    Returns the WAV inline as ``audio_b64`` too so headless clients and the
    "robot offline" fallback can still play something. ``played_on_robot``
    tells the frontend whether Reachy already spoke — when true, the browser
    should NOT play the audio locally to avoid a double echo.
    """
    import asyncio
    import base64

    p = get_persona(persona_id)
    if not p:
        raise HTTPException(404, {"error": f"unknown persona: {persona_id}"})

    line = (p.preview_line or p.tagline or f"Hi, I'm {p.name}.").strip()
    gesture_fired: Optional[str] = None
    played_on_robot: bool = False

    # TTS in the persona's voice (with a tight timeout — preview should feel
    # instant).
    from app.services.tts_service import get_tts_service
    tts = get_tts_service()
    try:
        # Edge-tts cold-start the first time a voice is used can take 5-10s
        # on Windows WSL; 12s gives it room without hanging the UI forever.
        audio_bytes = await asyncio.wait_for(
            tts.synthesize(line, voice_override=p.voice),
            timeout=12.0,
        )
    except asyncio.TimeoutError:
        raise HTTPException(504, {"error": "TTS timed out during preview"})
    except Exception as e:
        raise HTTPException(503, {"error": f"TTS failed: {e}"})

    # Play on Reachy's speaker + fire signature gesture when connected.
    try:
        reachy = get_reachy_service()
        connected = await reachy.is_connected()
        if connected:
            if p.signature_gesture:
                if body_motion_allowed(surface="persona_preview_gesture").get("allowed"):
                    asyncio.create_task(reachy.play_emotion(p.signature_gesture))
                    gesture_fired = p.signature_gesture
            play_res = await reachy.play_audio_bytes(
                audio_bytes, label=f"preview_{persona_id}"
            )
            if not play_res.get("error"):
                played_on_robot = True
    except Exception as e:
        logger.debug("persona_preview_play_skipped", error=str(e))

    return {
        "persona_id": persona_id,
        "line": line,
        "voice": p.voice,
        "gesture": gesture_fired,
        "played_on_robot": played_on_robot,
        "audio_b64": base64.b64encode(audio_bytes).decode("ascii"),
    }


@router.post("/gesture/parse")
async def gesture_parse(request: GestureParseRequest):
    """
    Dev endpoint: run a raw LLM reply through the gesture-marker stripper and
    return what the voice loop would say + which gestures it would fire.
    """
    clean, actions = parse_and_strip(request.text)
    return {
        "clean_text": clean,
        "actions": [{"kind": a.kind, "payload": a.payload, "offset": a.offset} for a in actions],
    }


# ---- Presence / pomodoro (Wave 5) ----

class PomodoroStartRequest(BaseModel):
    focus_minutes: int = Field(25, ge=5, le=90)
    break_minutes: int = Field(5, ge=1, le=30)


@router.get("/presence/pomodoro")
async def pomodoro_state():
    return get_reachy_presence_service().pomodoro_state()


@router.post("/presence/pomodoro/start")
async def pomodoro_start(request: PomodoroStartRequest):
    _body_motion_http_guard("pomodoro_start")
    return await get_reachy_presence_service().pomodoro_start(
        focus_minutes=request.focus_minutes,
        break_minutes=request.break_minutes,
    )


@router.post("/presence/pomodoro/stop")
async def pomodoro_stop():
    return await get_reachy_presence_service().pomodoro_stop()


# ---- Meeting mode (Wave 4) ----

class MeetingModeRequest(BaseModel):
    meeting_id: Optional[str] = Field(None, description="Zero meeting id, if any")


@router.get("/presence/meeting")
async def meeting_state():
    return get_reachy_presence_service().meeting_state()


@router.post("/presence/meeting/start")
async def meeting_start(request: MeetingModeRequest):
    _body_motion_http_guard("meeting_start")
    return await get_reachy_presence_service().start_meeting_mode(request.meeting_id)


@router.post("/presence/meeting/stop")
async def meeting_stop():
    return await get_reachy_presence_service().stop_meeting_mode()


# ---- Ambient autonomy (presence beat / idle watcher / hourly chime) ----

@router.get("/presence/ambient")
async def ambient_state():
    return get_reachy_presence_service().ambient_state()


@router.post("/presence/ambient/start")
async def ambient_start():
    _body_motion_http_guard("ambient_start")
    return get_reachy_presence_service().ambient_start()


@router.post("/presence/ambient/stop")
async def ambient_stop():
    return get_reachy_presence_service().ambient_stop()


@router.post("/wake-up")
async def wake_up():
    _body_motion_http_guard("wake_up")
    service = get_reachy_service()
    actions: list[dict[str, Any]] = []
    hardware_faults = await _daemon_hardware_faults_safe()
    if hardware_faults.get("active") or hardware_faults.get("power_issue"):
        return {
            "ok": False,
            "actions": [{
                "id": "hardware_faults",
                "ok": False,
                "detail": (
                    "Wake skipped because Reachy has an active motor fault or motor-power issue."
                ),
                "result": hardware_faults,
            }],
            "robot_ready": False,
            "body_control_mode": None,
            "hardware_issues": hardware_faults,
            "recommended_action": _reachy_recommended_action(
                body_connected=False,
                body_ready=False,
                control_mode=None,
                daemon_api_reachable=True,
                hardware_fault_active=True,
            ),
        }

    motor_result = await service.set_motor_mode("enabled")
    motor_ok = "error" not in motor_result
    actions.append({
        "id": "robot_motors",
        "ok": motor_ok,
        "detail": "Motor control enabled." if motor_ok else _short_error(motor_result.get("error")),
        "result": motor_result,
    })
    if not motor_ok:
        return {
            "ok": False,
            "actions": actions,
            "robot_ready": False,
            "body_control_mode": None,
            "hardware_issues": hardware_faults,
            "recommended_action": _reachy_recommended_action(
                body_connected=False,
                body_ready=False,
                control_mode=None,
                daemon_api_reachable=True,
            ),
        }

    wake_result = await service.wake_up()
    wake_ok = "error" not in wake_result
    actions.append({
        "id": "robot_wake",
        "ok": wake_ok,
        "detail": "Wake motion requested." if wake_ok else _short_error(wake_result.get("error")),
        "result": wake_result,
    })
    await asyncio.sleep(0.5)
    state_probe = await service.get_full_state(timeout=3.0, quiet=True)
    control_mode = _robot_control_mode({}, state_probe)
    body_connected = _looks_like_robot_state(state_probe)
    body_ready = body_connected and control_mode != "disabled"
    return {
        "ok": wake_ok and body_ready,
        "actions": actions,
        "robot_ready": body_ready,
        "state_probe": state_probe,
        "body_control_mode": control_mode,
        "hardware_issues": hardware_faults,
        "recommended_action": _reachy_recommended_action(
            body_connected=body_connected,
            body_ready=body_ready,
            control_mode=control_mode,
            daemon_api_reachable=True,
        ),
    }


@router.post("/sleep")
async def goto_sleep():
    _body_motion_http_guard("goto_sleep")
    return await get_reachy_service().goto_sleep()


@router.post("/move/stop")
async def stop_move(uuid: Optional[str] = None):
    service = get_reachy_service()
    if uuid:
        return await service.stop_move(uuid)
    return await service.stop_all_moves()


@router.get("/move/running")
async def is_moving():
    return await get_reachy_service().is_moving()


@router.get("/head-tracking/status")
async def head_tracking_status():
    from app.services.reachy_head_tracking_service import get_reachy_head_tracking_service

    return get_reachy_head_tracking_service().status()


@router.post("/head-tracking/start")
async def head_tracking_start():
    _body_motion_http_guard("head_tracking")
    from app.services.reachy_head_tracking_service import get_reachy_head_tracking_service

    return await get_reachy_head_tracking_service().start()


@router.post("/head-tracking/stop")
async def head_tracking_stop():
    from app.services.reachy_head_tracking_service import get_reachy_head_tracking_service

    return await get_reachy_head_tracking_service().stop()


@router.post("/head-tracking/step")
async def head_tracking_step():
    _body_motion_http_guard("head_tracking_step")
    from app.services.reachy_head_tracking_service import get_reachy_head_tracking_service

    return await get_reachy_head_tracking_service().step()


# --- Audio / speech ---

@router.post("/say")
async def say(request: SayRequest):
    """Synthesize text and play it through the Reachy speaker."""
    result = await get_reachy_service().say(request.text)
    if result.get("error"):
        raise HTTPException(503, result)
    return result


@router.post("/test-sound")
async def test_sound():
    """Play the daemon's built-in test chime."""
    return await get_reachy_service().test_sound()


@router.get("/sounds")
async def list_sounds():
    return await get_reachy_service().list_sounds()


@router.post("/sounds/upload")
async def upload_sound(file: UploadFile = File(...)):
    content = await file.read()
    return await get_reachy_service().upload_sound(file.filename or "upload.wav", content)


@router.delete("/sounds/{filename}")
async def delete_sound(filename: str):
    return await get_reachy_service().delete_sound(filename)


@router.post("/sounds/play")
async def play_sound(request: PlaySoundRequest):
    return await get_reachy_service().play_sound(request.file)


@router.post("/sounds/stop")
async def stop_sound():
    return await get_reachy_service().stop_sound()


# --- Volume ---

@router.get("/volume")
async def get_volume():
    return await get_reachy_service().get_volume()


@router.post("/volume")
async def set_volume(request: VolumeRequest):
    return await get_reachy_service().set_volume(request.volume)


@router.get("/volume/microphone")
async def get_mic_volume():
    return await get_reachy_service().get_mic_volume()


@router.post("/volume/microphone")
async def set_mic_volume(request: VolumeRequest):
    return await get_reachy_service().set_mic_volume(request.volume)


# --- Motors ---

@router.get("/motors")
async def get_motor_status():
    return await get_reachy_service().get_motor_status()


@router.post("/motors/mode")
async def set_motor_mode(request: MotorModeRequest):
    if request.mode.strip().lower() != "disabled":
        _body_motion_http_guard("motor_mode")
    return await get_reachy_service().set_motor_mode(request.mode)


# --- Camera ---
# Specs come from the Reachy daemon; live frames come from the host_agent
# (camera_worker) which owns the USB device via OpenCV. Zero proxies the
# MJPEG stream + single-frame endpoint so browsers see a same-origin URL.

@router.get("/camera/specs")
async def camera_specs():
    return await get_reachy_service().get_camera_specs()


@router.get("/camera/stream")
async def camera_stream(fmt: str = "mjpeg"):
    """URL for browsers to consume the live camera feed (same-origin MJPEG)."""
    return {
        "url": get_reachy_service().get_stream_url(fmt=fmt),
        "format": fmt,
    }


@router.get("/camera/status")
async def camera_status():
    """Ask the host_agent whether the camera worker is running and healthy."""
    status = await _host_agent_get_safe("/camera/status")
    if not status or status.get("status") == "host_agent_unreachable":
        return {
            "active": False,
            "reason": "host_agent unreachable or not configured",
            "host_agent": status or None,
        }
    return status


@router.get("/camera/frame.jpg")
async def camera_frame():
    """Single JPEG snapshot. Useful for VLM calls and manual probes."""
    base = _host_agent_base()
    if not base:
        raise HTTPException(503, "ZERO_HOST_AGENT_URL not configured")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{base}/camera/frame.jpg")
    except httpx.RequestError as e:
        raise HTTPException(502, f"Host agent unreachable: {e}")
    if resp.status_code >= 400:
        raise HTTPException(resp.status_code, resp.text[:400])
    return Response(content=resp.content, media_type="image/jpeg")


@router.get("/camera/mjpeg")
async def camera_mjpeg():
    """
    Proxy the host_agent MJPEG stream so the browser sees a same-origin URL.
    Uses `httpx.AsyncClient.stream()` to forward bytes without buffering.
    """
    base = _host_agent_base()
    if not base:
        raise HTTPException(503, "ZERO_HOST_AGENT_URL not configured")

    async def _pipe():
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream("GET", f"{base}/camera/mjpeg") as resp:
                    if resp.status_code >= 400:
                        msg = await resp.aread()
                        raise HTTPException(resp.status_code, msg.decode("utf-8", errors="replace")[:400])
                    async for chunk in resp.aiter_raw():
                        yield chunk
        except httpx.RequestError as e:
            logger.warning("camera_mjpeg_proxy_error", error=str(e))
            return

    return StreamingResponse(
        _pipe(),
        media_type="multipart/x-mixed-replace; boundary=zero-frame",
    )


# ---- Vision (Wave 3) ----

@router.get("/vision/backends")
async def vision_backends():
    """Report which vision backends are available on this deployment."""
    from app.services.reachy_vision_service import get_reachy_vision_service
    return get_reachy_vision_service().backend_status()


# ---- User-recorded moves (Wave 10) ----

class RecordStartRequest(BaseModel):
    library: str = Field("user", description="Library name — folder under workspace/reachy/user_moves")
    name: str = Field(..., description="Move name (alnum + _-)")
    description: str = Field("", description="Optional human description")


@router.post("/moves/record/start")
async def moves_record_start(request: RecordStartRequest):
    _body_motion_http_guard("moves_record_start")
    from app.services.reachy_move_recorder import get_reachy_move_recorder
    result = await get_reachy_move_recorder().start(
        library=request.library, name=request.name, description=request.description,
    )
    if result.get("error"):
        raise HTTPException(400, result)
    return result


@router.post("/moves/record/stop")
async def moves_record_stop():
    from app.services.reachy_move_recorder import get_reachy_move_recorder
    result = await get_reachy_move_recorder().stop()
    if result.get("error") == "not_recording":
        raise HTTPException(400, result)
    return result


@router.get("/moves/record/status")
async def moves_record_status():
    from app.services.reachy_move_recorder import get_reachy_move_recorder
    return get_reachy_move_recorder().status()


@router.get("/moves/user")
async def moves_user_list():
    from app.services.reachy_move_recorder import get_reachy_move_recorder
    return {"moves": get_reachy_move_recorder().list_moves()}


@router.post("/moves/user/{library}/{name}/play")
async def moves_user_play(library: str, name: str):
    _body_motion_http_guard("moves_user_play")
    from app.services.reachy_move_recorder import get_reachy_move_recorder
    result = await get_reachy_move_recorder().play(library, name)
    if result.get("error") == "not_found":
        raise HTTPException(404, result)
    if result.get("error"):
        raise HTTPException(400, result)
    return result


@router.delete("/moves/user/{library}/{name}")
async def moves_user_delete(library: str, name: str):
    from app.services.reachy_move_recorder import get_reachy_move_recorder
    result = get_reachy_move_recorder().delete_move(library, name)
    if result.get("error"):
        raise HTTPException(404, result)
    return result


# ---- Radio mode (Wave 13) ----

class RadioStartRequest(BaseModel):
    bpm: float = Field(..., ge=40.0, le=200.0)
    beats_per_dance: int = Field(8, ge=2, le=32)
    dances: Optional[list[str]] = Field(None, description="Dance clip names; default uses a preset rotation")


@router.get("/radio/status")
async def radio_status():
    from app.services.reachy_radio_service import get_reachy_radio_service
    return get_reachy_radio_service().status()


@router.post("/radio/start")
async def radio_start(request: RadioStartRequest):
    _body_motion_http_guard("radio_start")
    from app.services.reachy_radio_service import get_reachy_radio_service
    return await get_reachy_radio_service().start(
        bpm=request.bpm,
        beats_per_dance=request.beats_per_dance,
        dances=request.dances,
    )


@router.post("/radio/stop")
async def radio_stop():
    from app.services.reachy_radio_service import get_reachy_radio_service
    return await get_reachy_radio_service().stop()


@router.post("/radio/analyze")
async def radio_analyze(audio: UploadFile = File(...)):
    """Detect BPM from an uploaded audio sample via librosa."""
    from app.services.reachy_radio_service import get_reachy_radio_service
    body = await audio.read()
    result = get_reachy_radio_service().analyze_bpm(body)
    if not result.get("available"):
        raise HTTPException(503, result)
    return result


# Persona stats routes moved up above /personas/{persona_id}
# to avoid route-matching collisions.

# ---- Current context (Wave 17) ----

# ---- User memory (cross-session) ----


class MemoryNoteCreate(BaseModel):
    category: Literal["preference", "fact", "correction", "topic"] = Field(
        ..., description="One of: preference, fact, correction, topic",
    )
    text: str = Field(..., min_length=1, max_length=400)
    confidence: float = Field(1.0, ge=0.0, le=1.0)


@router.get("/memory")
async def memory_get():
    """Every durable note Reachy has learned about the user + turn stats."""
    from app.services.reachy_user_memory_service import (
        get_reachy_user_memory_service,
    )
    mem = get_reachy_user_memory_service()
    return {
        "notes": [n.to_dict() for n in mem.list_notes()],
        "stats": mem.stats(),
    }


@router.post("/memory/notes")
async def memory_add_note(request: MemoryNoteCreate):
    """Manually teach Reachy something durable about you."""
    from app.services.reachy_user_memory_service import (
        get_reachy_user_memory_service,
    )
    mem = get_reachy_user_memory_service()
    try:
        note = await mem.add_note(request.category, request.text, confidence=request.confidence)
    except ValueError as e:
        raise HTTPException(400, {"error": str(e)})
    return note.to_dict()


@router.delete("/memory/notes/{note_id}")
async def memory_delete_note(note_id: str):
    from app.services.reachy_user_memory_service import (
        get_reachy_user_memory_service,
    )
    mem = get_reachy_user_memory_service()
    ok = mem.delete_note(note_id)
    if not ok:
        raise HTTPException(404, {"error": f"unknown note: {note_id}"})
    return {"deleted": note_id}


@router.get("/context/hint")
async def context_hint():
    """Preview the context block that would be injected into the next LLM turn."""
    from app.services.reachy_context_service import build_context_hint
    vs = get_voice_loop_service()
    hint = await build_context_hint(vs.get_active_persona_id())
    return {"persona": vs.get_active_persona_id(), "hint": hint or ""}


@router.get("/context/debug")
async def context_debug(include_sight: bool = Query(False)):
    """Structured context (time, pomodoro, meeting, upcoming, sight, attention)
    for UI display. Mirrors what /context/hint injects into the LLM prompt."""
    from app.services.reachy_context_service import build_context_debug
    vs = get_voice_loop_service()
    persona_id = vs.get_active_persona_id()
    cache_key = (persona_id, bool(include_sight))
    cached = _CONTEXT_DEBUG_CACHE.get(cache_key)
    if cached is not None:
        cached_at, cached_payload = cached
        age = time.monotonic() - cached_at
        if age <= _CONTEXT_DEBUG_CACHE_S:
            payload = copy.deepcopy(cached_payload)
            payload["context_cached"] = True
            payload["context_cache_age_seconds"] = round(age, 3)
            return payload
    try:
        ctx = await asyncio.wait_for(
            build_context_debug(persona_id, include_sight=include_sight),
            timeout=_CONTEXT_DEBUG_TIMEOUT_S,
        )
    except Exception:
        if cached is not None:
            cached_at, cached_payload = cached
            payload = copy.deepcopy(cached_payload)
            payload["context_cached"] = True
            payload["context_stale"] = True
            payload["context_cache_age_seconds"] = round(time.monotonic() - cached_at, 3)
            return payload
        now_local = datetime.now(_LOCAL_TZ)
        ctx = {
            "local_time": now_local.strftime("%A %H:%M"),
            "time_of_day": (
                "morning" if 5 <= now_local.hour < 12
                else "afternoon" if 12 <= now_local.hour < 17
                else "evening" if 17 <= now_local.hour < 22
                else "night"
            ),
            "pomodoro": None,
            "meeting": None,
            "upcoming": None,
            "sight": None,
            "attention": None,
        }
    payload = {"persona": persona_id, "context": ctx}
    _CONTEXT_DEBUG_CACHE[cache_key] = (time.monotonic(), copy.deepcopy(payload))
    return payload


# ---- Wake-word (Wave 11) ----

@router.get("/wake-word/status")
async def wake_word_status():
    from app.services.reachy_wake_word_service import get_reachy_wake_word_service
    return get_reachy_wake_word_service().backend_status()


@router.post("/wake-word/predict")
async def wake_word_predict(audio: UploadFile = File(...)):
    """
    Accept a 16 kHz mono int16 PCM chunk (raw bytes, NOT a WAV) and return
    the wake-word score. Use this from the browser's MediaRecorder pipeline
    to hands-free-trigger the voice loop.
    """
    from app.services.reachy_wake_word_service import get_reachy_wake_word_service
    svc = get_reachy_wake_word_service()
    body = await audio.read()
    fired, score = svc.predict_bytes(body)
    return {"fired": fired, "score": score, "backend": svc.backend_status()}


@router.post("/vision/detect")
async def vision_detect(
    kind: Literal["face", "hands"] = "face",
    image: UploadFile = File(...),
):
    """
    Detect faces or hands in a POSTed JPEG/PNG frame. Backend selects:
    - ``face`` uses OpenCV Haar cascades (ships with opencv-python).
    - ``hands`` uses MediaPipe Hands (requires ``pip install mediapipe``).

    Returns normalized [0, 1] bounding boxes so callers can scale to any
    target resolution without knowing the input size.
    """
    from app.services.reachy_vision_service import get_reachy_vision_service
    body = await image.read()
    result = get_reachy_vision_service().detect(body, kind=kind)
    if not result.get("available"):
        raise HTTPException(503, result)
    return result


@router.post("/vision/scene")
async def vision_scene(
    provider_id: Optional[str] = None,
    kind: Literal["face", "hands"] = "face",
    question: Optional[str] = None,
):
    """
    Full scene analysis: VLM caption + MediaPipe/OpenCV detections.

    - `provider_id` selects which SightProvider to pull from; defaults to the
      active one (usually `reachy`).
    - `question` (optional) is answered grounded in the current frame.
    """
    from app.services.reachy_vision_service import get_reachy_vision_service
    result = await get_reachy_vision_service().analyze_scene(
        provider_id=provider_id, kind=kind, question=question,
    )
    if not result.get("available"):
        raise HTTPException(503, result)
    return result


@router.get("/camera")
async def capture_image():
    """
    Capture an image from the robot's camera.

    The daemon's REST API does not expose still-frame capture — camera frames
    are streamed over WebRTC on :8443 by the desktop app. This endpoint is
    preserved for backward compatibility and always returns 503.
    """
    raise HTTPException(
        status_code=503,
        detail="Camera capture is unavailable via REST. The Reachy Mini daemon exposes "
               "only /api/camera/specs; frames are delivered over WebRTC on :8443.",
    )


# --- TTS helper (pure synthesis, no robot) ---

@router.post("/tts")
async def synthesize_tts(request: SayRequest):
    """Synthesize text to WAV audio bytes (does not play on the robot)."""
    from app.services.tts_service import get_tts_service
    tts = get_tts_service()
    try:
        audio_bytes = await tts.synthesize(request.text)
        return Response(content=audio_bytes, media_type="audio/wav")
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))


# --- Voice loop (STT -> LLM -> TTS) ---

# Outer backstop. Must exceed the sum of per-stage timeouts in
# voice_loop_service (_STT_TIMEOUT + _LLM_TIMEOUT + _TTS_TIMEOUT = 45 s) so
# normal turns never hit it, but any pathological hang (e.g. wedged provider
# process) gets cut off before the browser's 50 s AbortController does.
_VOICE_OUTER_TIMEOUT = 48.0


@router.post("/voice")
async def process_voice(audio: UploadFile = File(...)):
    """
    Process voice input through the full STT -> persona-wrapped LLM -> gesture
    marker strip -> TTS pipeline.

    The response includes the TTS WAV inline as ``audio_response_b64`` so
    HTTP-only clients like the reachy_mini_zero bridge app can play it back
    without a second round trip.
    """
    import asyncio
    import base64
    voice_service = get_voice_loop_service()
    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="No audio data provided")
    try:
        result = await asyncio.wait_for(
            voice_service.process_voice_input(audio_bytes),
            timeout=_VOICE_OUTER_TIMEOUT,
        )
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail={
                "stage": "outer",
                "message": f"Voice pipeline exceeded {_VOICE_OUTER_TIMEOUT}s",
            },
        )
    audio_response: bytes | None = result.pop("audio_response", None)
    return {
        **result,
        "has_audio_response": audio_response is not None,
        "audio_response_b64": (
            base64.b64encode(audio_response).decode("ascii") if audio_response else None
        ),
    }


# --- Voice stack config (STT model, LLM task assignment, TTS voice) ---

from app.services.reachy_voice_config_service import get_reachy_voice_config


class VoiceConfigPatch(BaseModel):
    stt_model: Optional[str] = None
    llm_model: Optional[str] = None  # "provider/model" format, e.g. "kimi/kimi-k2.6"
    tts_voice: Optional[str] = None


@router.get("/voice/config")
async def get_voice_config():
    """Current voice-stack selections (STT model, LLM assignment, TTS voice)."""
    cfg = get_reachy_voice_config()
    from app.infrastructure.llm_router import get_llm_router
    router_ = get_llm_router()
    provider, model, _fbs = router_.resolve_provider_model("voice_reply")
    return {
        "stt_model": cfg.get_stt_model(),
        "llm": {
            "provider": provider,
            "model": model,
            "spec": f"{provider}/{model}",
            "task_type": "voice_reply",
        },
        "tts_voice": cfg.get_tts_voice(),
    }


@router.put("/voice/config")
async def set_voice_config(patch: VoiceConfigPatch):
    """Update any subset of STT / LLM / TTS for the voice pipeline."""
    from app.services.tts_service import get_tts_service
    cfg = get_reachy_voice_config()
    tts = get_tts_service()
    applied: dict = {}

    if patch.stt_model is not None:
        try:
            await cfg.set_stt_model(patch.stt_model)
        except ValueError as e:
            raise HTTPException(400, str(e))
        # Kick off a background warmup of the new model so the next turn is fast.
        try:
            from app.services.audio_service import get_audio_service
            import asyncio as _asyncio
            _asyncio.create_task(get_audio_service().warmup(patch.stt_model))
        except Exception:
            pass
        # Tell host_agent (if reachable) to swap its PTT model too.
        try:
            import httpx as _httpx
            async with _httpx.AsyncClient(timeout=5.0) as client:
                await client.post(
                    os.getenv("ZERO_HOST_AGENT_URL", "http://host.docker.internal:18796").rstrip("/") + "/voice/config",
                    json={"whisper_model": patch.stt_model},
                )
        except Exception as e:
            logger.debug("host_agent_voice_config_push_skipped", error=str(e))
        applied["stt_model"] = patch.stt_model

    if patch.llm_model is not None:
        spec = patch.llm_model.strip()
        if "/" not in spec:
            raise HTTPException(400, "llm_model must be in 'provider/model' format")
        try:
            from app.infrastructure.llm_router import get_llm_router
            await get_llm_router().set_task_model("voice_reply", spec)
        except Exception as e:
            raise HTTPException(400, f"Failed to set voice_reply model: {e}")
        applied["llm_model"] = spec

    if patch.tts_voice is not None:
        try:
            await cfg.set_tts_voice(patch.tts_voice)
            await tts.set_piper_voice(patch.tts_voice)
        except ValueError as e:
            raise HTTPException(400, str(e))
        applied["tts_voice"] = patch.tts_voice

    return {"ok": True, "applied": applied}


@router.get("/voice/models")
async def list_voice_models():
    """Enumerate model choices the UI can show in dropdowns."""
    from app.services.audio_service import get_audio_service
    from app.infrastructure.llm_providers import get_provider as _get_provider

    stt_choices = get_audio_service().get_available_models()

    # LLM choices: pull the provider/model catalog from the LLM router's
    # available-models endpoint. Falls back to a shortlist if unreachable.
    llm_choices: list[dict] = []
    try:
        from app.routers.llm import available_models as _available_models_fn  # type: ignore
        resp = await _available_models_fn()
        by_provider = (resp or {}).get("models_by_provider", {}) if isinstance(resp, dict) else {}
        for prov_name, models in by_provider.items():
            for m in models or []:
                if not m:
                    continue
                llm_choices.append({
                    "provider": prov_name,
                    "model": m,
                    "spec": f"{prov_name}/{m}",
                })
    except Exception as e:
        logger.debug("llm_available_models_unavailable", error=str(e))

    if not llm_choices:
        llm_choices = [
            {"provider": "kimi", "model": "kimi-k2.6", "spec": "kimi/kimi-k2.6"},
            {"provider": "gemini", "model": "gemini-3.1-flash", "spec": "gemini/gemini-3.1-flash"},
            {"provider": "vllm", "model": "qwen3-chat", "spec": "vllm/qwen3-chat"},
            {"provider": "ollama", "model": "gemma4:e4b", "spec": "ollama/gemma4:e4b"},
        ]

    tts_choices = [
        {"id": "en_US-lessac-medium", "engine": "piper", "label": "Lessac (US English, medium)"},
        {"id": "en-US-AriaNeural", "engine": "edge-tts", "label": "Aria (edge-tts, cloud)"},
        {"id": "en-US-JennyNeural", "engine": "edge-tts", "label": "Jenny (edge-tts, cloud)"},
    ]

    return {
        "stt": stt_choices,
        "llm": llm_choices,
        "tts": tts_choices,
    }
