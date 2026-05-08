"""Pydantic models for the Reachy custom motion sequence API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class SequenceStep(BaseModel):
    clip: str = Field(..., min_length=1, max_length=128)
    kind: Optional[Literal["emotion", "dance"]] = None
    gap_ms: int = Field(default=0, ge=0, le=10_000)


class SequenceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    description: Optional[str] = Field(default=None, max_length=1_000)
    steps: list[SequenceStep] = Field(..., min_length=1, max_length=64)
    aliases: list[str] = Field(default_factory=list, max_length=16)

    @field_validator("aliases")
    @classmethod
    def strip_aliases(cls, v: list[str]) -> list[str]:
        return [a.strip() for a in v if a and a.strip()]


class SequenceUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    description: Optional[str] = Field(default=None, max_length=1_000)
    steps: Optional[list[SequenceStep]] = Field(default=None, min_length=1, max_length=64)
    aliases: Optional[list[str]] = Field(default=None, max_length=16)

    @field_validator("aliases")
    @classmethod
    def strip_aliases(cls, v: Optional[list[str]]) -> Optional[list[str]]:
        if v is None:
            return None
        return [a.strip() for a in v if a and a.strip()]


class SequenceRead(BaseModel):
    id: int
    name: str
    description: Optional[str]
    steps: list[dict[str, Any]]
    aliases: list[str]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]


class SequencePlayResult(BaseModel):
    sequence_id: Optional[int]
    name: Optional[str]
    steps_played: int
    results: list[dict[str, Any]]
    is_sequence: bool = True
