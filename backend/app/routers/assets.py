"""Business-asset register API.

Read/write surface over the `business_assets` register (hardware / equipment /
Section 179). Each asset carries a derived `current_year_deduction` estimate for
the consolidated tax-savings summary. Replaces the old static Finance-tab assets
array. Nothing here is tax advice.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.infrastructure.auth import require_auth
from app.models.business_asset import (
    AssetTransferRequest,
    BusinessAsset,
    BusinessAssetCreate,
    BusinessAssetUpdate,
)
from app.services.asset_service import get_asset_service


router = APIRouter(
    prefix="/api/company/assets",
    tags=["company-assets"],
    dependencies=[Depends(require_auth)],
)


class BusinessAssetCreateRequest(BusinessAssetCreate):
    actor: str = Field(default="user", max_length=100)


def _default_year() -> int:
    return date.today().year


@router.get("", response_model=list[BusinessAsset])
async def list_assets(year: int = Query(default_factory=_default_year, ge=2000, le=2100)):
    return await get_asset_service().list_assets(year=year)


@router.post("", response_model=BusinessAsset)
async def create_asset(req: BusinessAssetCreateRequest, year: int = Query(default_factory=_default_year, ge=2000, le=2100)):
    payload = BusinessAssetCreate(**req.model_dump(exclude={"actor"}))
    return await get_asset_service().create_asset(payload, year=year, created_by=req.actor)


@router.post("/transfer", response_model=list[BusinessAsset])
async def transfer_assets(req: AssetTransferRequest):
    """Register personal property entering the LLC as a capital contribution.

    Idempotent: re-posting the same items (same name + placed-in-service date)
    neither duplicates register rows nor re-posts the owner-equity journal entry.
    """
    return await get_asset_service().record_contribution_batch(
        req.assets, memo_url=req.memo_url, actor=req.actor
    )


@router.patch("/{asset_id}", response_model=BusinessAsset)
async def update_asset(
    asset_id: str,
    updates: BusinessAssetUpdate,
    year: int = Query(default_factory=_default_year, ge=2000, le=2100),
):
    asset = await get_asset_service().update_asset(asset_id, updates, year=year)
    if not asset:
        raise HTTPException(404, f"Business asset {asset_id} not found")
    return asset


@router.delete("/{asset_id}")
async def delete_asset(asset_id: str):
    ok = await get_asset_service().delete_asset(asset_id)
    if not ok:
        raise HTTPException(404, f"Business asset {asset_id} not found")
    return {"status": "deleted", "id": asset_id}
