"""Pydantic schemas for the business_assets register.

A `BusinessAsset` is a piece of equipment in service for ADA AI LLC. The asset
service derives `current_year_deduction` from cost x business-use % and the
chosen method (§179 full expensing, de minimis, MACRS 5-yr, or none). Nothing
here is tax advice — the CPA elects the method at filing (IRS Pub 946).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


AssetMethod = Literal["section_179", "bonus", "de_minimis", "macrs_5yr", "none"]
AcquisitionType = Literal["purchased", "contributed"]


class BusinessAsset(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    asset_type: Optional[str] = None
    cost: float = 0.0
    business_use_pct: float = 100.0
    placed_in_service: Optional[date] = None
    method: AssetMethod = "section_179"
    acquisition_type: AcquisitionType = "purchased"
    fmv_at_contribution: Optional[float] = None
    original_cost: Optional[float] = None
    contribution_posted_at: Optional[datetime] = None
    disposed_at: Optional[date] = None
    evidence_url: Optional[str] = None
    notes: Optional[str] = None
    created_by: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    # Derived (populated by the service, not stored):
    current_year_deduction: Optional[float] = None


class BusinessAssetCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    asset_type: Optional[str] = Field(default=None, max_length=80)
    cost: float = Field(default=0.0, ge=0)
    business_use_pct: float = Field(default=100.0, ge=0, le=100)
    placed_in_service: Optional[date] = None
    method: AssetMethod = "section_179"
    acquisition_type: AcquisitionType = "purchased"
    fmv_at_contribution: Optional[float] = Field(default=None, ge=0)
    original_cost: Optional[float] = Field(default=None, ge=0)
    evidence_url: Optional[str] = None
    notes: Optional[str] = None


class BusinessAssetUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    asset_type: Optional[str] = Field(default=None, max_length=80)
    cost: Optional[float] = Field(default=None, ge=0)
    business_use_pct: Optional[float] = Field(default=None, ge=0, le=100)
    placed_in_service: Optional[date] = None
    method: Optional[AssetMethod] = None
    acquisition_type: Optional[AcquisitionType] = None
    fmv_at_contribution: Optional[float] = Field(default=None, ge=0)
    original_cost: Optional[float] = Field(default=None, ge=0)
    disposed_at: Optional[date] = None
    evidence_url: Optional[str] = None
    notes: Optional[str] = None


class AssetTransferItem(BaseModel):
    """One piece of personal property entering the LLC as a capital contribution."""

    name: str = Field(..., min_length=1, max_length=200)
    asset_type: Optional[str] = Field(default=None, max_length=80)
    fmv: float = Field(..., gt=0, description="Fair market value on the transfer date")
    original_cost: Optional[float] = Field(default=None, ge=0)
    business_use_pct: float = Field(default=100.0, ge=0, le=100)
    placed_in_service: date
    method: Optional[AssetMethod] = None  # default derived from basis (< $2,500 → de_minimis)
    notes: Optional[str] = None


class AssetTransferRequest(BaseModel):
    assets: list[AssetTransferItem] = Field(..., min_length=1)
    memo_url: Optional[str] = None
    actor: str = Field(default="user", max_length=100)
