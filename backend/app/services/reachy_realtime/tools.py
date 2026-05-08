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
from typing import Any, Awaitable, Callable, Dict, Optional

import structlog

from app.services.reachy_realtime.bg_tool_manager import BackgroundToolManager, ToolState
from app.services.reachy_realtime.common import ToolDependencies

logger = structlog.get_logger()


ToolHandler = Callable[[ToolDependencies, Dict[str, Any], BackgroundToolManager], Awaitable[Dict[str, Any]]]


# ----------------------- individual tool bodies -----------------------

async def _move_head(deps: ToolDependencies, args: Dict[str, Any], _mgr: BackgroundToolManager) -> Dict[str, Any]:
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
    move = args.get("move") or "random"
    repeat = int(args.get("repeat") or 1)
    if deps.motion.play_dance is None:
        return {"error": "dance unavailable"}
    if move == "random":
        # Let reachy_service's resolver pick a dance — it accepts 'random' as a free tag.
        move = "dance"
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
    if deps.motion.play_emotion is None:
        return {"error": "emotions unavailable"}
    res = await deps.motion.play_emotion(str(emotion))
    if res.get("error"):
        return {"error": res["error"], "emotion": emotion}
    return {"status": "queued", "emotion": emotion}


async def _stop_dance(deps: ToolDependencies, _args: Dict[str, Any], _mgr: BackgroundToolManager) -> Dict[str, Any]:
    if deps.motion.stop_move is not None:
        await deps.motion.stop_move()
    return {"status": "stopped dance"}


async def _stop_emotion(deps: ToolDependencies, _args: Dict[str, Any], _mgr: BackgroundToolManager) -> Dict[str, Any]:
    if deps.motion.stop_move is not None:
        await deps.motion.stop_move()
    return {"status": "stopped emotion"}


async def _head_tracking(deps: ToolDependencies, args: Dict[str, Any], _mgr: BackgroundToolManager) -> Dict[str, Any]:
    enable = bool(args.get("start"))
    if deps.motion.set_head_tracking is not None:
        await deps.motion.set_head_tracking(enable)
    status = "started" if enable else "stopped"
    return {"status": f"head tracking {status}"}


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
        return {"error": "no frame available"}
    return {"b64_im": base64.b64encode(jpeg).decode("ascii")}


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
        "description": "Toggle head-tracking state (the robot will follow a detected face).",
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
