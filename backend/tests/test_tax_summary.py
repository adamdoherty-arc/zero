"""Unit tests for the consolidated tax-savings rollup (dependencies faked, no DB)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.services.tax_summary_service as ts


class _FakeSnapshot:
    entity = "ADA AI LLC"
    by_category = {
        "Income:Software:Sales": 10000.0,  # income — must be ignored
        "Expenses:Software:AI": 100.0,
        "Expenses:Cloud": 300.0,
        "Expenses:Meals": 200.0,           # halved -> 100
        "Expenses:Hardware": 5000.0,       # excluded (asset register owns it)
        "Expenses:Phone": 50.0,            # excluded (cell-phone worksheet owns it)
        "Expenses:Auto": 80.0,             # excluded (vehicle worksheet owns it)
    }


class _FakeBookkeeper:
    async def snapshot(self, period="YTD"):
        return _FakeSnapshot()


class _FakeFacts:
    def __init__(self, facts: dict[str, str], home_office: dict | None = None):
        self._facts = facts
        self._home_office = home_office or {
            "actual_estimate_annual": 1200.0,
            "simplified_estimate": 1500.0,
            "missing_fields": [],
        }

    async def home_office_summary(self):
        return self._home_office

    async def deductions_summary(self):
        return {
            "cell_phone": {"annual_deductible": 600.0},
            "vehicle": {"annual_deductible": 870.0, "rate_note": "test"},
        }

    async def get_fact(self, key: str):
        v = self._facts.get(key)
        return SimpleNamespace(value=v) if v is not None else None


class _FakeAssets:
    async def total_current_year_deduction(self, *, year: int):
        return 1600.0


# Ledger after rules: AI 100 + Cloud 300 + Meals(50%) 100 = 500
# Plus home office 1200 + cell 600 + vehicle 870 + hardware 1600 = 4770
_EXPECTED_TOTAL = 500.0 + 1200.0 + 600.0 + 870.0 + 1600.0


def _patch(monkeypatch, facts: dict[str, str], home_office: dict | None = None):
    monkeypatch.setattr(ts, "get_bookkeeper_service", lambda: _FakeBookkeeper())
    monkeypatch.setattr(ts, "get_company_facts_service", lambda: _FakeFacts(facts, home_office))
    monkeypatch.setattr(ts, "get_asset_service", lambda: _FakeAssets())


async def test_rollup_excludes_income_and_double_counted_categories(monkeypatch):
    _patch(monkeypatch, {"tax.marginal_federal_pct": "24", "tax.include_se": "true"})
    out = await ts.TaxSummaryService().summary(year=2026)

    ledger = next(li for li in out["line_items"] if li["key"] == "ledger")
    assert ledger["amount"] == 500.0  # meals halved; hardware/phone/auto/income excluded
    assert out["total_deductible"] == _EXPECTED_TOTAL


async def test_income_and_se_tax_estimate(monkeypatch):
    _patch(monkeypatch, {"tax.marginal_federal_pct": "24", "tax.include_se": "true"})
    out = await ts.TaxSummaryService().summary(year=2026)

    assert out["marginal_federal_pct"] == 24.0
    assert out["est_income_tax_saved"] == round(_EXPECTED_TOTAL * 0.24, 2)
    assert out["est_se_tax_saved"] == round(_EXPECTED_TOTAL * 0.9235 * 0.153, 2)
    assert out["est_total_tax_saved"] == round(out["est_income_tax_saved"] + out["est_se_tax_saved"], 2)


async def test_se_tax_can_be_excluded(monkeypatch):
    _patch(monkeypatch, {"tax.marginal_federal_pct": "24", "tax.include_se": "false"})
    out = await ts.TaxSummaryService().summary(year=2026)

    assert out["include_se"] is False
    assert out["est_se_tax_saved"] == 0.0
    assert out["est_total_tax_saved"] == out["est_income_tax_saved"]


async def test_defaults_when_no_tax_facts(monkeypatch):
    _patch(monkeypatch, {})  # no tax.* facts set
    out = await ts.TaxSummaryService().summary(year=2026)

    assert out["marginal_federal_pct"] == ts.DEFAULT_MARGINAL_FEDERAL_PCT  # 22
    assert out["include_se"] is True  # SE defaults on


async def test_internet_standalone_under_simplified(monkeypatch):
    _patch(monkeypatch, {}, home_office={
        "actual_estimate_annual": None,  # forces simplified
        "simplified_estimate": 1000.0,
        "missing_fields": [],
        "inputs": {"internet_monthly": "80", "internet_business_pct": "50"},
    })
    out = await ts.TaxSummaryService().summary(year=2026)

    internet = next((li for li in out["line_items"] if li["key"] == "internet"), None)
    assert internet is not None
    assert internet["amount"] == round(80 * 12 * 0.5, 2)  # 480.0
    assert out["total_deductible"] == round(sum(li["amount"] for li in out["line_items"]), 2)


async def test_internet_absent_under_actual_method(monkeypatch):
    _patch(monkeypatch, {}, home_office={
        "actual_estimate_annual": 2000.0,  # actual wins — internet already inside
        "simplified_estimate": 1500.0,
        "missing_fields": [],
        "inputs": {"internet_monthly": "80", "internet_business_pct": "50"},
    })
    out = await ts.TaxSummaryService().summary(year=2026)
    assert not any(li["key"] == "internet" for li in out["line_items"])


async def test_internet_skipped_when_inputs_missing(monkeypatch):
    _patch(monkeypatch, {}, home_office={
        "actual_estimate_annual": None,
        "simplified_estimate": 1000.0,
        "missing_fields": ["Monthly internet"],
        "inputs": {},
    })
    out = await ts.TaxSummaryService().summary(year=2026)
    assert not any(li["key"] == "internet" for li in out["line_items"])


def test_to_float_and_bool_helpers():
    assert ts._to_float("$1,234.50", 0.0) == 1234.5
    assert ts._to_float("24%", 0.0) == 24.0
    assert ts._to_float(None, 22.0) == 22.0
    assert ts._to_float("garbage", 22.0) == 22.0
    assert ts._to_bool("true", False) is True
    assert ts._to_bool("no", True) is False
    assert ts._to_bool(None, True) is True
