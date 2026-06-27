"""Business-asset register service.

CRUD over the `business_assets` table + a current-year deduction estimate per
asset based on its method. Mirrors the company_facts service pattern (DB-backed,
async session per call, lru_cache singleton).

Deduction math (estimates only — the CPA elects the actual method at filing,
IRS Pub 946):

* ``section_179``  → full cost x business-use % expensed in the placed-in-service
  year. (Real §179 is capped at business taxable income; we annotate that, we
  don't model it.)
* ``de_minimis``   → full cost x business-use % (de minimis safe harbor, items
  typically < $2,500 each).
* ``macrs_5yr``    → 5-year MACRS, half-year convention → 20% of the depreciable
  basis in year one (a deliberate first-year approximation).
* ``none``         → 0 (tracked for the register / FMV only, not expensed).

Only assets placed in service in the requested year (and not disposed before it)
contribute to that year's deduction.
"""

from __future__ import annotations

import uuid
from functools import lru_cache
from typing import Optional

from sqlalchemy import select

from app.db.models import BusinessAssetModel
from app.infrastructure.database import get_session
from app.models.business_asset import BusinessAsset, BusinessAssetCreate, BusinessAssetUpdate

# First-year MACRS 5-year, half-year convention.
_MACRS_5YR_Y1 = 0.20


def current_year_deduction(asset: BusinessAssetModel, *, year: int) -> float:
    """Estimated deduction this asset contributes for `year` (see module docstring)."""
    if asset.placed_in_service is None or asset.placed_in_service.year != year:
        return 0.0
    if asset.disposed_at is not None and asset.disposed_at.year < year:
        return 0.0
    basis = max(0.0, float(asset.cost or 0.0)) * max(0.0, min(100.0, float(asset.business_use_pct or 0.0))) / 100.0
    method = (asset.method or "section_179").lower()
    if method in ("section_179", "de_minimis"):
        return round(basis, 2)
    if method == "macrs_5yr":
        return round(basis * _MACRS_5YR_Y1, 2)
    return 0.0


def _to_schema(row: BusinessAssetModel, *, year: int) -> BusinessAsset:
    asset = BusinessAsset.model_validate(row, from_attributes=True)
    asset.current_year_deduction = current_year_deduction(row, year=year)
    return asset


class AssetService:
    """CRUD over the business_assets register."""

    async def list_assets(self, *, year: int) -> list[BusinessAsset]:
        async with get_session() as session:
            rows = (
                await session.execute(
                    select(BusinessAssetModel).order_by(
                        BusinessAssetModel.placed_in_service.desc().nullslast(),
                        BusinessAssetModel.name,
                    )
                )
            ).scalars().all()
        return [_to_schema(row, year=year) for row in rows]

    async def get_asset(self, asset_id: str, *, year: int) -> Optional[BusinessAsset]:
        async with get_session() as session:
            row = (
                await session.execute(
                    select(BusinessAssetModel).where(BusinessAssetModel.id == asset_id).limit(1)
                )
            ).scalars().first()
        return _to_schema(row, year=year) if row else None

    async def create_asset(self, data: BusinessAssetCreate, *, year: int, created_by: str = "user") -> BusinessAsset:
        async with get_session() as session:
            row = BusinessAssetModel(
                id=f"asset-{uuid.uuid4().hex[:12]}",
                name=data.name.strip()[:200],
                asset_type=(data.asset_type or None),
                cost=abs(float(data.cost or 0.0)),
                business_use_pct=max(0.0, min(100.0, float(data.business_use_pct or 0.0))),
                placed_in_service=data.placed_in_service,
                method=data.method,
                evidence_url=data.evidence_url,
                notes=data.notes,
                created_by=created_by,
            )
            session.add(row)
            await session.flush()
            asset = _to_schema(row, year=year)
        return asset

    async def update_asset(self, asset_id: str, updates: BusinessAssetUpdate, *, year: int) -> Optional[BusinessAsset]:
        async with get_session() as session:
            row = (
                await session.execute(
                    select(BusinessAssetModel).where(BusinessAssetModel.id == asset_id).limit(1)
                )
            ).scalars().first()
            if not row:
                return None
            data = updates.model_dump(exclude_unset=True)
            for field, value in data.items():
                setattr(row, field, value)
            await session.flush()
            asset = _to_schema(row, year=year)
        return asset

    async def delete_asset(self, asset_id: str) -> bool:
        async with get_session() as session:
            row = (
                await session.execute(
                    select(BusinessAssetModel).where(BusinessAssetModel.id == asset_id).limit(1)
                )
            ).scalars().first()
            if not row:
                return False
            await session.delete(row)
        return True

    async def total_current_year_deduction(self, *, year: int) -> float:
        assets = await self.list_assets(year=year)
        return round(sum(a.current_year_deduction or 0.0 for a in assets), 2)


@lru_cache(maxsize=1)
def get_asset_service() -> AssetService:
    return AssetService()
