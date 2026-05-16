"""Pydantic schemas for the company_facts KV registry.

Each `CompanyFact` is a structured artifact captured when Adam completes a
company work item (or recorded manually). The registry is the canonical
"company definition" surface: queryable by key, grouped by domain, mirrored
into `docs/company/company-facts.md` so it flows through the existing docs
index and MCP retrieval tools.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class CompletionOutput(BaseModel):
    """One structured output captured at task completion."""

    key: str = Field(..., min_length=1, max_length=160)
    label: str = Field(..., min_length=1, max_length=300)
    value: str = Field(..., min_length=1)
    domain: Optional[str] = Field(default=None, max_length=80)
    evidence_url: Optional[str] = None
    sensitive: bool = False
    notes: Optional[str] = None


class CompanyFact(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    key: str
    label: str
    value: str
    domain: Optional[str] = None
    source_task_id: Optional[str] = None
    source: str = "task_completion"
    evidence_url: Optional[str] = None
    sensitive: bool = False
    notes: Optional[str] = None
    created_by: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class CompanyFactCreate(BaseModel):
    key: str = Field(..., min_length=1, max_length=160)
    label: str = Field(..., min_length=1, max_length=300)
    value: str = Field(..., min_length=1)
    domain: Optional[str] = Field(default=None, max_length=80)
    evidence_url: Optional[str] = None
    sensitive: bool = False
    notes: Optional[str] = None


class CompanyFactUpdate(BaseModel):
    label: Optional[str] = Field(default=None, max_length=300)
    value: Optional[str] = None
    domain: Optional[str] = Field(default=None, max_length=80)
    evidence_url: Optional[str] = None
    sensitive: Optional[bool] = None
    notes: Optional[str] = None
