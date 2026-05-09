"""Pydantic models for the Reachy companion experience."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


CompanionMode = Literal["ambient", "focus", "meeting", "privacy", "sleep"]
CompanionEventType = Literal[
    "voice_heard",
    "person_seen",
    "object_seen",
    "phone_seen",
    "meeting_started",
    "email_arrived",
    "ha_state_changed",
    "idle_elapsed",
    "skill_triggered",
    "mode_changed",
    "policy_changed",
    "privacy_alert",
    "notice",
]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class CompanionEventCreate(BaseModel):
    type: CompanionEventType
    source: str = Field("zero", min_length=1, max_length=80)
    summary: str = Field(..., min_length=1, max_length=240)
    payload: dict[str, Any] = Field(default_factory=dict)
    importance: float = Field(0.4, ge=0.0, le=1.0)


class CompanionEvent(CompanionEventCreate):
    id: str = Field(default_factory=lambda: uuid4().hex)
    created_at: datetime = Field(default_factory=utc_now)
    mode: CompanionMode = "ambient"
    persona_id: Optional[str] = None


class CompanionPolicy(BaseModel):
    mode: CompanionMode = "ambient"
    mic_enabled: bool = True
    camera_enabled: bool = True
    body_motion_enabled: bool = True
    proactive_enabled: bool = True
    cloud_realtime_allowed: bool = False
    memory_write_allowed: bool = True
    deterministic_alerts_enabled: bool = True
    max_proactive_events_per_hour: int = Field(4, ge=0, le=24)
    allowed_actions: list[str] = Field(default_factory=list)
    per_persona_tool_grants: dict[str, list[str]] = Field(default_factory=dict)
    quiet_hours_start: int = Field(22, ge=0, le=23)
    quiet_hours_end: int = Field(7, ge=0, le=23)
    updated_at: datetime = Field(default_factory=utc_now)


class CompanionPolicyPatch(BaseModel):
    mic_enabled: Optional[bool] = None
    camera_enabled: Optional[bool] = None
    body_motion_enabled: Optional[bool] = None
    proactive_enabled: Optional[bool] = None
    cloud_realtime_allowed: Optional[bool] = None
    memory_write_allowed: Optional[bool] = None
    deterministic_alerts_enabled: Optional[bool] = None
    max_proactive_events_per_hour: Optional[int] = Field(None, ge=0, le=24)
    allowed_actions: Optional[list[str]] = None
    per_persona_tool_grants: Optional[dict[str, list[str]]] = None
    quiet_hours_start: Optional[int] = Field(None, ge=0, le=23)
    quiet_hours_end: Optional[int] = Field(None, ge=0, le=23)


class CompanionModeRequest(BaseModel):
    mode: CompanionMode
    reason: str = Field("user", min_length=1, max_length=120)
    apply_actions: bool = True


class CompanionSkill(BaseModel):
    id: str
    title: str
    description: str
    mode_bias: CompanionMode
    required_events: list[CompanionEventType] = Field(default_factory=list)
    allowed_actions: list[str] = Field(default_factory=list)
    enabled: bool = True
    blocked_reason: Optional[str] = None


class CompanionSkillTriggerResponse(BaseModel):
    ok: bool
    skill_id: str
    mode: CompanionMode
    actions: list[dict[str, Any]] = Field(default_factory=list)
    event: CompanionEvent

