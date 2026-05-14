"""Companion state, policy, and event routing for Reachy Mini.

This layer makes Reachy feel like an aware companion instead of a set of
separate controls. It deliberately sits above the existing robot, realtime,
persona, memory, Home Assistant, and presence services: those remain the
specialists, while this service owns mode, consent, typed events, and the
next useful action.
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import threading
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx
import structlog

from app.infrastructure.config import get_settings, get_workspace_path
from app.models.reachy_companion import (
    CompanionEvent,
    CompanionEventCreate,
    CompanionMode,
    CompanionPolicy,
    CompanionPolicyPatch,
    CompanionSkill,
    CompanionSkillTriggerResponse,
    utc_now,
)
from app.services.reachy_personas import PERSONAS, REACHY_TOOLS, persona_to_dict

logger = structlog.get_logger()

EVENT_LIMIT = 300

CORE_ACTIONS = [
    "speak",
    "gesture",
    "look_at",
    "body_motion",
    "mic_listen",
    "camera_read",
    "memory_read",
    "memory_write",
    "calendar_read",
    "email_read",
    "home_assistant_read",
    "home_assistant_control",
    "cloud_realtime",
    "proactive_nudge",
    "alert",
]

MODE_DEFAULTS: dict[CompanionMode, dict[str, Any]] = {
    "ambient": {
        "mic_enabled": True,
        "camera_enabled": True,
        "body_motion_enabled": False,
        "proactive_enabled": True,
        "cloud_realtime_allowed": False,
        "memory_write_allowed": True,
        "max_proactive_events_per_hour": 4,
        "allowed_actions": [action for action in CORE_ACTIONS if action != "body_motion"],
    },
    "focus": {
        "mic_enabled": True,
        "camera_enabled": True,
        "body_motion_enabled": False,
        "proactive_enabled": True,
        "cloud_realtime_allowed": False,
        "memory_write_allowed": True,
        "max_proactive_events_per_hour": 2,
        "allowed_actions": [
            "speak",
            "gesture",
            "look_at",
            "mic_listen",
            "camera_read",
            "memory_read",
            "calendar_read",
            "home_assistant_read",
            "proactive_nudge",
            "alert",
        ],
    },
    "meeting": {
        "mic_enabled": True,
        "camera_enabled": False,
        "body_motion_enabled": False,
        "proactive_enabled": True,
        "cloud_realtime_allowed": False,
        "memory_write_allowed": True,
        "max_proactive_events_per_hour": 2,
        "allowed_actions": [
            "speak",
            "gesture",
            "look_at",
            "mic_listen",
            "memory_read",
            "memory_write",
            "calendar_read",
            "proactive_nudge",
            "alert",
        ],
    },
    "privacy": {
        "mic_enabled": False,
        "camera_enabled": False,
        "body_motion_enabled": False,
        "proactive_enabled": False,
        "cloud_realtime_allowed": False,
        "memory_write_allowed": False,
        "max_proactive_events_per_hour": 0,
        "allowed_actions": ["speak", "gesture", "memory_read", "calendar_read", "alert"],
    },
    "sleep": {
        "mic_enabled": False,
        "camera_enabled": False,
        "body_motion_enabled": False,
        "proactive_enabled": False,
        "cloud_realtime_allowed": False,
        "memory_write_allowed": False,
        "max_proactive_events_per_hour": 0,
        "allowed_actions": ["memory_read", "calendar_read", "alert"],
    },
}


COMPANION_SKILLS: tuple[CompanionSkill, ...] = (
    CompanionSkill(
        id="morning_briefing",
        title="Morning Briefing",
        description="Context, calendar, inbox pressure, and one useful next step.",
        mode_bias="ambient",
        required_events=["idle_elapsed"],
        allowed_actions=["speak", "calendar_read", "email_read", "memory_read"],
    ),
    CompanionSkill(
        id="focus_guardian",
        title="Focus Guardian",
        description="Quiet focus mode with sparse nudges and optional pomodoro motion.",
        mode_bias="focus",
        required_events=["phone_seen", "idle_elapsed"],
        allowed_actions=["speak", "gesture", "body_motion", "proactive_nudge"],
    ),
    CompanionSkill(
        id="meeting_copilot",
        title="Meeting Copilot",
        description="Meeting posture, speaker attention, and short interruptions only.",
        mode_bias="meeting",
        required_events=["meeting_started", "voice_heard"],
        allowed_actions=["speak", "look_at", "body_motion", "mic_listen", "memory_write"],
    ),
    CompanionSkill(
        id="home_presence",
        title="Home Presence",
        description="React to Home Assistant changes with tiny motion feedback.",
        mode_bias="ambient",
        required_events=["ha_state_changed"],
        allowed_actions=["gesture", "home_assistant_read", "home_assistant_control", "alert"],
    ),
    CompanionSkill(
        id="phone_detox",
        title="Phone Detox",
        description="Playful phone-awareness nudges during focus blocks.",
        mode_bias="focus",
        required_events=["phone_seen"],
        allowed_actions=["speak", "gesture", "camera_read", "proactive_nudge"],
    ),
    CompanionSkill(
        id="story_teach",
        title="Story/Teach Mode",
        description="A more expressive teaching companion with memory and motion.",
        mode_bias="ambient",
        required_events=["voice_heard"],
        allowed_actions=["speak", "gesture", "body_motion", "memory_read"],
    ),
    CompanionSkill(
        id="wind_down",
        title="Wind-down",
        description="Evening quiet mode, softer persona, and less motion.",
        mode_bias="sleep",
        required_events=["idle_elapsed"],
        allowed_actions=["speak", "gesture", "memory_read"],
    ),
    CompanionSkill(
        id="noticed_nudge",
        title="Reachy Noticed",
        description="A deterministic nudge when a typed event is important enough.",
        mode_bias="ambient",
        required_events=["object_seen", "person_seen", "phone_seen"],
        allowed_actions=["speak", "gesture", "proactive_nudge", "alert"],
    ),
)


class ReachyCompanionService:
    def __init__(self, storage_dir: Path | None = None) -> None:
        base = storage_dir or get_workspace_path("reachy")
        self._dir = Path(base).resolve()
        self._dir.mkdir(parents=True, exist_ok=True)
        self._policy_path = self._dir / "companion_policy.json"
        self._events_path = self._dir / "companion_events.json"
        self._lock = threading.RLock()
        self._events: list[CompanionEvent] | None = None
        self._status_cache: dict[str, Any] | None = None
        self._status_cache_at = 0.0
        self._status_cache_ttl_s = max(
            0.0,
            float(os.getenv("ZERO_REACHY_COMPANION_STATUS_CACHE_S", "5.0")),
        )

    def get_policy(self) -> CompanionPolicy:
        with self._lock:
            if not self._policy_path.exists():
                policy = self._default_policy()
                self._save_policy_locked(policy)
                return policy
            try:
                data = json.loads(self._policy_path.read_text(encoding="utf-8"))
                return self._normalize_policy(CompanionPolicy.model_validate(data))
            except Exception as exc:
                logger.warning("reachy_companion_policy_load_failed", error=str(exc))
                policy = self._default_policy()
                self._save_policy_locked(policy)
                return policy

    async def get_status(self) -> dict[str, Any]:
        if self._status_cache and self._status_cache_ttl_s > 0:
            age = time.monotonic() - self._status_cache_at
            if age <= self._status_cache_ttl_s:
                cached = copy.deepcopy(self._status_cache)
                cached["status_cached"] = True
                cached["status_cache_age_seconds"] = round(age, 3)
                return cached

        policy = self.get_policy()
        host_health, host_wake, host_camera, host_daemon = await asyncio.gather(
            self._host_get("/health", timeout=0.75),
            self._host_get("/wake/status", timeout=0.75),
            self._host_get("/camera/status", timeout=0.75),
            self._host_get("/daemon/status", timeout=0.75),
        )

        body = await self._body_status(host_daemon)
        persona = self._active_persona()
        presence = self._presence_status()
        realtime = self._realtime_status()
        backend_wake = self._backend_wake_status()
        context = await self._context_status(persona.get("id"))
        events = self.list_events(limit=10)
        diagnostics = self._diagnostics(
            body=body,
            host_health=host_health,
            host_wake=host_wake,
            host_camera=host_camera,
            realtime=realtime,
            backend_wake=backend_wake,
            policy=policy,
        )

        payload = {
            "mode": policy.mode,
            "policy": policy.model_dump(mode="json"),
            "persona": persona,
            "presence": presence,
            "realtime": realtime,
            "body": body,
            "senses": {
                "mic": {
                    "enabled": policy.mic_enabled,
                    "host_wake": host_wake,
                    "backend_wake": backend_wake,
                },
                "camera": {
                    "enabled": policy.camera_enabled,
                    "status": host_camera,
                },
                "context": context,
            },
            "diagnostics": diagnostics,
            "skills": [skill.model_dump() for skill in self.list_skills()],
            "timeline": [event.model_dump(mode="json") for event in events],
            "next_suggested_action": self._next_action(diagnostics, policy),
            "host_agent": host_health,
            "host_daemon": host_daemon,
        }
        self._status_cache = copy.deepcopy(payload)
        self._status_cache_at = time.monotonic()
        return payload

    def list_events(self, limit: int = 50) -> list[CompanionEvent]:
        events = self._load_events()
        return events[: max(1, min(limit, EVENT_LIMIT))]

    def record_event(self, event: CompanionEventCreate) -> CompanionEvent:
        policy = self.get_policy()
        persona = self._active_persona()
        item = CompanionEvent(
            **event.model_dump(),
            mode=policy.mode,
            persona_id=persona.get("id"),
        )
        with self._lock:
            events = self._load_events_locked()
            events.insert(0, item)
            self._events = events[:EVENT_LIMIT]
            self._save_events_locked()
        logger.info(
            "reachy_companion_event_recorded",
            event_id=item.id,
            event_type=item.type,
            source=item.source,
        )
        return item

    async def set_mode(
        self,
        mode: CompanionMode,
        *,
        reason: str = "user",
        apply_actions: bool = True,
    ) -> CompanionPolicy:
        with self._lock:
            existing = self.get_policy()
            policy = self._policy_for_mode(mode, existing=existing)
            self._save_policy_locked(policy)
        self.record_event(
            CompanionEventCreate(
                type="mode_changed",
                source="companion_policy",
                summary=f"Mode changed to {mode}.",
                payload={"reason": reason, "apply_actions": apply_actions},
                importance=0.55,
            )
        )
        if apply_actions:
            await self._apply_mode_actions(mode)
        return policy

    def update_policy(self, patch: CompanionPolicyPatch) -> CompanionPolicy:
        with self._lock:
            data = self.get_policy().model_dump()
            updates = patch.model_dump(exclude_none=True)
            if "allowed_actions" in updates and updates["allowed_actions"] is not None:
                updates["allowed_actions"] = self._clean_actions(updates["allowed_actions"])
            data.update(updates)
            data["updated_at"] = utc_now()
            policy = self._normalize_policy(CompanionPolicy.model_validate(data))
            self._save_policy_locked(policy)
        self.record_event(
            CompanionEventCreate(
                type="policy_changed",
                source="companion_policy",
                summary="Companion policy updated.",
                payload={"fields": sorted(updates.keys())},
                importance=0.5,
            )
        )
        return policy

    def list_skills(self) -> list[CompanionSkill]:
        policy = self.get_policy()
        return [self._skill_with_policy(skill, policy) for skill in COMPANION_SKILLS]

    async def trigger_skill(self, skill_id: str) -> CompanionSkillTriggerResponse:
        skill = next((item for item in self.list_skills() if item.id == skill_id), None)
        if skill is None:
            raise ValueError(f"unknown companion skill: {skill_id}")
        if not skill.enabled:
            event = self.record_event(
                CompanionEventCreate(
                    type="skill_triggered",
                    source="companion_skill",
                    summary=f"{skill.title} blocked.",
                    payload={"skill_id": skill_id, "blocked_reason": skill.blocked_reason},
                    importance=0.4,
                )
            )
            return CompanionSkillTriggerResponse(
                ok=False,
                skill_id=skill_id,
                mode=self.get_policy().mode,
                actions=[],
                event=event,
            )

        actions: list[dict[str, Any]] = []
        if skill.mode_bias != self.get_policy().mode:
            policy = await self.set_mode(skill.mode_bias, reason=f"skill:{skill_id}", apply_actions=True)
            actions.append({"id": "mode", "ok": True, "mode": policy.mode})

        event = self.record_event(
            CompanionEventCreate(
                type="skill_triggered",
                source="companion_skill",
                summary=f"{skill.title} triggered.",
                payload={"skill_id": skill_id},
                importance=0.6,
            )
        )
        return CompanionSkillTriggerResponse(
            ok=True,
            skill_id=skill_id,
            mode=self.get_policy().mode,
            actions=actions,
            event=event,
        )

    def action_allowed(self, action: str, *, persona_id: str | None = None) -> dict[str, Any]:
        policy = self.get_policy()
        if action == "alert" and policy.deterministic_alerts_enabled:
            return {"allowed": True, "reason": "deterministic_alert_bypass"}
        if action == "mic_listen" and not policy.mic_enabled:
            return {"allowed": False, "reason": "mic_disabled"}
        if action == "camera_read" and not policy.camera_enabled:
            return {"allowed": False, "reason": "camera_disabled"}
        if action == "body_motion" and not policy.body_motion_enabled:
            return {"allowed": False, "reason": "body_motion_disabled"}
        if action == "cloud_realtime" and not policy.cloud_realtime_allowed:
            return {"allowed": False, "reason": "cloud_realtime_not_allowed"}
        if action == "memory_write" and not policy.memory_write_allowed:
            return {"allowed": False, "reason": "memory_write_disabled"}
        if action == "proactive_nudge" and not policy.proactive_enabled:
            return {"allowed": False, "reason": "proactive_disabled"}
        if action.startswith("tool:"):
            tool = action.split(":", 1)[1]
            grants = self._tool_grants(policy, persona_id)
            return {
                "allowed": tool in grants,
                "reason": "persona_tool_grant" if tool in grants else "persona_tool_denied",
                "tool": tool,
                "persona_id": persona_id,
            }
        return {
            "allowed": action in policy.allowed_actions,
            "reason": "allowed_action" if action in policy.allowed_actions else "action_not_allowed",
        }

    def _default_policy(self) -> CompanionPolicy:
        return self._policy_for_mode("ambient")

    def _policy_for_mode(
        self,
        mode: CompanionMode,
        *,
        existing: CompanionPolicy | None = None,
    ) -> CompanionPolicy:
        data = existing.model_dump() if existing else {}
        data.update(MODE_DEFAULTS[mode])
        data["mode"] = mode
        data["updated_at"] = utc_now()
        if not data.get("per_persona_tool_grants"):
            data["per_persona_tool_grants"] = {
                persona.id: list(persona.tools or REACHY_TOOLS) for persona in PERSONAS
            }
        data["allowed_actions"] = self._clean_actions(data.get("allowed_actions") or [])
        return self._normalize_policy(CompanionPolicy.model_validate(data))

    def _normalize_policy(self, policy: CompanionPolicy) -> CompanionPolicy:
        data = policy.model_dump()
        mode_defaults = MODE_DEFAULTS[data["mode"]]
        if data["mode"] in {"privacy", "sleep"}:
            for key in (
                "mic_enabled",
                "camera_enabled",
                "body_motion_enabled",
                "proactive_enabled",
                "cloud_realtime_allowed",
                "memory_write_allowed",
            ):
                data[key] = False
        if not data.get("allowed_actions"):
            data["allowed_actions"] = mode_defaults["allowed_actions"]
        data["allowed_actions"] = self._clean_actions(data["allowed_actions"])
        if not _companion_body_motion_allowed():
            data["body_motion_enabled"] = False
            data["allowed_actions"] = [
                action for action in data["allowed_actions"] if action != "body_motion"
            ]
        if not data.get("per_persona_tool_grants"):
            data["per_persona_tool_grants"] = {
                persona.id: list(persona.tools or REACHY_TOOLS) for persona in PERSONAS
            }
        return CompanionPolicy.model_validate(data)

    def _clean_actions(self, actions: list[str]) -> list[str]:
        valid = set(CORE_ACTIONS)
        return [action for action in dict.fromkeys(actions) if action in valid]

    def _load_events(self) -> list[CompanionEvent]:
        with self._lock:
            return list(self._load_events_locked())

    def _load_events_locked(self) -> list[CompanionEvent]:
        if self._events is not None:
            return self._events
        if not self._events_path.exists():
            self._events = []
            return self._events
        try:
            raw = json.loads(self._events_path.read_text(encoding="utf-8"))
            self._events = [CompanionEvent.model_validate(item) for item in raw][:EVENT_LIMIT]
        except Exception as exc:
            logger.warning("reachy_companion_events_load_failed", error=str(exc))
            self._events = []
        return self._events

    def _save_events_locked(self) -> None:
        events = self._events or []
        tmp = self._events_path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps([event.model_dump(mode="json") for event in events], indent=2),
            encoding="utf-8",
        )
        tmp.replace(self._events_path)

    def _save_policy_locked(self, policy: CompanionPolicy) -> None:
        tmp = self._policy_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(policy.model_dump(mode="json"), indent=2), encoding="utf-8")
        tmp.replace(self._policy_path)

    async def _apply_mode_actions(self, mode: CompanionMode) -> None:
        try:
            from app.services.reachy_presence_service import get_reachy_presence_service

            presence = get_reachy_presence_service()
            policy = self.get_policy()
            if mode == "ambient":
                if policy.body_motion_enabled:
                    presence.ambient_start()
                else:
                    presence.ambient_stop()
            elif mode == "focus":
                if policy.body_motion_enabled and not presence.pomodoro_state().get("active"):
                    await presence.pomodoro_start(focus_minutes=25, break_minutes=5)
                elif not policy.body_motion_enabled:
                    await presence.pomodoro_stop(play_ack=False)
                    presence.ambient_stop()
            elif mode == "meeting":
                if policy.body_motion_enabled:
                    await presence.start_meeting_mode("companion-mode")
                else:
                    await presence.stop_meeting_mode(play_ack=False)
                    presence.ambient_stop()
            elif mode == "privacy":
                presence.ambient_stop()
                await presence.stop_meeting_mode(play_ack=False)
                await presence.pomodoro_stop(play_ack=False)
            elif mode == "sleep":
                presence.ambient_stop()
                await presence.stop_meeting_mode(play_ack=False)
                await presence.pomodoro_stop(play_ack=False)
                try:
                    from app.services.reachy_service import get_reachy_service

                    reachy = get_reachy_service()
                    await reachy.stop_sound()
                    await reachy.stop_all_moves()
                    await reachy.set_motor_mode("disabled")
                except Exception as exc:
                    logger.debug("reachy_companion_sleep_body_skipped", error=str(exc))
        except Exception as exc:
            logger.warning("reachy_companion_mode_actions_failed", mode=mode, error=str(exc))

    async def _host_get(self, path: str, *, timeout: float = 3.0) -> dict[str, Any] | None:
        base = self._host_agent_base()
        if not base:
            return None
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(f"{base}{path}")
                if resp.status_code >= 400:
                    return None
                return resp.json() if resp.content else {}
        except Exception:
            return None

    def _host_agent_base(self) -> str | None:
        settings = get_settings()
        url = settings.host_agent_url or "http://host.docker.internal:18796"
        return url.rstrip("/") if url else None

    async def _body_status(self, host_daemon: dict[str, Any] | None) -> dict[str, Any]:
        try:
            from app.services.reachy_service import get_reachy_service

            svc = get_reachy_service()
            try:
                daemon_api = await svc.get_daemon_status(timeout=0.4, supervisor_timeout=0.25, quiet=True)
            except TypeError as exc:
                if "unexpected keyword" not in str(exc):
                    raise
                daemon_api = await svc.get_daemon_status()
            api_reachable = not bool(daemon_api.get("error"))
            if api_reachable:
                try:
                    state_probe = await svc.get_full_state(with_doa=False, timeout=0.6, quiet=True)
                except TypeError as exc:
                    if "unexpected keyword" not in str(exc):
                        raise
                    state_probe = await svc.get_full_state(timeout=0.6, quiet=True)
            else:
                state_probe = {}
            backend = daemon_api.get("backend_status") if isinstance(daemon_api, dict) else {}
            backend_control_mode = (backend or {}).get("motor_control_mode")
            connected = _looks_like_robot_state(state_probe) or bool(
                api_reachable and daemon_api.get("state") == "running" and backend
            )
            control_mode = (
                str(state_probe.get("control_mode") or backend_control_mode or "").lower()
                or None
            )
            ready = bool(
                connected
                and control_mode is not None
                and control_mode != "disabled"
                and _looks_like_robot_state(state_probe)
            )
            if ready:
                detail = f"Robot body is reachable; motor control is {control_mode}."
            elif connected and control_mode == "disabled":
                detail = "Robot body is reachable, but motors are disabled/asleep."
            elif connected:
                detail = "Robot body is reachable but not fully ready."
            elif host_daemon and host_daemon.get("running"):
                detail = "Zero robot daemon is running, but robot state is not responding."
            else:
                detail = "Zero robot daemon is stopped or unavailable."
            return {
                "connected": connected,
                "ready": ready,
                "detail": detail,
                "control_mode": control_mode,
                "daemon_api": daemon_api,
                "host_daemon": host_daemon,
            }
        except Exception as exc:
            return {
                "connected": False,
                "ready": False,
                "detail": f"Body status unavailable: {exc}",
                "host_daemon": host_daemon,
            }

    def _active_persona(self) -> dict[str, Any]:
        active_id = None
        try:
            from app.services.voice_loop_service import get_voice_loop_service

            active_id = get_voice_loop_service().get_active_persona_id()
        except Exception:
            pass
        if not active_id:
            try:
                from app.services.reachy_realtime.config_store import load_config_masked

                active_id = load_config_masked().get("profile")
            except Exception:
                active_id = None
        active_id = active_id or "companion"
        persona = next((item for item in PERSONAS if item.id == active_id), None)
        if persona is None:
            return {"id": active_id, "name": active_id, "tools": []}
        return persona_to_dict(persona)

    def _presence_status(self) -> dict[str, Any]:
        try:
            from app.services.reachy_presence_service import get_reachy_presence_service

            presence = get_reachy_presence_service()
            return {
                "ambient": presence.ambient_state(),
                "pomodoro": presence.pomodoro_state(),
                "meeting": presence.meeting_state(),
            }
        except Exception as exc:
            return {"error": str(exc)}

    def _realtime_status(self) -> dict[str, Any]:
        try:
            from app.routers.reachy import _realtime_config_safe
            from app.services.reachy_realtime.session import realtime_session_snapshot

            return {**_realtime_config_safe(), "session": realtime_session_snapshot()}
        except Exception as exc:
            return {"realtime_available": False, "error": str(exc)}

    def _backend_wake_status(self) -> dict[str, Any]:
        try:
            from app.services.reachy_wake_word_service import get_reachy_wake_word_service

            return get_reachy_wake_word_service().backend_status()
        except Exception as exc:
            return {"available": False, "error": str(exc)}

    async def _context_status(self, persona_id: str | None) -> dict[str, Any] | None:
        try:
            from app.services.reachy_context_service import build_context_debug

            return await build_context_debug(persona_id, include_sight=False)
        except Exception:
            return None

    def _diagnostics(
        self,
        *,
        body: dict[str, Any],
        host_health: dict[str, Any] | None,
        host_wake: dict[str, Any] | None,
        host_camera: dict[str, Any] | None,
        realtime: dict[str, Any],
        backend_wake: dict[str, Any],
        policy: CompanionPolicy,
    ) -> list[dict[str, Any]]:
        wake_running = bool((host_wake or {}).get("running"))
        wake_available = bool((backend_wake or {}).get("available")) or (
            "openwakeword" in ((host_wake or {}).get("available_modes") or [])
        )
        camera_active = bool((host_camera or {}).get("active"))
        body_motion_locked = not policy.body_motion_enabled
        return [
            {
                "id": "robot_body",
                "label": "Robot body",
                "state": (
                    "locked"
                    if body_motion_locked
                    else "ready"
                    if body.get("ready")
                    else ("degraded" if body.get("connected") else "repair")
                ),
                "ok": bool(body_motion_locked or body.get("ready")),
                "detail": (
                    "Body motion is locked off; voice, camera, memory, and companion policy remain active."
                    if body_motion_locked
                    else body.get("detail") or "Unknown body state."
                ),
                "repair": None
                if body_motion_locked
                else "Wake the body or check Zero robot daemon/USB if this stays degraded.",
            },
            {
                "id": "wake_word",
                "label": "Wake word",
                "state": "ready" if wake_running else ("repair" if wake_available else "off"),
                "ok": wake_running,
                "detail": (
                    f"Running {host_wake.get('mode')}."
                    if wake_running and host_wake
                    else "openWakeWord is available but not running."
                    if wake_available
                    else "No local wake backend is available."
                ),
                "repair": "Enable openWakeWord on the host agent.",
            },
            {
                "id": "camera",
                "label": "Camera",
                "state": "ready" if camera_active else "idle",
                "ok": camera_active,
                "detail": (
                    "Camera worker is streaming."
                    if camera_active
                    else "Camera is idle; this is fine until a vision skill needs it."
                ),
                "repair": "Open a camera view or let a vision skill request frames.",
            },
            {
                "id": "provider",
                "label": "Provider",
                "state": "ready" if realtime.get("realtime_available") else "degraded",
                "ok": bool(realtime.get("realtime_available")),
                "detail": f"Using {realtime.get('preferred_backend') or realtime.get('backend') or 'unknown'}.",
                "repair": "Check the LLM status badge or voice settings.",
            },
            {
                "id": "privacy",
                "label": "Privacy",
                "state": "locked" if policy.mode in {"privacy", "sleep"} else "ready",
                "ok": True,
                "detail": (
                    "Mic, camera, proactive nudges, cloud realtime, and memory writes are disabled."
                    if policy.mode in {"privacy", "sleep"}
                    else "Local-first companion policy is active."
                ),
                "repair": None,
            },
            {
                "id": "host_agent",
                "label": "Host agent",
                "state": "ready" if host_health else "repair",
                "ok": bool(host_health),
                "detail": "Host agent is reachable." if host_health else "Host agent is not reachable.",
                "repair": "Run host_agent auto-restart task.",
            },
        ]

    def _next_action(
        self,
        diagnostics: list[dict[str, Any]],
        policy: CompanionPolicy,
    ) -> dict[str, Any]:
        by_id = {item["id"]: item for item in diagnostics}
        if not by_id.get("host_agent", {}).get("ok"):
            return {"id": "repair_host_agent", "label": "Repair host agent", "priority": "high"}
        if by_id.get("robot_body", {}).get("state") == "locked":
            return {"id": "body_motion_locked", "label": "Body motion locked off", "priority": "low"}
        if by_id.get("robot_body", {}).get("state") == "repair":
            return {"id": "repair_body", "label": "Reconnect Reachy body", "priority": "high"}
        if not by_id.get("wake_word", {}).get("ok"):
            return {"id": "enable_openwakeword", "label": "Enable openWakeWord", "priority": "medium"}
        if policy.mode == "ambient":
            return {"id": "start_focus", "label": "Start Focus Guardian", "priority": "low"}
        if policy.mode == "privacy":
            return {"id": "exit_privacy", "label": "Return to ambient when ready", "priority": "low"}
        return {"id": "none", "label": "No action needed", "priority": "low"}

    def _skill_with_policy(self, skill: CompanionSkill, policy: CompanionPolicy) -> CompanionSkill:
        blocked = [
            action
            for action in skill.allowed_actions
            if not self.action_allowed(action).get("allowed")
        ]
        if blocked:
            return skill.model_copy(
                update={
                    "enabled": False,
                    "blocked_reason": f"Policy blocks: {', '.join(blocked[:3])}",
                }
            )
        return skill.model_copy(update={"enabled": True, "blocked_reason": None})

    def _tool_grants(self, policy: CompanionPolicy, persona_id: str | None) -> list[str]:
        if persona_id and persona_id in policy.per_persona_tool_grants:
            return policy.per_persona_tool_grants[persona_id]
        active = self._active_persona().get("id")
        if active and active in policy.per_persona_tool_grants:
            return policy.per_persona_tool_grants[active]
        return list(REACHY_TOOLS)


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


def _companion_body_motion_allowed() -> bool:
    value = os.getenv("ZERO_REACHY_COMPANION_BODY_MOTION", "false")
    return value.strip().lower() in {"1", "true", "yes", "on"}


@lru_cache()
def get_reachy_companion_service() -> ReachyCompanionService:
    return ReachyCompanionService()
