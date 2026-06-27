"""Unit tests for the business-asset deduction math (no DB required)."""

from __future__ import annotations

from datetime import date

from app.db.models import BusinessAssetModel
from app.services.asset_service import current_year_deduction


def _asset(**kw) -> BusinessAssetModel:
    defaults = dict(
        id="asset-test",
        name="Workstation",
        cost=1000.0,
        business_use_pct=100.0,
        placed_in_service=date(2026, 3, 1),
        method="section_179",
        disposed_at=None,
    )
    defaults.update(kw)
    return BusinessAssetModel(**defaults)


def test_section_179_full_business_share():
    a = _asset(cost=2000.0, business_use_pct=80.0, method="section_179")
    assert current_year_deduction(a, year=2026) == 1600.0


def test_de_minimis_full_business_share():
    a = _asset(cost=500.0, business_use_pct=100.0, method="de_minimis")
    assert current_year_deduction(a, year=2026) == 500.0


def test_macrs_5yr_first_year_is_20_percent():
    a = _asset(cost=1000.0, business_use_pct=100.0, method="macrs_5yr")
    assert current_year_deduction(a, year=2026) == 200.0


def test_method_none_is_zero():
    a = _asset(cost=1000.0, method="none")
    assert current_year_deduction(a, year=2026) == 0.0


def test_wrong_year_is_zero():
    a = _asset(cost=1000.0, placed_in_service=date(2025, 6, 1), method="section_179")
    assert current_year_deduction(a, year=2026) == 0.0


def test_unplaced_asset_is_zero():
    a = _asset(placed_in_service=None)
    assert current_year_deduction(a, year=2026) == 0.0


def test_business_pct_clamped_to_100():
    a = _asset(cost=1000.0, business_use_pct=150.0, method="section_179")
    # over-100% typo clamps so the deduction can't exceed cost
    assert current_year_deduction(a, year=2026) == 1000.0


def test_negative_pct_clamped_to_zero():
    a = _asset(cost=1000.0, business_use_pct=-20.0, method="section_179")
    assert current_year_deduction(a, year=2026) == 0.0
