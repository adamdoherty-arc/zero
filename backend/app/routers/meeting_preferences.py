"""User-tunable meeting preferences.

Runtime-mutable settings live in ``workspace/meetings/preferences.json``
because the env-backed ``Settings`` object is read once at startup. Lets
the user flip auto-record-all and auto-create-tasks-from-meetings without
restarting zero-api.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import structlog
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()
logger = structlog.get_logger(__name__)

_PREFS_PATH = Path("/app/workspace/meetings/preferences.json")
_DEFAULTS: dict = {
    "auto_record_all": False,
    "auto_create_tasks_from_meetings": False,
}


class MeetingPreferences(BaseModel):
    auto_record_all: bool = False
    auto_create_tasks_from_meetings: bool = False


class MeetingPreferencesUpdate(BaseModel):
    auto_record_all: Optional[bool] = None
    auto_create_tasks_from_meetings: Optional[bool] = None


def _read_prefs() -> dict:
    try:
        if _PREFS_PATH.exists():
            data = json.loads(_PREFS_PATH.read_text(encoding="utf-8"))
            return {**_DEFAULTS, **(data if isinstance(data, dict) else {})}
    except Exception as exc:  # noqa: BLE001
        logger.warning("read_meeting_prefs_failed", error=str(exc))
    return dict(_DEFAULTS)


def _write_prefs(prefs: dict) -> None:
    _PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _PREFS_PATH.write_text(json.dumps(prefs, indent=2), encoding="utf-8")


def get_meeting_prefs() -> dict:
    """Module-level helper used by the scheduler & pipeline."""
    return _read_prefs()


@router.get("", response_model=MeetingPreferences)
async def get_preferences():
    return MeetingPreferences(**_read_prefs())


@router.patch("", response_model=MeetingPreferences)
async def update_preferences(update: MeetingPreferencesUpdate):
    current = _read_prefs()
    payload = update.model_dump(exclude_unset=True)
    current.update(payload)
    _write_prefs(current)
    logger.info("meeting_prefs_updated", **payload)
    return MeetingPreferences(**current)
