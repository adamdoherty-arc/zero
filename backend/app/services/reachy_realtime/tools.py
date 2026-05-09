"""
Realtime-callable tools — same names and JSON Schemas as the upstream
``reachy_mini_conversation_app.tools.*`` modules, but the bodies call Zero's
``reachy_service`` via the injected ``MotionDispatcher`` instead of the
upstream MovementManager/CameraWorker threads.

This is intentionally closed-registry. The upstream dynamic loader
(profile-local .py tools, ``REACHY_MINI_EXTERNAL_TOOLS_DIRECTORY``, system
task_status/task_cancel) is deliberately absent — Zero profiles declare which
of these fixed tools to expose, and nothing more. That keeps untrusted tool
code out of the container and is enough to match every built-in upstream
behaviour.

Upstream mirror:
https://github.com/pollen-robotics/reachy_mini_conversation_app/tree/main/src/reachy_mini_conversation_app/tools
"""

from __future__ import annotations

import base64
import json
import time
from typing import Any, Awaitable, Callable, Dict, Optional

import httpx
import structlog

from app.services.reachy_realtime.bg_tool_manager import BackgroundToolManager, ToolState
from app.services.reachy_realtime.common import ToolDependencies
from app.services.reachy_motion_policy import body_motion_allowed, body_motion_locked_payload

logger = structlog.get_logger()


ToolHandler = Callable[[ToolDependencies, Dict[str, Any], BackgroundToolManager], Awaitable[Dict[str, Any]]]


class _MotionGovernor:
    """Keep companion motion subtle and prevent repeated or stuck clips."""

    banned_default_clips = {"cheerful1", "cheerful2", "happy_dance"}
    cooldown_s = 8.0
    max_repeat = 1
    settle_s = 1.2

    def __init__(self) -> None:
        self._last_by_name: dict[str, float] = {}
        self._active_until = 0.0

    def check(self, deps: ToolDependencies, *, name: str, kind: str, explicit: bool = False) -> dict[str, Any] | None:
        profile = str((deps.extra or {}).get("profile_id") or "").lower()
        companion_mode = profile in {"companion", "sally", "companion_girlfriend"}
        now = time.monotonic()
        if not companion_mode:
            return None
        if companion_mode and kind == "emotion" and name in self.banned_default_clips and not explicit:
            return {
                "error": f"{name} is disabled in default companion mode",
                "hint": "Use a short nod/look gesture or explicitly ask for that clip.",
            }
        if now < self._active_until and not explicit:
            return {
                "error": "motion governor is waiting for the current move to settle",
                "retry_after_s": round(self._active_until - now, 2),
            }
        last = self._last_by_name.get(name, 0.0)
        if companion_mode and now - last < self.cooldown_s and not explicit:
            return {
                "error": f"{name} is on cooldown",
                "retry_after_s": round(self.cooldown_s - (now - last), 2),
            }
        self._last_by_name[name] = now
        self._active_until = now + self.settle_s
        return None

    def clear(self) -> None:
        self._active_until = 0.0


_MOTION_GOVERNOR = _MotionGovernor()


_EXPLICIT_MOTION_WORDS = {
    "nod",
    "look",
    "wave",
    "wake",
    "move",
    "turn",
    "follow",
    "face",
    "track",
    "dance",
    "gesture",
    "point",
    "sleep",
}


def _explicit_motion_requested(deps: ToolDependencies, args: Dict[str, Any]) -> bool:
    if bool(args.get("explicit")):
        return True
    latest = str((deps.extra or {}).get("latest_user_text") or "").lower()
    return any(word in latest for word in _EXPLICIT_MOTION_WORDS)


def _companion_action_allowed(action: str, *, surface: str) -> dict[str, Any]:
    try:
        from app.services.reachy_companion_service import get_reachy_companion_service

        result = get_reachy_companion_service().action_allowed(action)
        return {
            "allowed": bool(result.get("allowed")),
            "surface": surface,
            "reason": result.get("reason") or ("allowed" if result.get("allowed") else "action_not_allowed"),
        }
    except Exception as exc:
        logger.warning("realtime_companion_policy_unavailable", surface=surface, action=action, error=str(exc))
        return {"allowed": False, "surface": surface, "reason": "policy_unavailable", "error": str(exc)}


def _motion_policy_error(surface: str, *, action: str = "body_motion") -> dict[str, Any] | None:
    """Policy gate for realtime movement tools.

    ``body_motion`` remains the opt-in gate for autonomous/continuous motion.
    Direct voice commands use the narrower companion actions (``gesture`` and
    ``look_at``), so "nod" and "look at me" still work while idle body motion
    stays locked off by default.
    """
    if action == "body_motion":
        if body_motion_allowed(surface=f"realtime:{surface}").get("allowed"):
            return None
        return body_motion_locked_payload(surface=f"realtime:{surface}")
    allowed = _companion_action_allowed(action, surface=f"realtime:{surface}")
    if allowed.get("allowed"):
        return None
    return {
        "error": f"{action}_locked",
        "surface": f"realtime:{surface}",
        "reason": allowed.get("reason"),
        "detail": f"Companion policy does not allow {action} right now.",
    }


# ----------------------- individual tool bodies -----------------------

async def _move_head(deps: ToolDependencies, args: Dict[str, Any], _mgr: BackgroundToolManager) -> Dict[str, Any]:
    locked = _motion_policy_error("move_head", action="look_at")
    if locked:
        return locked
    direction = str(args.get("direction") or "front")
    # Same delta table as upstream (degrees).
    deltas = {
        "left": dict(roll=0, pitch=0, yaw=40),
        "right": dict(roll=0, pitch=0, yaw=-40),
        "up": dict(roll=0, pitch=-30, yaw=0),
        "down": dict(roll=0, pitch=30, yaw=0),
        "front": dict(roll=0, pitch=0, yaw=0),
    }
    if direction not in deltas:
        return {"error": f"unknown direction: {direction}"}
    if deps.motion.move_head is None:
        return {"error": "motion unavailable"}
    res = await deps.motion.move_head(
        **deltas[direction],
        duration=deps.motion_duration_s,
    )
    if res.get("error"):
        return {"error": res["error"]}
    return {"status": f"looking {direction}"}


async def _dance(deps: ToolDependencies, args: Dict[str, Any], _mgr: BackgroundToolManager) -> Dict[str, Any]:
    locked = _motion_policy_error("dance", action="gesture")
    if locked:
        return locked
    move = args.get("move") or "random"
    repeat = int(args.get("repeat") or 1)
    if deps.motion.play_dance is None:
        return {"error": "dance unavailable"}
    if move == "random":
        # Let reachy_service's resolver pick a dance — it accepts 'random' as a free tag.
        move = "dance"
    blocked = _MOTION_GOVERNOR.check(
        deps,
        name=str(move),
        kind="dance",
        explicit=_explicit_motion_requested(deps, args),
    )
    if blocked:
        return blocked
    profile = str((deps.extra or {}).get("profile_id") or "").lower()
    if profile in {"companion", "sally", "companion_girlfriend"} and not _explicit_motion_requested(deps, args):
        repeat = min(repeat, _MOTION_GOVERNOR.max_repeat)
    last: Dict[str, Any] = {}
    for _ in range(max(1, repeat)):
        last = await deps.motion.play_dance(str(move))
        if last.get("error"):
            return {"error": last["error"], "move": move}
    return {"status": "queued", "move": move, "repeat": repeat}


async def _play_emotion(deps: ToolDependencies, args: Dict[str, Any], _mgr: BackgroundToolManager) -> Dict[str, Any]:
    emotion = args.get("emotion")
    if not emotion:
        return {"error": "Emotion name is required"}
    locked = _motion_policy_error("play_emotion", action="gesture")
    if locked:
        return locked
    if deps.motion.play_emotion is None:
        return {"error": "emotions unavailable"}
    blocked = _MOTION_GOVERNOR.check(
        deps,
        name=str(emotion),
        kind="emotion",
        explicit=_explicit_motion_requested(deps, args),
    )
    if blocked:
        return blocked
    res = await deps.motion.play_emotion(str(emotion))
    if res.get("error"):
        return {"error": res["error"], "emotion": emotion}
    return {"status": "queued", "emotion": emotion}


async def _stop_dance(deps: ToolDependencies, _args: Dict[str, Any], _mgr: BackgroundToolManager) -> Dict[str, Any]:
    if deps.motion.stop_move is not None:
        await deps.motion.stop_move()
    _MOTION_GOVERNOR.clear()
    return {"status": "stopped dance"}


async def _stop_emotion(deps: ToolDependencies, _args: Dict[str, Any], _mgr: BackgroundToolManager) -> Dict[str, Any]:
    if deps.motion.stop_move is not None:
        await deps.motion.stop_move()
    _MOTION_GOVERNOR.clear()
    return {"status": "stopped emotion"}


async def _head_tracking(deps: ToolDependencies, args: Dict[str, Any], _mgr: BackgroundToolManager) -> Dict[str, Any]:
    enable = bool(args.get("start"))
    if enable:
        locked = _motion_policy_error("head_tracking", action="look_at")
        if locked:
            return locked
        if not bool((deps.extra or {}).get("body_motion_enabled")) and not _explicit_motion_requested(deps, args):
            return {
                "error": "body_motion_session_off",
                "detail": "Automatic face tracking is off for this live session. Use Auto motion or explicitly ask me to move.",
            }
    result: dict[str, Any] = {}
    if deps.motion.set_head_tracking is not None:
        result = await deps.motion.set_head_tracking(enable)
    else:
        result = {"error": "head tracking unavailable"}
    if result.get("error"):
        return result
    state = str(result.get("state") or ("started" if enable else "stopped"))
    detail = str(result.get("detail") or "")
    if enable and state == "scanning":
        return {
            "status": "head tracking scanning",
            "detail": detail or "Scanning for a visible face before moving.",
            "tracking": result,
        }
    if enable and state == "tracking":
        return {
            "status": "head tracking active",
            "detail": detail or "Following the detected face.",
            "tracking": result,
        }
    status = "stopped" if not enable else state
    return {
        "status": f"head tracking {status}",
        "detail": detail,
        "tracking": result,
    }


async def _do_nothing(_deps: ToolDependencies, args: Dict[str, Any], _mgr: BackgroundToolManager) -> Dict[str, Any]:
    reason = args.get("reason", "just chilling")
    return {"status": "doing nothing", "reason": reason}


async def _camera(deps: ToolDependencies, args: Dict[str, Any], _mgr: BackgroundToolManager) -> Dict[str, Any]:
    question = str(args.get("question") or "").strip()
    if not question:
        return {"error": "question must be a non-empty string"}
    if deps.motion.capture_image is None:
        return {"error": "camera unavailable", "hint": "Reachy daemon exposes only /api/camera/specs; frames live on WebRTC :8443"}
    try:
        jpeg = await deps.motion.capture_image()
    except Exception as e:
        return {"error": f"capture failed: {e}"}
    if not jpeg:
        return await _camera_unavailable_detail()
    return {"b64_im": base64.b64encode(jpeg).decode("ascii")}


async def _camera_unavailable_detail() -> Dict[str, Any]:
    """Explain whether the daemon sees a camera but host frames are inactive."""
    specs: dict[str, Any] = {}
    status: dict[str, Any] = {}
    try:
        from app.infrastructure.config import get_settings
        from app.services.reachy_service import get_reachy_service

        specs = await get_reachy_service().get_camera_specs()
        host_agent = (get_settings().host_agent_url or "http://host.docker.internal:18796").rstrip("/")
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{host_agent}/camera/status")
            if resp.status_code == 200:
                status = resp.json()
            else:
                status = {"last_error": f"host_agent /camera/status HTTP {resp.status_code}"}
    except Exception as exc:
        status = status or {"last_error": str(exc)}

    specs_detected = bool(specs and not specs.get("error"))
    worker_active = bool(status.get("active"))
    frame_available = bool(status.get("frame_available"))
    if specs_detected and not worker_active:
        return {
            "error": "camera frame unavailable",
            "condition": "specs_detected_frame_worker_inactive",
            "detail": (
                "Reachy camera specs are detected, but the host camera frame "
                f"worker is inactive: {status.get('last_error') or 'no JPEG frame has been captured'}."
            ),
            "camera_specs": specs,
            "camera_status": status,
        }
    return {
        "error": "camera frame unavailable",
        "condition": "no_jpeg_frame",
        "detail": status.get("last_error") or (
            "Host camera worker is active but has not produced a real JPEG frame."
            if worker_active and not frame_available
            else "No real JPEG frame was captured."
        ),
        "camera_specs": specs,
        "camera_status": status,
    }


async def _task_status(_deps: ToolDependencies, args: Dict[str, Any], mgr: BackgroundToolManager) -> Dict[str, Any]:
    tool_id = args.get("tool_id")
    if tool_id:
        t = mgr.get_tool(str(tool_id))
        if not t:
            return {"error": f"Tool {tool_id} not found."}
        return {
            "tool_id": t.tool_id,
            "name": t.tool_name,
            "status": t.status.value,
            "result": t.result,
            "error": t.error,
        }
    running = mgr.get_running_tools()
    if not running:
        return {"status": "idle", "message": "No tools running in the background."}
    return {
        "status": "running",
        "count": len(running),
        "tools": [{"tool_id": t.tool_id, "name": t.tool_name} for t in running],
    }


async def _task_cancel(_deps: ToolDependencies, args: Dict[str, Any], mgr: BackgroundToolManager) -> Dict[str, Any]:
    tool_id = args.get("tool_id")
    if not tool_id:
        return {"error": "Tool ID is required."}
    t = mgr.get_tool(str(tool_id))
    if not t:
        return {"error": f"Tool {tool_id} not found."}
    if t.status != ToolState.RUNNING:
        return {"status": t.status.value, "tool_id": tool_id}
    ok = await mgr.cancel_tool(str(tool_id))
    return {"status": "cancelled" if ok else "not_cancelled", "tool_id": tool_id}


# ----------------------- specs (name -> (spec, handler)) -----------------------

_SPECS: Dict[str, Dict[str, Any]] = {
    "move_head": {
        "type": "function",
        "name": "move_head",
        "description": "Move your head in a given direction: left, right, up, down or front.",
        "parameters": {
            "type": "object",
            "properties": {
                "direction": {"type": "string", "enum": ["left", "right", "up", "down", "front"]},
            },
            "required": ["direction"],
        },
    },
    "dance": {
        "type": "function",
        "name": "dance",
        "description": "Play a named or random dance move once (or repeat). Non-blocking.",
        "parameters": {
            "type": "object",
            "properties": {
                "move": {"type": "string", "description": "Dance name, or 'random' to pick one."},
                "repeat": {"type": "integer", "description": "Times to repeat (default 1)."},
            },
            "required": [],
        },
    },
    "play_emotion": {
        "type": "function",
        "name": "play_emotion",
        "description": "Play a pre-recorded emotion clip (e.g. happy, surprised, laughing, thinking, greeting).",
        "parameters": {
            "type": "object",
            "properties": {
                "emotion": {"type": "string", "description": "Emotion clip name or alias."},
            },
            "required": ["emotion"],
        },
    },
    "stop_dance": {
        "type": "function",
        "name": "stop_dance",
        "description": "Stop the current dance move.",
        "parameters": {
            "type": "object",
            "properties": {"dummy": {"type": "boolean", "description": "dummy boolean, set it to true"}},
            "required": ["dummy"],
        },
    },
    "stop_emotion": {
        "type": "function",
        "name": "stop_emotion",
        "description": "Stop the current emotion.",
        "parameters": {
            "type": "object",
            "properties": {"dummy": {"type": "boolean", "description": "dummy boolean, set it to true"}},
            "required": ["dummy"],
        },
    },
    "head_tracking": {
        "type": "function",
        "name": "head_tracking",
        "description": "Start or stop real face tracking. Start scans the Reachy camera and only moves when a face is detected; otherwise report that no face is visible.",
        "parameters": {
            "type": "object",
            "properties": {"start": {"type": "boolean"}},
            "required": ["start"],
        },
    },
    "do_nothing": {
        "type": "function",
        "name": "do_nothing",
        "description": "Choose to do nothing — stay still and silent. Use when you want to be contemplative or just chill.",
        "parameters": {
            "type": "object",
            "properties": {"reason": {"type": "string"}},
            "required": [],
        },
    },
    "camera": {
        "type": "function",
        "name": "camera",
        "description": "Take a picture with the camera and ask a question about it.",
        "parameters": {
            "type": "object",
            "properties": {"question": {"type": "string"}},
            "required": ["question"],
        },
    },
    "task_status": {
        "type": "function",
        "name": "task_status",
        "description": "Check the status of background tool tasks.",
        "parameters": {
            "type": "object",
            "properties": {"tool_id": {"type": "string"}},
            "required": [],
        },
    },
    "task_cancel": {
        "type": "function",
        "name": "task_cancel",
        "description": "Cancel a running background tool task. Requires confirmation before cancelling.",
        "parameters": {
            "type": "object",
            "properties": {"tool_id": {"type": "string"}},
            "required": ["tool_id"],
        },
    },
    "update_memory_block": {
        "type": "function",
        "name": "update_memory_block",
        "description": (
            "Save something durable you just learned about the user into your "
            "long-term memory. Use this when the user tells you a fact about "
            "themselves you want to remember next session (their name, a "
            "preference, a recurring person/project) — NOT for ephemeral "
            "chitchat. The 'human' block stores facts about the user. The "
            "'relationship' block stores recurring topics or shared "
            "shorthand."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "block": {
                    "type": "string",
                    "enum": ["human", "relationship"],
                    "description": "Which memory block to update.",
                },
                "patch": {
                    "type": "string",
                    "description": (
                        "The fact to remember, written as one short line in "
                        "the third person about the user (e.g. 'Daughter is "
                        "named Mira, age 4'). Keep it under 140 chars."
                    ),
                },
                "reason": {
                    "type": "string",
                    "description": "Why this is worth remembering (one phrase).",
                },
                "mode": {
                    "type": "string",
                    "enum": ["append", "replace"],
                    "description": (
                        "'append' (default) adds a line; 'replace' overwrites "
                        "the entire block — only use replace for major life "
                        "changes you must correct."
                    ),
                },
            },
            "required": ["block", "patch", "reason"],
        },
    },
    "lookup_my_notes": {
        "type": "function",
        "name": "lookup_my_notes",
        "description": (
            "Search the user's Obsidian vault (their personal notes, "
            "journal, and reference library) for context relevant to the "
            "current conversation. Use when you need more detail than the "
            "system prompt already gave you about a project, a person, or "
            "an idea they're working on. Returns up to 3 short excerpts "
            "with their file paths."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural-language search query.",
                },
            },
            "required": ["query"],
        },
    },
    "get_schedule": {
        "type": "function",
        "name": "get_schedule",
        "description": "Summarize the user's upcoming calendar events.",
        "parameters": {
            "type": "object",
            "properties": {
                "hours": {"type": "integer", "description": "Lookahead window in hours, default 24."},
                "limit": {"type": "integer", "description": "Maximum events to return, default 5."},
            },
            "required": [],
        },
    },
    "get_inbox_summary": {
        "type": "function",
        "name": "get_inbox_summary",
        "description": "Summarize recent email from the user's inbox.",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Maximum messages to return, default 5."},
                "unread_only": {"type": "boolean", "description": "Only unread messages, default true."},
            },
            "required": [],
        },
    },
    "weather_now": {
        "type": "function",
        "name": "weather_now",
        "description": "Current weather (temperature, condition, wind, humidity) via Open-Meteo. Cached 10 min. Falls back to ZERO_DEFAULT_LAT/LON env if no coordinates given.",
        "parameters": {
            "type": "object",
            "properties": {
                "lat": {"type": "number", "description": "Latitude (decimal degrees). Optional."},
                "lon": {"type": "number", "description": "Longitude (decimal degrees). Optional."},
            },
            "required": [],
        },
    },
    "smart_home_status": {
        "type": "function",
        "name": "smart_home_status",
        "description": "Read Home Assistant entity states (lights, locks, climate, sensors). Returns a compact list with state and friendly name.",
        "parameters": {
            "type": "object",
            "properties": {
                "domain": {"type": "string", "description": "Optional HA domain filter, e.g. 'light', 'lock', 'climate'."},
                "contains": {"type": "string", "description": "Optional substring filter on entity name/id."},
                "limit": {"type": "integer", "description": "Max entities to return (default 25, max 40)."},
            },
            "required": [],
        },
    },
    "start_meeting_recording": {
        "type": "function",
        "name": "start_meeting_recording",
        "description": "Start recording a meeting from the Reachy microphone.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Optional meeting title."},
                "meeting_id": {"type": "string", "description": "Optional existing Zero meeting id."},
            },
            "required": [],
        },
    },
    "stop_meeting_recording": {
        "type": "function",
        "name": "stop_meeting_recording",
        "description": "Stop the current meeting recording and queue processing.",
        "parameters": {
            "type": "object",
            "properties": {"dummy": {"type": "boolean", "description": "dummy boolean, set it to true"}},
            "required": [],
        },
    },
    "start_focus_timer": {
        "type": "function",
        "name": "start_focus_timer",
        "description": "Start a Reachy-assisted focus timer with optional break length.",
        "parameters": {
            "type": "object",
            "properties": {
                "focus_minutes": {"type": "integer", "description": "Focus block length, default 25."},
                "break_minutes": {"type": "integer", "description": "Break length, default 5."},
            },
            "required": [],
        },
    },
    "set_persona": {
        "type": "function",
        "name": "set_persona",
        "description": "Switch Reachy's assistant persona/profile.",
        "parameters": {
            "type": "object",
            "properties": {
                "persona": {"type": "string", "description": "Persona id, e.g. assistant, companion, deep_work."},
            },
            "required": ["persona"],
        },
    },
    "set_ambient_mode": {
        "type": "function",
        "name": "set_ambient_mode",
        "description": "Enable or disable autonomous ambient Reachy presence gestures.",
        "parameters": {
            "type": "object",
            "properties": {
                "enabled": {"type": "boolean", "description": "true to enable ambient presence, false to disable."},
            },
            "required": ["enabled"],
        },
    },
    "robot_wake": {
        "type": "function",
        "name": "robot_wake",
        "description": "Wake the robot body into an active posture.",
        "parameters": {
            "type": "object",
            "properties": {"dummy": {"type": "boolean", "description": "dummy boolean, set it to true"}},
            "required": [],
        },
    },
    "robot_sleep": {
        "type": "function",
        "name": "robot_sleep",
        "description": "Put the robot body into its sleep/rest posture.",
        "parameters": {
            "type": "object",
            "properties": {"dummy": {"type": "boolean", "description": "dummy boolean, set it to true"}},
            "required": [],
        },
    },
    "zero_system_status": {
        "type": "function",
        "name": "zero_system_status",
        "description": "Check Reachy assistant health, robot connection, voice config, and ambient state.",
        "parameters": {
            "type": "object",
            "properties": {"dummy": {"type": "boolean", "description": "dummy boolean, set it to true"}},
            "required": [],
        },
    },
    "company_status": {
        "type": "function",
        "name": "company_status",
        "description": "Summarize ADA AI LLC company status: tasks, blockers, approvals, formation progress, and subagents.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Optional focus, e.g. formation, agents, finance."}},
            "required": [],
        },
    },
    "company_today": {
        "type": "function",
        "name": "company_today",
        "description": "Answer what Adam should work on today for the company.",
        "parameters": {
            "type": "object",
            "properties": {"dummy": {"type": "boolean", "description": "dummy boolean, set it to true"}},
            "required": [],
        },
    },
    "company_approvals": {
        "type": "function",
        "name": "company_approvals",
        "description": "List company approvals waiting on Adam.",
        "parameters": {
            "type": "object",
            "properties": {"dummy": {"type": "boolean", "description": "dummy boolean, set it to true"}},
            "required": [],
        },
    },
    "company_blockers": {
        "type": "function",
        "name": "company_blockers",
        "description": "List blocked company tasks and why they are blocked.",
        "parameters": {
            "type": "object",
            "properties": {"dummy": {"type": "boolean", "description": "dummy boolean, set it to true"}},
            "required": [],
        },
    },
    "company_create_task": {
        "type": "function",
        "name": "company_create_task",
        "description": "Create an internal company task after spoken confirmation. Never use for purchases, filings, tax elections, client/public messages, or account changes.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "description": {"type": "string"},
                "priority": {"type": "string", "enum": ["critical", "high", "medium", "low"]},
                "confirmed": {"type": "boolean", "description": "Must be true only after the user confirms the exact task aloud."},
            },
            "required": ["title", "confirmed"],
        },
    },
    "company_update_task_confirmed": {
        "type": "function",
        "name": "company_update_task_confirmed",
        "description": "Update an internal company task only after spoken confirmation.",
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "status": {"type": "string", "enum": ["backlog", "todo", "in_progress", "review", "testing", "done", "blocked"]},
                "priority": {"type": "string", "enum": ["critical", "high", "medium", "low"]},
                "blocked_reason": {"type": "string"},
                "confirmed": {"type": "boolean", "description": "Must be true only after the user confirms the exact update aloud."},
            },
            "required": ["task_id", "confirmed"],
        },
    },
    "delegate_research": {
        "type": "function",
        "name": "delegate_research",
        "description": "Spawn a researcher to investigate a question and bring back findings.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to research."},
            },
            "required": ["query"],
        },
    },
    "draft_email": {
        "type": "function",
        "name": "draft_email",
        "description": "Compose an email draft for Adam to review and approve. Never sends directly.",
        "parameters": {
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "Gmail account scope (e.g. 'work' or 'personal'). Defaults to 'default'."},
                "to": {"type": "string"},
                "subject": {"type": "string"},
                "body": {"type": "string"},
                "thread_id": {"type": "string"},
            },
            "required": ["to", "subject", "body"],
        },
    },
    "bookkeeping_query": {
        "type": "function",
        "name": "bookkeeping_query",
        "description": "Ask the ADA AI bookkeeper a question — revenue, expenses, taxes, pending drafts.",
        "parameters": {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
            },
            "required": ["question"],
        },
    },
    "supervisor_dispatch": {
        "type": "function",
        "name": "supervisor_dispatch",
        "description": "Hand the user's request to the supervisor agent which routes to the right sub-agent (email, calendar, company, research, bookkeeper, daily brief).",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
            },
            "required": ["text"],
        },
    },
}


async def _update_memory_block(
    _deps: ToolDependencies,
    args: Dict[str, Any],
    _mgr: BackgroundToolManager,
) -> Dict[str, Any]:
    from app.services.reachy_memory_blocks import update_memory_block_tool

    block = str(args.get("block") or "")
    patch = str(args.get("patch") or "").strip()
    reason = str(args.get("reason") or "")
    mode = str(args.get("mode") or "append")
    if not patch:
        return {"error": "patch is required"}
    return await update_memory_block_tool(block, patch, reason, mode=mode)


async def _lookup_my_notes(
    _deps: ToolDependencies,
    args: Dict[str, Any],
    _mgr: BackgroundToolManager,
) -> Dict[str, Any]:
    from app.services.vault_retrieval_service import VaultRetrievalService

    query = str(args.get("query") or "").strip()
    if not query:
        return {"error": "query is required"}
    try:
        svc = VaultRetrievalService()
        # No partition filter — the model decides relevance, we don't
        # pre-filter the user's notes by category.
        result = await svc.search(query, top_k=3, per_side_k=20)
    except Exception as e:
        return {"error": f"vault search failed: {type(e).__name__}: {e}"}
    hits = (result or {}).get("hits") or []
    excerpts = []
    for c in hits[:3]:
        body = (c.get("content") or "").strip().replace("\n", " ")
        if len(body) > 280:
            body = body[:280].rstrip() + "…"
        excerpts.append({"path": c.get("path") or "?", "excerpt": body})
    return {"excerpts": excerpts, "count": len(excerpts)}


def _attr_or_key(obj: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        if hasattr(obj, name):
            value = getattr(obj, name)
            if value is not None:
                return value
        if isinstance(obj, dict) and obj.get(name) is not None:
            return obj[name]
    return default


def _compact_text(value: Any, *, limit: int = 220) -> str:
    text = str(value or "").replace("\n", " ").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "..."


async def _get_schedule(
    _deps: ToolDependencies,
    args: Dict[str, Any],
    _mgr: BackgroundToolManager,
) -> Dict[str, Any]:
    from datetime import datetime, timedelta, timezone

    hours = int(args.get("hours") or 24)
    hours = max(1, min(168, hours))
    limit = int(args.get("limit") or 5)
    limit = max(1, min(10, limit))
    try:
        from app.services.calendar_service import get_calendar_service
        svc = get_calendar_service()
        now = datetime.now(tz=timezone.utc)
        events = await svc.list_events(
            start_date=now,
            end_date=now + timedelta(hours=hours),
            limit=limit,
        )
    except Exception as e:
        return {"error": f"calendar unavailable: {type(e).__name__}: {e}"}

    out = []
    for event in events[:limit]:
        title = _attr_or_key(event, "summary", "title", default="Untitled event")
        start = _attr_or_key(event, "start_time", "start", default=None)
        end = _attr_or_key(event, "end_time", "end", default=None)
        out.append({
            "title": _compact_text(title, limit=120),
            "start": str(start) if start is not None else None,
            "end": str(end) if end is not None else None,
        })
    return {"hours": hours, "count": len(out), "events": out}


async def _get_inbox_summary(
    _deps: ToolDependencies,
    args: Dict[str, Any],
    _mgr: BackgroundToolManager,
) -> Dict[str, Any]:
    limit = int(args.get("limit") or 5)
    limit = max(1, min(10, limit))
    unread_only = bool(args.get("unread_only", True))
    try:
        from app.models.email import EmailStatus
        from app.services.gmail_service import get_gmail_service

        svc = get_gmail_service()
        status = EmailStatus.UNREAD if unread_only else None
        emails = await svc.list_emails(status=status, limit=limit)
    except Exception as e:
        return {"error": f"inbox unavailable: {type(e).__name__}: {e}"}

    messages = []
    for msg in emails[:limit]:
        sender = _attr_or_key(msg, "sender", "from_name", "from_address", default="Unknown sender")
        subject = _attr_or_key(msg, "subject", default="No subject")
        snippet = _attr_or_key(msg, "snippet", "body_preview", default="")
        messages.append({
            "from": _compact_text(sender, limit=80),
            "subject": _compact_text(subject, limit=120),
            "snippet": _compact_text(snippet, limit=180),
        })
    return {"unread_only": unread_only, "count": len(messages), "messages": messages}


_WEATHER_CACHE: dict[str, Any] = {"at": 0.0, "lat": None, "lon": None, "payload": None}


async def _weather_now(
    _deps: ToolDependencies,
    args: Dict[str, Any],
    _mgr: BackgroundToolManager,
) -> Dict[str, Any]:
    """Current weather via Open-Meteo (no API key). Cached 10 min per location."""
    import os
    try:
        lat = float(args.get("lat") or os.getenv("ZERO_DEFAULT_LAT") or 40.7128)
        lon = float(args.get("lon") or os.getenv("ZERO_DEFAULT_LON") or -74.0060)
    except (TypeError, ValueError):
        return {"error": "lat and lon must be numbers"}
    now = time.monotonic()
    if (
        _WEATHER_CACHE["payload"]
        and _WEATHER_CACHE["lat"] == lat
        and _WEATHER_CACHE["lon"] == lon
        and now - _WEATHER_CACHE["at"] < 600.0
    ):
        return {**_WEATHER_CACHE["payload"], "cached": True}
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        "&current=temperature_2m,apparent_temperature,relative_humidity_2m,"
        "weather_code,wind_speed_10m,is_day"
        "&temperature_unit=fahrenheit&wind_speed_unit=mph&timezone=auto"
    )
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(8.0, connect=3.0)) as client:
            resp = await client.get(url)
        if resp.status_code >= 400:
            return {"error": f"open-meteo {resp.status_code}: {resp.text[:160]}"}
        data = resp.json()
    except Exception as e:
        return {"error": f"weather unavailable: {type(e).__name__}: {e}"}
    current = (data or {}).get("current") or {}
    code_to_text = {
        0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "overcast",
        45: "fog", 48: "icy fog", 51: "light drizzle", 53: "drizzle", 55: "heavy drizzle",
        61: "light rain", 63: "rain", 65: "heavy rain",
        71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains",
        80: "rain showers", 81: "heavy showers", 82: "violent showers",
        85: "snow showers", 86: "heavy snow showers",
        95: "thunderstorm", 96: "thunderstorm with hail", 99: "severe thunderstorm",
    }
    code = current.get("weather_code")
    payload = {
        "lat": lat,
        "lon": lon,
        "temperature_f": current.get("temperature_2m"),
        "apparent_temperature_f": current.get("apparent_temperature"),
        "humidity_pct": current.get("relative_humidity_2m"),
        "wind_mph": current.get("wind_speed_10m"),
        "is_day": bool(current.get("is_day")),
        "condition": code_to_text.get(int(code), f"code {code}") if code is not None else None,
        "observed_at": current.get("time"),
    }
    _WEATHER_CACHE.update({"at": now, "lat": lat, "lon": lon, "payload": payload})
    return payload


_HA_INTERESTING_DOMAINS = ("light", "switch", "lock", "climate", "media_player", "binary_sensor", "sensor", "alarm_control_panel")


async def _smart_home_status(
    _deps: ToolDependencies,
    args: Dict[str, Any],
    _mgr: BackgroundToolManager,
) -> Dict[str, Any]:
    """Compact Home Assistant snapshot: which lights are on, doors open, etc."""
    try:
        from app.services.home_assistant_service import get_home_assistant_service
        svc = get_home_assistant_service()
        if not svc.configured:
            return {"configured": False, "detail": "Home Assistant base/token not set."}
        states = await svc.list_states()
    except Exception as e:
        return {"error": f"home assistant unavailable: {type(e).__name__}: {e}"}
    if not isinstance(states, list):
        return {"error": "home assistant returned no state list"}

    domain_filter = args.get("domain")
    name_filter = (args.get("contains") or "").strip().lower() or None
    limit = max(1, min(40, int(args.get("limit") or 25)))

    interesting: list[dict[str, Any]] = []
    for entry in states:
        if not isinstance(entry, dict):
            continue
        entity_id = str(entry.get("entity_id") or "")
        if "." not in entity_id:
            continue
        domain = entity_id.split(".", 1)[0]
        if domain_filter and domain != domain_filter:
            continue
        if not domain_filter and domain not in _HA_INTERESTING_DOMAINS:
            continue
        attrs = entry.get("attributes") or {}
        friendly = str(attrs.get("friendly_name") or entity_id)
        if name_filter and name_filter not in friendly.lower() and name_filter not in entity_id.lower():
            continue
        interesting.append({
            "entity_id": entity_id,
            "name": friendly,
            "state": entry.get("state"),
            "domain": domain,
        })
    interesting.sort(key=lambda r: (r["domain"], r["name"]))
    on_count = sum(1 for r in interesting if r["state"] == "on")
    return {
        "configured": True,
        "total_entities_returned": min(len(interesting), limit),
        "total_entities_matching": len(interesting),
        "on_count": on_count,
        "entities": interesting[:limit],
    }


async def _host_agent_request(method: str, path: str, body: dict | None = None) -> Dict[str, Any]:
    import httpx
    from app.infrastructure.config import get_settings

    base = (get_settings().host_agent_url or "http://host.docker.internal:18796").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=3.0)) as client:
            resp = await client.request(method, f"{base}{path}", json=body)
        if resp.status_code >= 400:
            return {"error": f"host_agent {resp.status_code}: {resp.text[:220]}"}
        return resp.json() if resp.content else {"ok": True}
    except Exception as e:
        return {"error": f"host_agent unreachable: {e}"}


async def _start_meeting_recording(
    _deps: ToolDependencies,
    args: Dict[str, Any],
    _mgr: BackgroundToolManager,
) -> Dict[str, Any]:
    title = _compact_text(args.get("title") or "Reachy voice meeting", limit=120)
    return await _host_agent_request(
        "POST",
        "/record/start",
        {"title": title, "source": "mic", "meeting_id": args.get("meeting_id")},
    )


async def _stop_meeting_recording(
    _deps: ToolDependencies,
    _args: Dict[str, Any],
    _mgr: BackgroundToolManager,
) -> Dict[str, Any]:
    return await _host_agent_request("POST", "/record/stop")


async def _start_focus_timer(
    _deps: ToolDependencies,
    args: Dict[str, Any],
    _mgr: BackgroundToolManager,
) -> Dict[str, Any]:
    focus_minutes = int(args.get("focus_minutes") or 25)
    break_minutes = int(args.get("break_minutes") or 5)
    focus_minutes = max(5, min(90, focus_minutes))
    break_minutes = max(1, min(30, break_minutes))
    try:
        from app.services.reachy_presence_service import get_reachy_presence_service
        return await get_reachy_presence_service().pomodoro_start(
            focus_minutes=focus_minutes,
            break_minutes=break_minutes,
        )
    except Exception as e:
        return {"error": f"focus timer unavailable: {type(e).__name__}: {e}"}


async def _set_persona(
    _deps: ToolDependencies,
    args: Dict[str, Any],
    _mgr: BackgroundToolManager,
) -> Dict[str, Any]:
    persona = str(args.get("persona") or "assistant").strip()
    if not persona:
        return {"error": "persona is required"}
    try:
        from app.services.reachy_realtime.config_store import update_config
        cfg = update_config({"profile": persona})
        return {
            "status": "selected",
            "persona": persona,
            "profile": cfg.get("profile") or persona,
        }
    except Exception as e:
        return {"error": f"persona switch failed: {type(e).__name__}: {e}"}


async def _set_ambient_mode(
    _deps: ToolDependencies,
    args: Dict[str, Any],
    _mgr: BackgroundToolManager,
) -> Dict[str, Any]:
    enabled = bool(args.get("enabled"))
    if enabled:
        locked = _motion_policy_error("ambient_mode", action="body_motion")
        if locked:
            return locked
    try:
        from app.services.reachy_presence_service import get_reachy_presence_service
        svc = get_reachy_presence_service()
        return svc.ambient_start() if enabled else svc.ambient_stop()
    except Exception as e:
        return {"error": f"ambient mode failed: {type(e).__name__}: {e}"}


async def _robot_wake(
    _deps: ToolDependencies,
    _args: Dict[str, Any],
    _mgr: BackgroundToolManager,
) -> Dict[str, Any]:
    locked = _motion_policy_error("robot_wake", action="gesture")
    if locked:
        return locked
    try:
        from app.services.reachy_service import get_reachy_service
        return await get_reachy_service().wake_up()
    except Exception as e:
        return {"error": f"robot wake failed: {type(e).__name__}: {e}"}


async def _robot_sleep(
    _deps: ToolDependencies,
    _args: Dict[str, Any],
    _mgr: BackgroundToolManager,
) -> Dict[str, Any]:
    locked = _motion_policy_error("robot_sleep", action="gesture")
    if locked:
        return locked
    try:
        from app.services.reachy_service import get_reachy_service
        return await get_reachy_service().goto_sleep()
    except Exception as e:
        return {"error": f"robot sleep failed: {type(e).__name__}: {e}"}


async def _zero_system_status(
    _deps: ToolDependencies,
    _args: Dict[str, Any],
    _mgr: BackgroundToolManager,
) -> Dict[str, Any]:
    try:
        from app.services.reachy_realtime.config_store import load_config_masked
        from app.services.reachy_service import get_reachy_service
        from app.services.reachy_presence_service import get_reachy_presence_service

        svc = get_reachy_service()
        connected = await svc.is_connected()
        return {
            "reachy_connected": connected,
            "reachy": svc.get_status_info(),
            "voice": load_config_masked(),
            "ambient": get_reachy_presence_service().ambient_state(),
        }
    except Exception as e:
        return {"error": f"system status failed: {type(e).__name__}: {e}"}


async def _company_status(
    _deps: ToolDependencies,
    args: Dict[str, Any],
    _mgr: BackgroundToolManager,
) -> Dict[str, Any]:
    from app.services.company_operator_service import get_company_operator_service

    query = str(args.get("query") or "company status")
    return await get_company_operator_service().spoken_company_summary(query)


async def _company_today(
    _deps: ToolDependencies,
    _args: Dict[str, Any],
    _mgr: BackgroundToolManager,
) -> Dict[str, Any]:
    from app.services.company_operator_service import get_company_operator_service

    today = await get_company_operator_service().today()
    return {"response_text": today["answer"], "today": today}


async def _company_approvals(
    _deps: ToolDependencies,
    _args: Dict[str, Any],
    _mgr: BackgroundToolManager,
) -> Dict[str, Any]:
    from app.services.company_operator_service import get_company_operator_service

    return await get_company_operator_service().spoken_company_summary("company approvals")


async def _company_blockers(
    _deps: ToolDependencies,
    _args: Dict[str, Any],
    _mgr: BackgroundToolManager,
) -> Dict[str, Any]:
    from app.services.company_operator_service import get_company_operator_service

    return await get_company_operator_service().spoken_company_summary("company blockers")


async def _company_create_task(
    _deps: ToolDependencies,
    args: Dict[str, Any],
    _mgr: BackgroundToolManager,
) -> Dict[str, Any]:
    from app.models.task import TaskCategory, TaskCreate, TaskPriority, TaskSource
    from app.services.company_operator_service import get_company_operator_service

    title = _compact_text(args.get("title"), limit=500)
    if not title:
        return {"error": "title is required"}
    if not bool(args.get("confirmed")):
        return {
            "status": "needs_confirmation",
            "response_text": f"Confirm before I create this company task: {title}",
            "title": title,
        }
    priority = str(args.get("priority") or "medium")
    if priority not in {"critical", "high", "medium", "low"}:
        priority = "medium"
    task = await get_company_operator_service().create_company_task(
        TaskCreate(
            title=title,
            description=str(args.get("description") or ""),
            category=TaskCategory.CHORE,
            priority=TaskPriority(priority),
            source=TaskSource.MANUAL,
            source_reference="reachy_voice",
        )
    )
    return {"status": "created", "task": task.model_dump(mode="json"), "response_text": f"Created company task: {task.title}."}


async def _company_update_task_confirmed(
    _deps: ToolDependencies,
    args: Dict[str, Any],
    _mgr: BackgroundToolManager,
) -> Dict[str, Any]:
    from app.models.task import TaskPriority, TaskStatus, TaskUpdate
    from app.services.company_operator_service import get_company_operator_service

    task_id = str(args.get("task_id") or "").strip()
    if not task_id:
        return {"error": "task_id is required"}
    if not bool(args.get("confirmed")):
        return {
            "status": "needs_confirmation",
            "response_text": f"Confirm before I update company task {task_id}.",
            "task_id": task_id,
        }

    update: dict[str, Any] = {}
    status = args.get("status")
    if status in {"backlog", "todo", "in_progress", "review", "testing", "done", "blocked"}:
        update["status"] = TaskStatus(str(status))
    priority = args.get("priority")
    if priority in {"critical", "high", "medium", "low"}:
        update["priority"] = TaskPriority(str(priority))
    if args.get("blocked_reason"):
        update["blocked_reason"] = str(args.get("blocked_reason"))
    if not update:
        return {"error": "no valid updates provided"}

    task = await get_company_operator_service().update_company_task(task_id, TaskUpdate(**update))
    if not task:
        return {"error": f"task {task_id} not found"}
    return {"status": "updated", "task": task.model_dump(mode="json"), "response_text": f"Updated company task: {task.title}."}


async def _delegate_research(deps: ToolDependencies, args: Dict[str, Any], _mgr: BackgroundToolManager) -> Dict[str, Any]:
    query = str(args.get("query") or "").strip()
    if not query:
        return {"error": "missing query"}
    try:
        from app.services.supervisor_graph import get_supervisor
        res = await get_supervisor().handle(query, persona_id=str((deps.extra or {}).get("profile_id") or "default"))
        return {"response_text": res.spoken or "Researcher dispatched.", "intent": res.intent, "tool_calls": res.tool_calls}
    except Exception as e:
        return {"error": str(e), "response_text": "I couldn't reach the research supervisor."}


async def _draft_email(deps: ToolDependencies, args: Dict[str, Any], _mgr: BackgroundToolManager) -> Dict[str, Any]:
    to = str(args.get("to") or "").strip()
    subject = str(args.get("subject") or "").strip()
    body = str(args.get("body") or "").strip()
    account_id = str(args.get("account_id") or "default").strip() or "default"
    thread_id = args.get("thread_id")
    if not to or not subject or not body:
        return {"error": "to, subject, and body are required"}
    try:
        from app.services.email_draft_pool_service import get_email_draft_pool
        d = await get_email_draft_pool().add_draft(
            account_id=account_id, to=to, subject=subject, body=body,
            thread_id=thread_id,
            meta={"source": "reachy_realtime", "user_text": str((deps.extra or {}).get("latest_user_text") or "")},
        )
        return {
            "response_text": f"I drafted a reply to {to}. Approve it from the drafts inbox or say 'send it'.",
            "draft_id": d.id,
            "account_id": d.account_id,
        }
    except Exception as e:
        return {"error": str(e), "response_text": "I couldn't save the draft."}


async def _bookkeeping_query(deps: ToolDependencies, args: Dict[str, Any], _mgr: BackgroundToolManager) -> Dict[str, Any]:
    q = str(args.get("question") or "").strip()
    if not q:
        return {"error": "missing question"}
    try:
        from app.services.bookkeeper_service import get_bookkeeper_service
        ans = await get_bookkeeper_service().answer_voice_question(q)
        return {"response_text": ans}
    except Exception as e:
        return {"error": str(e), "response_text": "I can't reach the bookkeeper."}


async def _supervisor_dispatch(deps: ToolDependencies, args: Dict[str, Any], _mgr: BackgroundToolManager) -> Dict[str, Any]:
    text = str(args.get("text") or (deps.extra or {}).get("latest_user_text") or "").strip()
    if not text:
        return {"error": "missing text"}
    try:
        from app.services.supervisor_graph import get_supervisor
        res = await get_supervisor().handle(text, persona_id=str((deps.extra or {}).get("profile_id") or "default"))
        return {"response_text": res.spoken or "OK", "intent": res.intent, "tool_calls": res.tool_calls}
    except Exception as e:
        return {"error": str(e), "response_text": "Supervisor unavailable."}


_HANDLERS: Dict[str, ToolHandler] = {
    "move_head": _move_head,
    "dance": _dance,
    "play_emotion": _play_emotion,
    "stop_dance": _stop_dance,
    "stop_emotion": _stop_emotion,
    "head_tracking": _head_tracking,
    "do_nothing": _do_nothing,
    "camera": _camera,
    "task_status": _task_status,
    "task_cancel": _task_cancel,
    "update_memory_block": _update_memory_block,
    "lookup_my_notes": _lookup_my_notes,
    "get_schedule": _get_schedule,
    "get_inbox_summary": _get_inbox_summary,
    "weather_now": _weather_now,
    "smart_home_status": _smart_home_status,
    "start_meeting_recording": _start_meeting_recording,
    "stop_meeting_recording": _stop_meeting_recording,
    "start_focus_timer": _start_focus_timer,
    "set_persona": _set_persona,
    "set_ambient_mode": _set_ambient_mode,
    "robot_wake": _robot_wake,
    "robot_sleep": _robot_sleep,
    "zero_system_status": _zero_system_status,
    "company_status": _company_status,
    "company_today": _company_today,
    "company_approvals": _company_approvals,
    "company_blockers": _company_blockers,
    "company_create_task": _company_create_task,
    "company_update_task_confirmed": _company_update_task_confirmed,
    "delegate_research": _delegate_research,
    "draft_email": _draft_email,
    "bookkeeping_query": _bookkeeping_query,
    "supervisor_dispatch": _supervisor_dispatch,
}


ALL_TOOL_NAMES: tuple[str, ...] = tuple(_HANDLERS.keys())
# Always-on tools regardless of profile-level tools.txt allow-listing —
# memory and vault are core to Zero's identity, not optional add-ons.
SYSTEM_TOOL_NAMES: frozenset[str] = frozenset({
    "task_status",
    "task_cancel",
    "update_memory_block",
    "lookup_my_notes",
})
def get_tool_specs(enabled: Optional[list[str]] = None) -> list[Dict[str, Any]]:
    """Return specs for the tools this session should expose.

    ``enabled`` is the list from the profile's ``tools.txt`` (or None for
    everything). System tools (``task_status``, ``task_cancel``) are always
    appended — they're how the model introspects running background work.
    """
    names: list[str]
    if enabled is None:
        names = list(_SPECS.keys())
    else:
        allowed = set(enabled) | SYSTEM_TOOL_NAMES
        names = [n for n in _SPECS.keys() if n in allowed]
    return [_SPECS[n] for n in names if n in _SPECS]


async def dispatch(
    tool_name: str,
    args_json: str,
    deps: ToolDependencies,
    mgr: BackgroundToolManager,
) -> Dict[str, Any]:
    """Parse args, resolve the handler, invoke it safely."""
    handler = _HANDLERS.get(tool_name)
    if handler is None:
        return {"error": f"unknown tool: {tool_name}"}
    try:
        args = json.loads(args_json) if args_json else {}
        if not isinstance(args, dict):
            args = {}
    except Exception:
        logger.warning("bad_tool_args", tool=tool_name, args=args_json)
        args = {}
    try:
        return await handler(deps, args, mgr)
    except Exception as e:
        logger.exception("tool_dispatch_failed", tool=tool_name)
        return {"error": f"{type(e).__name__}: {e}"}
