"""Tests for the Schedule C category mapping and rollup."""

from __future__ import annotations

from types import SimpleNamespace

import app.services.tax_summary_service as ts
from app.services.bookkeeper_service import RECURRING_CATEGORY_PRESETS
from app.services.schedule_c_map import build_rollup, map_category, map_worksheet


def test_longest_prefix_wins():
    assert map_category("Expenses:Software:AI")["label"] == "Other expenses — AI/LLM services"
    assert map_category("Expenses:Software")["label"] == "Other expenses — software subscriptions"
    assert map_category("Expenses:Fees:Bank")["line"] == "27a"


def test_every_recurring_preset_maps():
    for preset in RECURRING_CATEGORY_PRESETS:
        mapped = map_category(preset["account"])
        assert mapped["line"] and mapped["label"]


def test_unknown_category_falls_back_to_27a():
    assert map_category("Expenses:SomethingNew")["line"] == "27a"


def test_worksheet_lines():
    assert map_worksheet("home_office")["line"] == "30"
    assert map_worksheet("internet")["line"] == "25"
    assert map_worksheet("cell_phone")["line"] == "25"
    assert map_worksheet("vehicle")["line"] == "9"
    assert map_worksheet("hardware")["line"] == "13"


def test_build_rollup_aggregates_and_sorts():
    rollup = build_rollup([
        {"line": "25", "label": "Utilities (phone)", "amount": 600.0, "category": "cell_phone"},
        {"line": "25", "label": "Utilities (phone)", "amount": 480.0, "category": "internet"},
        {"line": "9", "label": "Car and truck expenses", "amount": 100.0, "category": "vehicle"},
        {"line": "24b", "label": "Deductible meals", "amount": 50.0, "category": "Expenses:Meals"},
    ])
    assert [r["line"] for r in rollup] == ["9", "24b", "25"]
    line25 = next(r for r in rollup if r["line"] == "25")
    assert line25["amount"] == 1080.0
    assert set(line25["categories"]) == {"cell_phone", "internet"}


# ---------------------------------------------------------------------------
# End-to-end: summary rollup total equals total_deductible (faked deps,
# mirrors test_tax_summary's fixtures).
# ---------------------------------------------------------------------------

class _FakeSnapshot:
    entity = "ADA AI LLC"
    by_category = {
        "Expenses:Software:AI": 100.0,
        "Expenses:Cloud": 300.0,
        "Expenses:Meals": 200.0,  # halved -> 100
        "Expenses:Hardware": 5000.0,  # excluded
    }


class _FakeBookkeeper:
    async def snapshot(self, period="YTD"):
        return _FakeSnapshot()


class _FakeFacts:
    async def home_office_summary(self):
        return {"actual_estimate_annual": 1200.0, "simplified_estimate": 1500.0, "missing_fields": []}

    async def deductions_summary(self):
        return {
            "cell_phone": {"annual_deductible": 600.0},
            "vehicle": {"annual_deductible": 870.0, "rate_note": "test"},
        }

    async def get_fact(self, key: str):
        return SimpleNamespace(value=None) if False else None


class _FakeAssets:
    async def total_current_year_deduction(self, *, year: int):
        return 1600.0


async def test_rollup_total_equals_total_deductible(monkeypatch):
    monkeypatch.setattr(ts, "get_bookkeeper_service", lambda: _FakeBookkeeper())
    monkeypatch.setattr(ts, "get_company_facts_service", lambda: _FakeFacts())
    monkeypatch.setattr(ts, "get_asset_service", lambda: _FakeAssets())

    out = await ts.TaxSummaryService().summary(year=2026)
    rollup_total = round(sum(r["amount"] for r in out["schedule_c_rollup"]), 2)
    assert rollup_total == out["total_deductible"]
    # worksheet items are annotated
    ho = next(li for li in out["line_items"] if li["key"] == "home_office")
    assert ho["schedule_c"]["line"] == "30"
