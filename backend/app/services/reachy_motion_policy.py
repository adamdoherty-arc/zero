"""Fail-closed policy gate for every Reachy body-motion surface."""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger()


def body_motion_allowed(*, surface: str = "unknown") -> dict[str, Any]:
    """Return whether body/head/antenna/emotion/dance motion may be sent.

    This intentionally gates outside the companion console too. The robot can
    still speak, listen, and use camera/context while physical motion is locked.
    """
    try:
        from app.services.reachy_companion_service import get_reachy_companion_service

        result = get_reachy_companion_service().action_allowed("body_motion")
        allowed = bool(result.get("allowed"))
        return {
            "allowed": allowed,
            "surface": surface,
            "reason": result.get("reason") or ("allowed" if allowed else "body_motion_locked"),
        }
    except Exception as exc:
        logger.warning("reachy_motion_policy_unavailable", surface=surface, error=str(exc))
        return {
            "allowed": False,
            "surface": surface,
            "reason": "policy_unavailable",
            "error": str(exc),
        }


def body_motion_locked_payload(*, surface: str = "unknown") -> dict[str, Any]:
    policy = body_motion_allowed(surface=surface)
    return {
        "error": "body_motion_locked",
        "surface": surface,
        "reason": policy.get("reason"),
        "detail": (
            "Reachy body motion is locked off. Voice, camera, memory, and "
            "companion policy remain active; set ZERO_REACHY_COMPANION_BODY_MOTION=true "
            "and explicitly enable body motion before sending physical movement."
        ),
    }
