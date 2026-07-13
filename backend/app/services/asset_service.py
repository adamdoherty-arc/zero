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
from datetime import date, datetime, timezone
from functools import lru_cache
from typing import Optional

import structlog
from sqlalchemy import select

from app.db.models import BusinessAssetModel
from app.infrastructure.database import get_session
from app.models.business_asset import (
    AssetTransferItem,
    BusinessAsset,
    BusinessAssetCreate,
    BusinessAssetUpdate,
)

logger = structlog.get_logger(__name__)

# First-year MACRS 5-year, half-year convention.
_MACRS_5YR_Y1 = 0.20
# De minimis safe harbor ceiling (per item, no AFS) — IRS Reg. 1.263(a)-1(f).
DE_MINIMIS_CEILING = 2500.0


def deduction_basis(asset: BusinessAssetModel) -> float:
    """Depreciable basis before the business-use % haircut.

    Purchased property → cost. Contributed personal property → the LESSER of
    FMV at contribution or the owner's original cost (IRS Pub 551 converted-
    property rule); falls back to whichever of the two is present, then cost.
    """
    if (asset.acquisition_type or "purchased") == "contributed":
        candidates = [
            v for v in (asset.fmv_at_contribution, asset.original_cost) if v is not None
        ]
        if candidates:
            return max(0.0, float(min(candidates)))
    return max(0.0, float(asset.cost or 0.0))


def current_year_deduction(asset: BusinessAssetModel, *, year: int) -> float:
    """Estimated deduction this asset contributes for `year` (see module docstring)."""
    if asset.placed_in_service is None or asset.placed_in_service.year != year:
        return 0.0
    if asset.disposed_at is not None and asset.disposed_at.year < year:
        return 0.0
    basis = deduction_basis(asset) * max(0.0, min(100.0, float(asset.business_use_pct or 0.0))) / 100.0
    method = (asset.method or "section_179").lower()
    # bonus = 100% bonus depreciation (OBBBA, property placed in service after
    # 2025-01-19) — same year-one math as §179 but a distinct election the CPA
    # package must label separately.
    if method in ("section_179", "bonus", "de_minimis"):
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
        cost = abs(float(data.cost or 0.0))
        if data.acquisition_type == "contributed" and not cost and data.fmv_at_contribution:
            # Display consistency: contributed rows show FMV as the headline cost.
            cost = abs(float(data.fmv_at_contribution))
        async with get_session() as session:
            row = BusinessAssetModel(
                id=f"asset-{uuid.uuid4().hex[:12]}",
                name=data.name.strip()[:200],
                asset_type=(data.asset_type or None),
                cost=cost,
                business_use_pct=max(0.0, min(100.0, float(data.business_use_pct or 0.0))),
                placed_in_service=data.placed_in_service,
                method=data.method,
                acquisition_type=data.acquisition_type,
                fmv_at_contribution=data.fmv_at_contribution,
                original_cost=data.original_cost,
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

    async def record_contribution_batch(
        self,
        items: list[AssetTransferItem],
        *,
        memo_url: Optional[str] = None,
        actor: str = "user",
    ) -> list[BusinessAsset]:
        """Register personal property entering the LLC as a capital contribution.

        Idempotent two ways: an item matching an existing contributed row (same
        normalized name + placed-in-service date) reuses that row instead of
        duplicating it, and the Equity:Owner:Contributions journal entry is
        posted at most once per row (contribution_posted_at marker). Facts
        `asset_transfer_*` are refreshed so the ASSET_TRANSFER_WALKTHROUGH sees
        the register as its system of record.
        """
        from app.services.bookkeeper_service import get_bookkeeper_service

        year = date.today().year
        results: list[BusinessAsset] = []
        rows_to_post: list[BusinessAssetModel] = []
        async with get_session() as session:
            existing_rows = (
                await session.execute(
                    select(BusinessAssetModel).where(
                        BusinessAssetModel.acquisition_type == "contributed"
                    )
                )
            ).scalars().all()
            by_key = {
                (r.name.strip().lower(), r.placed_in_service): r for r in existing_rows
            }
            for item in items:
                key = (item.name.strip().lower(), item.placed_in_service)
                row = by_key.get(key)
                if row is None:
                    basis_candidates = [v for v in (item.fmv, item.original_cost) if v is not None]
                    basis = min(basis_candidates) if basis_candidates else item.fmv
                    method = item.method or (
                        "de_minimis" if basis < DE_MINIMIS_CEILING else "section_179"
                    )
                    row = BusinessAssetModel(
                        id=f"asset-{uuid.uuid4().hex[:12]}",
                        name=item.name.strip()[:200],
                        asset_type=(item.asset_type or None),
                        cost=abs(float(item.fmv)),
                        business_use_pct=max(0.0, min(100.0, float(item.business_use_pct))),
                        placed_in_service=item.placed_in_service,
                        method=method,
                        acquisition_type="contributed",
                        fmv_at_contribution=abs(float(item.fmv)),
                        original_cost=item.original_cost,
                        evidence_url=memo_url,
                        notes=item.notes,
                        created_by=actor,
                    )
                    session.add(row)
                    by_key[key] = row
                if row.contribution_posted_at is None:
                    rows_to_post.append(row)
            await session.flush()
            # Serialize inside the session so lazy attrs are loaded.
            pending_ids = {r.id for r in rows_to_post}
            results = [_to_schema(by_key[(i.name.strip().lower(), i.placed_in_service)], year=year) for i in items]

        # Journal entries + idempotence stamps happen outside the row-creating
        # transaction so a ledger-write failure never rolls back the register.
        bookkeeper = get_bookkeeper_service()
        posted_at = datetime.now(timezone.utc)
        for asset in results:
            if asset.id not in pending_ids:
                continue
            await bookkeeper.post_owner_contribution(
                date_str=(asset.placed_in_service or date.today()).isoformat(),
                description=f"Owner capital contribution — {asset.name}",
                amount=float(asset.fmv_at_contribution or asset.cost or 0.0),
            )
            async with get_session() as session:
                row = (
                    await session.execute(
                        select(BusinessAssetModel).where(BusinessAssetModel.id == asset.id).limit(1)
                    )
                ).scalars().first()
                if row:
                    row.contribution_posted_at = posted_at
            asset.contribution_posted_at = posted_at

        await self._refresh_transfer_facts(actor=actor)
        return results

    async def _refresh_transfer_facts(self, *, actor: str) -> None:
        """Mirror register totals into the asset_transfer_* company facts."""
        try:
            from app.models.company_facts import CompanyFactCreate
            from app.services.company_facts_service import get_company_facts_service

            async with get_session() as session:
                rows = (
                    await session.execute(
                        select(BusinessAssetModel).where(
                            BusinessAssetModel.acquisition_type == "contributed"
                        )
                    )
                ).scalars().all()
            if not rows:
                return
            total_fmv = round(sum(float(r.fmv_at_contribution or r.cost or 0.0) for r in rows), 2)
            latest = max((r.placed_in_service for r in rows if r.placed_in_service), default=None)
            facts_service = get_company_facts_service()
            for key, label, value in (
                ("asset_transfer_total_fmv", "Asset transfer — total FMV", f"${total_fmv:,.2f}"),
                ("asset_transfer_structure", "Asset transfer — structure", "capital_contribution"),
                (
                    "asset_transfer_placed_in_service_on",
                    "Asset transfer — placed in service",
                    latest.isoformat() if latest else "",
                ),
            ):
                if value == "":
                    continue
                await facts_service.upsert_fact(
                    CompanyFactCreate(key=key, label=label, value=value, domain="finance"),
                    created_by=actor,
                    source="asset_transfer",
                )
        except Exception as e:  # facts mirror must never fail the transfer
            logger.warning("asset_transfer_facts_refresh_failed", error=str(e))


@lru_cache(maxsize=1)
def get_asset_service() -> AssetService:
    return AssetService()
