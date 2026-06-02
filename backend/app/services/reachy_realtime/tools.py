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

# Strong refs for fire-and-forget background tasks. CPython only keeps a weak
# ref to a running task, so an unheld create_task() result can be GC'd before
# it finishes; tasks self-remove on done.
_BG_FOLLOWUP_TASKS: set = set()


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
        "description": "Start recording a meeting from the Zero microphone.",
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
        "description": "Check Zero assistant health, robot connection, voice config, and ambient state.",
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
        "description": "Hand the user's request to the supervisor agent which routes to the right sub-agent (email, calendar, company, research, bookkeeper, daily brief, meeting RAG).",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
            },
            "required": ["text"],
        },
    },
    "meeting_rag_query": {
        "type": "function",
        "name": "meeting_rag_query",
        "description": "Search the meeting archive (transcripts + summaries) and answer a question about what was said, who said it, or what was agreed. Use for questions like 'what did Sarah say about the budget?' or 'recap yesterday's standup'.",
        "parameters": {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "meeting_id": {
                    "type": "string",
                    "description": "Optional: restrict the search to a specific meeting id.",
                },
                "speaker": {
                    "type": "string",
                    "description": "Optional: restrict to a specific diarized speaker label.",
                },
                "topic_label": {
                    "type": "string",
                    "description": "Optional: bias results toward segments inside topics matching this label (F-91). Auto-extracted from 'about X' phrasings when omitted.",
                },
            },
            "required": ["question"],
        },
    },
    "mark_meeting_private": {
        "type": "function",
        "name": "mark_meeting_private",
        "description": "Mark the currently-recording meeting as private. The recording stays on local disk for the user's reference, but the transcript will NOT be summarized, indexed, or used to draft follow-up emails. Use when the user says 'this is private', 'don't share this', 'mark this private', or 'don't summarise this one'.",
        "parameters": {
            "type": "object",
            "properties": {
                "meeting_id": {
                    "type": "string",
                    "description": "Optional. Defaults to whatever meeting is currently active (companion policy.meeting_active_id).",
                },
            },
        },
    },
    "summarize_current_meeting": {
        "type": "function",
        "name": "summarize_current_meeting",
        "description": "Summarise the meeting that is recording RIGHT NOW (uses companion policy.meeting_active_id). Use when the user asks 'summarise so far', 'recap so far', or 'what have we covered'.",
        "parameters": {"type": "object", "properties": {}},
    },
    "regenerate_summary": {
        "type": "function",
        "name": "regenerate_summary",
        "description": "Re-run summarization on the active or most-recent meeting and re-render its vault markdown. Use when the user says 'redo the summary', 'try the summary again', 'make a better summary', or 'rebuild the recap'.",
        "parameters": {
            "type": "object",
            "properties": {
                "meeting_id": {
                    "type": "string",
                    "description": "Optional. Defaults to companion policy.meeting_active_id or the most recent completed meeting.",
                },
            },
        },
    },
    "enroll_voice_from_meeting": {
        "type": "function",
        "name": "enroll_voice_from_meeting",
        "description": "Attach a real person's display name to a diarized speaker cluster from the active or most-recent meeting (voice modality). Use when the user says 'enroll Sarah's voice', 'save SPEAKER_01's voice as Mike', 'remember this voice as Mike', etc. Computes the centroid embedding from that speaker's transcript segments and enrolls it as a voiceprint.",
        "parameters": {
            "type": "object",
            "properties": {
                "display_name": {"type": "string"},
                "speaker_label": {
                    "type": "string",
                    "description": "Diarization label like SPEAKER_01 (defaults to the speaker with the most segments).",
                },
                "meeting_id": {
                    "type": "string",
                    "description": "Optional. Defaults to companion policy.meeting_active_id or the most recent meeting with transcript segments.",
                },
                "is_primary": {
                    "type": "boolean",
                    "description": "Set true to mark this person as the primary user (e.g., Adam).",
                    "default": False,
                },
            },
            "required": ["display_name"],
        },
    },
    "enroll_face_from_meeting": {
        "type": "function",
        "name": "enroll_face_from_meeting",
        "description": "Attach a real person's display name to an unknown face cluster from the active or most-recent meeting. Use when the user says 'that was Sarah', 'label SPEAKER_01 as Sarah', 'enroll the new face as Mike', etc. Pulls the latest face cluster centroid + crop from the meeting's face-match step and enrolls it as a faceprint.",
        "parameters": {
            "type": "object",
            "properties": {
                "display_name": {"type": "string", "description": "Human name to attach (e.g., 'Sarah Smith')."},
                "speaker_label": {
                    "type": "string",
                    "description": "Optional. The SPEAKER_XX or 'Unknown #2' label from the transcript. When omitted, attaches to the most-recently-clustered face.",
                },
                "meeting_id": {
                    "type": "string",
                    "description": "Optional. Defaults to companion policy.meeting_active_id or the most recent completed meeting.",
                },
            },
            "required": ["display_name"],
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
    title = _compact_text(args.get("title") or "Zero voice meeting", limit=120)
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
    # Fix-96: validate against the known persona set before persisting. A
    # misheard voice command ("switch to persona banana") otherwise writes a
    # bogus profile id that get_profile() silently falls back to default on,
    # leaving the stored config wrong. Skip the guard only if profiles can't be
    # enumerated (infra failure) so we never harden into a hard block.
    try:
        from app.services.reachy_realtime.profiles import list_profiles
        valid = {p.id for p in list_profiles()}
    except Exception:
        valid = set()
    if valid and persona not in valid:
        return {
            "error": f"unknown persona '{persona}'",
            "valid_personas": sorted(valid),
        }
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


async def _mark_meeting_private(deps: ToolDependencies, args: Dict[str, Any], _mgr: BackgroundToolManager) -> Dict[str, Any]:
    """Mark the currently-recording meeting private. Reads the active
    meeting from companion policy when ``meeting_id`` is not supplied."""
    meeting_id = str(args.get("meeting_id") or "").strip()
    if not meeting_id:
        try:
            from app.services.reachy_companion_service import (
                get_reachy_companion_service,
            )
            policy = get_reachy_companion_service().get_policy()
            meeting_id = policy.meeting_active_id or ""
        except Exception:
            meeting_id = ""
    if not meeting_id:
        return {
            "error": "no active meeting",
            "response_text": "There's no meeting being recorded right now.",
        }
    try:
        from app.services.meeting_privacy_service import (
            get_meeting_privacy_service,
        )

        get_meeting_privacy_service().mark_private(meeting_id, source="voice")
        return {
            "meeting_id": meeting_id,
            "response_text": "Got it — this one stays private. No summary, no email follow-up, no search index.",
        }
    except Exception as e:
        return {
            "error": str(e),
            "response_text": "Couldn't mark the meeting private right now.",
        }


async def _regenerate_summary(deps: ToolDependencies, args: Dict[str, Any], _mgr: BackgroundToolManager) -> Dict[str, Any]:
    """Voice 'Hey Zero, redo the summary'. Re-runs meeting_summary_service
    on the meeting's stored transcript and rewrites the vault markdown."""
    meeting_id = str(args.get("meeting_id") or "").strip()
    if not meeting_id:
        try:
            from app.services.reachy_companion_service import (
                get_reachy_companion_service,
            )
            meeting_id = (
                get_reachy_companion_service().get_policy().meeting_active_id or ""
            )
        except Exception:
            meeting_id = ""
    if not meeting_id:
        # Fall back to the most-recent meeting that has transcript segments.
        try:
            from sqlalchemy import select, func
            from app.infrastructure.database import get_session
            from app.db.models import (  # type: ignore
                MeetingModel,
                MeetingTranscriptSegmentModel,
            )

            async with get_session() as db:
                row = (
                    await db.execute(
                        select(MeetingTranscriptSegmentModel.meeting_id, func.max(MeetingTranscriptSegmentModel.id))
                        .group_by(MeetingTranscriptSegmentModel.meeting_id)
                        .order_by(func.max(MeetingTranscriptSegmentModel.id).desc())
                        .limit(1)
                    )
                ).first()
                if row:
                    meeting_id = row[0]
        except Exception as exc:
            logger.debug("regenerate_summary_fallback_failed", error=str(exc))
    if not meeting_id:
        return {
            "error": "no meeting",
            "response_text": "I couldn't find a meeting to re-summarise.",
        }
    try:
        import time
        import uuid
        from sqlalchemy import select, delete
        from app.infrastructure.database import get_session
        from app.db.models import (  # type: ignore
            MeetingModel,
            MeetingTranscriptSegmentModel,
            MeetingSummaryModel,
            MeetingRecordingModel,
        )
        from app.services.meeting_summary_service import get_meeting_summary_service
        from app.services.meeting_vault_writer import get_meeting_vault_writer
        from app.services.meeting_privacy_service import get_meeting_privacy_service
        from app.infrastructure.config import get_settings

        async with get_session() as db:
            meeting = (
                await db.execute(select(MeetingModel).where(MeetingModel.id == meeting_id))
            ).scalar_one_or_none()
            if meeting is None:
                return {"error": "meeting_not_found", "response_text": "That meeting isn't on file."}
            segments = (
                await db.execute(
                    select(MeetingTranscriptSegmentModel)
                    .where(MeetingTranscriptSegmentModel.meeting_id == meeting_id)
                    .order_by(MeetingTranscriptSegmentModel.start_time.asc())
                )
            ).scalars().all()
            recording = (
                await db.execute(
                    select(MeetingRecordingModel)
                    .where(MeetingRecordingModel.meeting_id == meeting_id)
                    .order_by(MeetingRecordingModel.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
        if not segments:
            return {
                "error": "no_segments",
                "response_text": "That meeting has no transcript yet. Wait for transcription to finish.",
            }
        transcript_text = "\n".join(
            f"[{seg.speaker or 'Speaker'}]: {seg.text}" for seg in segments
        )
        title = getattr(meeting, "title", "") or ""
        t0 = time.time()
        summary_data = await get_meeting_summary_service().summarize(
            transcript_text, meeting_title=title
        )
        elapsed = int((time.time() - t0) * 1000)
        async with get_session() as db:
            await db.execute(
                delete(MeetingSummaryModel).where(MeetingSummaryModel.meeting_id == meeting_id)
            )
            db.add(MeetingSummaryModel(
                id=uuid.uuid4().hex,
                meeting_id=meeting_id,
                summary_text=summary_data.get("summary_text", "") or "",
                key_topics=summary_data.get("key_topics", []) or [],
                action_items=summary_data.get("action_items", []) or [],
                decisions=summary_data.get("decisions", []) or [],
                model_used=get_settings().ollama_model,
                generation_time_ms=elapsed,
            ))
            await db.commit()
        # Re-render vault markdown with the new summary.
        try:
            speakers = sorted({s.speaker for s in segments if s.speaker})
            vault_res = get_meeting_vault_writer().write(
                meeting_id=meeting_id,
                title=title or "Untitled meeting",
                start_time=meeting.start_time,
                end_time=meeting.end_time,
                attendees=list(meeting.participants or []),
                summary_text=summary_data.get("summary_text", "") or "",
                key_topics=summary_data.get("key_topics", []) or [],
                action_items=summary_data.get("action_items", []) or [],
                decisions=summary_data.get("decisions", []) or [],
                transcript_segment_count=len(segments),
                recording_path=getattr(recording, "file_path", None) if recording else None,
                speakers=speakers,
                private=get_meeting_privacy_service().is_private(meeting_id),
            )
        except Exception as exc:
            vault_res = {"ok": False, "reason": str(exc)}
        action_count = len(summary_data.get("action_items", []) or [])
        # F-95: kick the follow-up service so the new action items + draft
        # emails reflect the regenerated summary. Idempotent via the
        # followup ledger; existing tasks stay, only new items spawn.
        followup_kicked = False
        try:
            import asyncio as _asyncio
            from app.services.meeting_followup_service import (
                get_meeting_followup_service,
            )

            _fu_task = _asyncio.create_task(
                get_meeting_followup_service().run(
                    meeting_id=meeting_id, max_wait_for_summary_s=10
                )
            )
            _BG_FOLLOWUP_TASKS.add(_fu_task)
            _fu_task.add_done_callback(_BG_FOLLOWUP_TASKS.discard)
            followup_kicked = True
        except Exception as exc:
            logger.debug("regenerate_summary_followup_kick_failed", error=str(exc))
        return {
            "ok": True,
            "meeting_id": meeting_id,
            "elapsed_ms": elapsed,
            "action_items": action_count,
            "vault": vault_res,
            "followup_kicked": followup_kicked,
            "response_text": (
                f"Re-summarised in {elapsed} ms — {action_count} action item"
                f"{'s' if action_count != 1 else ''}. Vault and follow-ups are refreshed."
            ),
        }
    except Exception as e:
        logger.warning("regenerate_summary_failed", error=str(e))
        return {"error": str(e), "response_text": "Re-summarising failed."}


async def _enroll_face_from_meeting(deps: ToolDependencies, args: Dict[str, Any], _mgr: BackgroundToolManager) -> Dict[str, Any]:
    """Voice 'Hey Zero, that was Sarah'. Re-clusters frames from the
    target meeting, picks the matching cluster, enrolls its centroid
    embedding as a faceprint under the user-supplied display name."""
    display_name = str(args.get("display_name") or "").strip()
    if not display_name:
        return {"error": "missing display_name", "response_text": "I need a name to enroll the face under."}
    meeting_id = str(args.get("meeting_id") or "").strip()
    speaker_label = str(args.get("speaker_label") or "").strip()
    if not meeting_id:
        try:
            from app.services.reachy_companion_service import (
                get_reachy_companion_service,
            )

            meeting_id = (
                get_reachy_companion_service().get_policy().meeting_active_id or ""
            )
        except Exception:
            meeting_id = ""
    if not meeting_id:
        # Fall back to the most-recent meeting with face frames.
        try:
            from app.infrastructure.config import get_workspace_path

            frames_root = get_workspace_path("meetings")
            candidates = sorted(
                [p for p in frames_root.iterdir() if p.is_dir() and (p / "frames").exists()],
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            if candidates:
                meeting_id = candidates[0].name
        except Exception:
            pass
    if not meeting_id:
        return {
            "error": "no meeting",
            "response_text": "I couldn't find a meeting with face frames. Was the camera on?",
        }
    try:
        from pathlib import Path

        from app.services.meeting_face_service import (
            extract_faces_from_meeting,
            get_faceprint_service,
        )
        from app.infrastructure.config import get_workspace_path

        frames_dir: Path = get_workspace_path("meetings") / meeting_id / "frames"
        if not frames_dir.exists():
            return {
                "error": "no_frames",
                "response_text": "That meeting doesn't have face frames captured.",
            }
        clusters = extract_faces_from_meeting(meeting_id, frames_dir)
        if not clusters:
            return {
                "error": "no_clusters",
                "response_text": "I see frames but couldn't find any faces in them.",
            }
        # Pick the cluster: if a speaker_label is provided and it looks
        # like a numeric index (SPEAKER_03 or cluster id 3), use it;
        # otherwise default to the largest cluster (most frames).
        chosen = None
        if speaker_label:
            import re
            m = re.search(r"(\d+)", speaker_label)
            if m:
                cid = int(m.group(1))
                chosen = next((c for c in clusters if c.cluster_id == cid), None)
        if chosen is None:
            chosen = max(clusters, key=lambda c: len(c.frames))
        if chosen.centroid is None:
            return {
                "error": "no_embedding",
                "response_text": "I couldn't compute a face embedding for that cluster.",
            }
        svc = get_faceprint_service()
        row, replaced = await svc.enroll(
            display_name=display_name,
            embedding=chosen.centroid.astype("float32"),
            sample_count=len(chosen.frames),
            source_meeting_id=meeting_id,
        )
        action = "updated" if replaced else "enrolled"
        return {
            "ok": True,
            "faceprint_id": row.id,
            "display_name": display_name,
            "meeting_id": meeting_id,
            "cluster_id": chosen.cluster_id,
            "sample_count": len(chosen.frames),
            "response_text": f"Got it — {action} {display_name} from {len(chosen.frames)} frames in that meeting.",
        }
    except Exception as e:
        logger.warning("enroll_face_from_meeting_failed", error=str(e))
        return {
            "error": str(e),
            "response_text": "Face enrollment failed.",
        }


async def _enroll_voice_from_meeting(deps: ToolDependencies, args: Dict[str, Any], _mgr: BackgroundToolManager) -> Dict[str, Any]:
    """F-24 — voice 'Hey Zero, enroll Sarah's voice'. Computes a
    voiceprint centroid from the chosen speaker's transcript segments
    in the active or most-recent meeting + enrolls it."""
    display_name = str(args.get("display_name") or "").strip()
    if not display_name:
        return {"error": "missing display_name", "response_text": "Whose voice should I enroll?"}
    speaker_label = str(args.get("speaker_label") or "").strip()
    meeting_id = str(args.get("meeting_id") or "").strip()
    is_primary = bool(args.get("is_primary") or False)
    if not meeting_id:
        try:
            from app.services.reachy_companion_service import (
                get_reachy_companion_service,
            )
            meeting_id = (
                get_reachy_companion_service().get_policy().meeting_active_id or ""
            )
        except Exception:
            meeting_id = ""
    if not meeting_id:
        # Most recent meeting with segments.
        try:
            from sqlalchemy import select, func
            from app.infrastructure.database import get_session
            from app.db.models import MeetingTranscriptSegmentModel  # type: ignore

            async with get_session() as db:
                row = (
                    await db.execute(
                        select(MeetingTranscriptSegmentModel.meeting_id, func.max(MeetingTranscriptSegmentModel.id))
                        .group_by(MeetingTranscriptSegmentModel.meeting_id)
                        .order_by(func.max(MeetingTranscriptSegmentModel.id).desc())
                        .limit(1)
                    )
                ).first()
                if row:
                    meeting_id = row[0]
        except Exception as exc:
            logger.debug("enroll_voice_meeting_lookup_failed", error=str(exc))
    if not meeting_id:
        return {"error": "no meeting", "response_text": "I couldn't find a meeting to enroll from."}
    try:
        from sqlalchemy import select, func
        from app.infrastructure.database import get_session
        from app.db.models import (  # type: ignore
            MeetingTranscriptSegmentModel,
            MeetingRecordingModel,
        )
        from app.services.voiceprint_service import get_voiceprint_service
        from app.services.meeting_processing_pipeline import _resolve_audio_path

        async with get_session() as db:
            # Decide which speaker label to enroll.
            if not speaker_label:
                row = (
                    await db.execute(
                        select(
                            MeetingTranscriptSegmentModel.speaker,
                            func.count().label("n"),
                        )
                        .where(MeetingTranscriptSegmentModel.meeting_id == meeting_id)
                        .where(MeetingTranscriptSegmentModel.speaker.is_not(None))
                        .group_by(MeetingTranscriptSegmentModel.speaker)
                        .order_by(func.count().desc())
                        .limit(1)
                    )
                ).first()
                if not row:
                    return {"error": "no_speakers", "response_text": "That meeting has no diarized speakers."}
                speaker_label = str(row[0])
            segs = (
                await db.execute(
                    select(MeetingTranscriptSegmentModel)
                    .where(MeetingTranscriptSegmentModel.meeting_id == meeting_id)
                    .where(MeetingTranscriptSegmentModel.speaker == speaker_label)
                    .order_by(MeetingTranscriptSegmentModel.start_time.asc())
                )
            ).scalars().all()
            recording = (
                await db.execute(
                    select(MeetingRecordingModel)
                    .where(MeetingRecordingModel.meeting_id == meeting_id)
                    .order_by(MeetingRecordingModel.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
        if not segs:
            return {"error": "no_segments_for_speaker", "response_text": f"No segments for {speaker_label}."}
        if recording is None:
            return {"error": "no_recording", "response_text": "Couldn't locate the audio file."}
        audio_path = _resolve_audio_path(recording.file_path)
        speaker_segments = [
            {"start": float(s.start_time or 0.0), "end": float(s.end_time or 0.0), "speaker": speaker_label}
            for s in segs
        ]
        svc = get_voiceprint_service()
        centroid = svc.compute_cluster_centroid(audio_path, speaker_segments)
        if centroid is None:
            return {"error": "no_embedding", "response_text": "Couldn't compute a voiceprint for that speaker."}
        sample_seconds = sum(max(0.0, s["end"] - s["start"]) for s in speaker_segments)
        row, replaced = await svc.enroll(
            display_name=display_name,
            embedding=centroid,
            samples_seconds=sample_seconds,
            is_primary=is_primary,
            source_meeting_id=meeting_id,
        )
        action = "updated" if replaced else "enrolled"
        return {
            "ok": True,
            "voiceprint_id": getattr(row, "id", None),
            "display_name": display_name,
            "speaker_label": speaker_label,
            "meeting_id": meeting_id,
            "samples_seconds": round(sample_seconds, 1),
            "response_text": (
                f"Got it — {action} {display_name}'s voice from {round(sample_seconds, 1)}s of audio in that meeting."
            ),
        }
    except Exception as e:
        logger.warning("enroll_voice_from_meeting_failed", error=str(e))
        return {"error": str(e), "response_text": "Voice enrollment failed."}


async def _summarize_current_meeting(deps: ToolDependencies, args: Dict[str, Any], _mgr: BackgroundToolManager) -> Dict[str, Any]:
    """Voice: 'Hey Zero, summarise so far'. Reads companion's active
    meeting_id and routes through meeting_rag_query so the user gets a
    transcript-grounded recap without leaving the realtime turn."""
    try:
        from app.services.reachy_companion_service import (
            get_reachy_companion_service,
        )

        meeting_id = (
            get_reachy_companion_service().get_policy().meeting_active_id or ""
        )
    except Exception:
        meeting_id = ""
    if not meeting_id:
        return {
            "response_text": "I'm not capturing a meeting right now, so there's nothing to summarise yet.",
        }
    return await _meeting_rag_query(
        deps,
        {"question": "Summarise everything that has been discussed so far in this meeting.",
         "meeting_id": meeting_id},
        _mgr,
    )


async def _meeting_rag_query(deps: ToolDependencies, args: Dict[str, Any], _mgr: BackgroundToolManager) -> Dict[str, Any]:
    """Search past meetings (transcripts + summaries) and answer a question.
    Powers 'Hey Zero, what did Sarah say last week?' from inside an active
    realtime turn — does not go through the keyword classifier."""
    question = str(args.get("question") or "").strip()
    if not question:
        return {"error": "missing question", "response_text": "What did you want to know about the meeting?"}
    meeting_id = args.get("meeting_id")
    speaker_hint = args.get("speaker")
    topic_label = args.get("topic_label")
    # F-91: derive topic_label from the question text when not supplied
    # explicitly — questions like "what did we say about budget" usually
    # imply a topical filter on the noun phrase after "about".
    if not topic_label:
        ql = question.lower()
        for trigger in (" about ", " regarding ", " on the topic of "):
            if trigger in ql:
                topic_label = question[ql.index(trigger) + len(trigger):].strip(" .?!,")[:60]
                break
    try:
        from app.services.meeting_rag_service import get_meeting_rag_service
        from app.infrastructure.database import get_session

        svc = get_meeting_rag_service()
        async with get_session() as db:
            result = await svc.query(
                question=question,
                db=db,
                meeting_id=meeting_id,
                top_k=6,
                topic_label=topic_label,
            )
        answer = (result.get("answer") or "").strip()
        sources = result.get("sources") or []
        if speaker_hint:
            sources = [
                s for s in sources
                if speaker_hint.lower() in str(s.get("speaker") or "").lower()
            ]
        if not answer:
            answer = (
                "I searched the meeting archive but couldn't find anything matching that."
                if not sources
                else "I found some context but can't summarise it just yet."
            )
        return {
            "response_text": answer,
            "sources": [
                {
                    "meeting_id": s.get("meeting_id"),
                    "meeting_title": s.get("meeting_title"),
                    "speaker": s.get("speaker"),
                    "timestamp": s.get("timestamp"),
                }
                for s in sources[:5]
            ],
        }
    except Exception as e:
        logger.warning("meeting_rag_query_tool_failed", error=str(e))
        return {"error": str(e), "response_text": "I couldn't reach the meeting archive."}


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
    "meeting_rag_query": _meeting_rag_query,
    "mark_meeting_private": _mark_meeting_private,
    "summarize_current_meeting": _summarize_current_meeting,
    "enroll_face_from_meeting": _enroll_face_from_meeting,
    "enroll_voice_from_meeting": _enroll_voice_from_meeting,
    "regenerate_summary": _regenerate_summary,
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
