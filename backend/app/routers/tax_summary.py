"""Consolidated tax-savings summary API.

`GET /api/company/tax-summary?year=YYYY` rolls every deductible category into one
YTD picture + an estimate of personal tax saved (income + self-employment). The
heavy lifting lives in `tax_summary_service`. Nothing here is tax advice.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query, Response

from app.infrastructure.auth import require_auth
from app.services.tax_summary_service import get_tax_summary_service


router = APIRouter(
    prefix="/api/company/tax-summary",
    tags=["company-tax-summary"],
    dependencies=[Depends(require_auth)],
)


def _default_year() -> int:
    return date.today().year


@router.get("")
async def tax_summary(year: int = Query(default_factory=_default_year, ge=2000, le=2100)):
    return await get_tax_summary_service().summary(year=year)


@router.get("/export")
async def tax_package_export(
    year: int = Query(default_factory=_default_year, ge=2000, le=2100),
    format: str = Query(default="md", pattern="^(md|csv)$"),
):
    """Download the CPA tax package (Schedule C rollup, assets, worksheets)."""
    content, media_type, filename = await get_tax_summary_service().tax_package(year=year, fmt=format)
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
