"""Unit tests for CompanyFactsService deduction math + masking (no DB).

`get_session` is faked so the pure worksheet math (home-office simplified vs
actual, cell-phone + vehicle mileage) is exercised deterministically. This math
feeds the user's tax-savings numbers, so a regression here is high-impact.
"""

from __future__ import annotations

from types import SimpleNamespace

import app.services.company_facts_service as cfs


# --------------------------------------------------------------------------- #
# Fake async session that returns a fixed list of CompanyFactModel-like rows.
# The summary methods only read row.key / row.value.
# --------------------------------------------------------------------------- #
class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


class _FakeSession:
    def __init__(self, rows):
        self._rows = rows

    async def execute(self, _stmt):
        return _FakeResult(self._rows)


class _FakeSessionCtx:
    def __init__(self, rows):
        self._rows = rows

    async def __aenter__(self):
        return _FakeSession(self._rows)

    async def __aexit__(self, *_exc):
        return False


def _facts(mapping: dict[str, str]):
    """Build fact rows from a {key: value} mapping."""
    return [SimpleNamespace(key=k, value=v) for k, v in mapping.items()]


def _patch_session(monkeypatch, mapping: dict[str, str]):
    rows = _facts(mapping)
    monkeypatch.setattr(cfs, "get_session", lambda: _FakeSessionCtx(rows))


# --------------------------------------------------------------------------- #
# _mask (pure)
# --------------------------------------------------------------------------- #
def test_mask_non_sensitive_passthrough():
    assert cfs._mask("123456789", sensitive=False) == "123456789"


def test_mask_sensitive_reveals_last_four():
    assert cfs._mask("123456789", sensitive=True) == "*****6789"


def test_mask_sensitive_short_value_fully_masked():
    assert cfs._mask("12", sensitive=True) == "****"


def test_mask_empty_value_untouched():
    assert cfs._mask("", sensitive=True) == ""


# --------------------------------------------------------------------------- #
# home_office_summary
# --------------------------------------------------------------------------- #
async def test_home_office_simplified_and_actual(monkeypatch):
    _patch_session(
        monkeypatch,
        {
            "home_office.exclusive_sqft": "200",
            "home_office.total_sqft": "1000",
            "home_office.rent_or_mortgage_monthly": "2000",
            "home_office.utilities_monthly": "100",
            "home_office.internet_monthly": "80",
            "home_office.internet_business_pct": "50",
            "home_office.method": "simplified",
        },
    )
    out = await cfs.CompanyFactsService().home_office_summary()

    assert out["method"] == "simplified"
    # 200/1000 = 20%
    assert out["business_use_pct"] == 20.0
    # min(200, 300) * 5
    assert out["simplified_estimate"] == 1000.0
    # ((2000+100)*12) * 0.20  + 80*12*0.50
    assert out["actual_estimate_annual"] == 5520.0
    assert out["missing_fields"] == []
    assert out["facts_count"] == 7


async def test_home_office_simplified_caps_at_300_sqft(monkeypatch):
    _patch_session(monkeypatch, {"home_office.exclusive_sqft": "400"})
    out = await cfs.CompanyFactsService().home_office_summary()
    # capped: min(400, 300) * 5
    assert out["simplified_estimate"] == 1500.0


async def test_home_office_explicit_pct_clamped_to_100(monkeypatch):
    _patch_session(monkeypatch, {"home_office.business_use_pct": "150"})
    out = await cfs.CompanyFactsService().home_office_summary()
    assert out["business_use_pct"] == 100.0


async def test_home_office_reports_missing_fields(monkeypatch):
    _patch_session(monkeypatch, {"home_office.exclusive_sqft": "150"})
    out = await cfs.CompanyFactsService().home_office_summary()
    # only exclusive_sqft supplied → the other required labels are missing
    assert "Total home square feet" in out["missing_fields"]
    assert "Monthly rent or mortgage interest" in out["missing_fields"]
    assert out["method"] == "undecided"


async def test_home_office_empty_returns_undecided(monkeypatch):
    _patch_session(monkeypatch, {})
    out = await cfs.CompanyFactsService().home_office_summary()
    assert out["method"] == "undecided"
    assert out["business_use_pct"] is None
    assert out["simplified_estimate"] is None
    assert out["actual_estimate_annual"] is None
    assert out["facts_count"] == 0


# --------------------------------------------------------------------------- #
# deductions_summary
# --------------------------------------------------------------------------- #
async def test_deductions_cell_and_vehicle_default_rate(monkeypatch):
    _patch_session(
        monkeypatch,
        {
            "cell_phone.monthly": "100",
            "cell_phone.business_pct": "80",
            "vehicle.business_miles_ytd": "1000",
        },
    )
    out = await cfs.CompanyFactsService().deductions_summary()

    assert out["cell_phone"]["annual_deductible"] == 960.0  # 100*12*0.80
    # default mileage rate 0.725 (no tax.mileage_rate fact)
    assert out["vehicle"]["mileage_rate"] == cfs.CompanyFactsService.DEFAULT_MILEAGE_RATE
    assert out["vehicle"]["annual_deductible"] == 725.0  # 1000 * 0.725
    assert out["total_annual_deductible"] == 1685.0


async def test_deductions_editable_mileage_rate_overrides_default(monkeypatch):
    _patch_session(
        monkeypatch,
        {
            "vehicle.business_miles_ytd": "1000",
            "tax.mileage_rate": "0.70",
        },
    )
    out = await cfs.CompanyFactsService().deductions_summary()
    assert out["vehicle"]["mileage_rate"] == 0.70
    assert out["vehicle"]["annual_deductible"] == 700.0
    # cell phone absent → contributes 0 to total
    assert out["total_annual_deductible"] == 700.0


async def test_deductions_currency_symbols_parsed(monkeypatch):
    _patch_session(
        monkeypatch,
        {
            "cell_phone.monthly": "$100.00",
            "cell_phone.business_pct": "80%",
        },
    )
    out = await cfs.CompanyFactsService().deductions_summary()
    assert out["cell_phone"]["annual_deductible"] == 960.0


async def test_deductions_empty_totals_zero(monkeypatch):
    _patch_session(monkeypatch, {})
    out = await cfs.CompanyFactsService().deductions_summary()
    assert out["total_annual_deductible"] == 0.0
    assert out["cell_phone"]["annual_deductible"] is None
    assert out["vehicle"]["annual_deductible"] is None
