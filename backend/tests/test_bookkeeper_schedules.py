"""Tests for recurring-transaction detection (find-schedules port)."""

from __future__ import annotations

import pytest

import app.services.bookkeeper_service as bk


@pytest.fixture()
def service(tmp_path, monkeypatch):
    monkeypatch.setattr(bk, "LEDGER_DIR", tmp_path)
    monkeypatch.setattr(bk, "LEDGER_PATH", tmp_path / "ledger.beancount")
    monkeypatch.setattr(bk, "DRAFT_PATH", tmp_path / "ledger_drafts.json")
    monkeypatch.setattr(bk, "RECURRING_PATH", tmp_path / "recurring_expenses.json")
    monkeypatch.setattr(bk, "RULES_PATH", tmp_path / "categorization_rules.json")
    return bk.BookkeeperService()


async def _seed(service, rows: list[tuple[str, str, float]]):
    csv_text = "date,description,amount\n" + "\n".join(
        f"{d},{desc},{amt}" for d, desc, amt in rows
    )
    return await service.ingest_bank_csv(source="bank_csv", csv_text=csv_text)


async def test_detects_monthly_subscription(service):
    await _seed(service, [
        ("2026-05-03", "NETLIFY HOSTING", -19.00),
        ("2026-06-03", "NETLIFY HOSTING", -19.00),
        ("2026-07-03", "NETLIFY HOSTING", -19.00),
    ])
    suggestions = await service.suggest_recurring()
    assert len(suggestions) == 1
    s = suggestions[0]
    assert s["vendor"].lower() == "netlify hosting"
    assert s["amount_monthly"] == 19.0
    assert s["billing_day"] == 3
    assert s["occurrences"] == 3


async def test_single_month_not_suggested(service):
    await _seed(service, [
        ("2026-07-01", "ONE OFF VENDOR", -50.00),
        ("2026-07-15", "ONE OFF VENDOR", -50.00),  # twice, same month
    ])
    assert await service.suggest_recurring() == []


async def test_high_amount_variance_rejected(service):
    await _seed(service, [
        ("2026-05-03", "VARIABLE VENDOR", -10.00),
        ("2026-06-03", "VARIABLE VENDOR", -30.00),  # 200% of median spread
    ])
    assert await service.suggest_recurring() == []


async def test_registry_vendors_excluded(service):
    await service.add_recurring(vendor="Netlify Hosting", amount_monthly=19.0)
    await _seed(service, [
        ("2026-05-03", "NETLIFY HOSTING", -19.00),
        ("2026-06-03", "NETLIFY HOSTING", -19.00),
    ])
    assert await service.suggest_recurring() == []


async def test_income_and_generated_drafts_ignored(service):
    # Positive amounts (income) and recurring-source drafts never suggest.
    await _seed(service, [
        ("2026-05-01", "CLIENT PAYMENT", 500.00),
        ("2026-06-01", "CLIENT PAYMENT", 500.00),
    ])
    await service.add_recurring(vendor="Claude Max", amount_monthly=200.0)
    await service.generate_recurring_drafts(period="2026-05")
    await service.generate_recurring_drafts(period="2026-06")
    assert await service.suggest_recurring() == []


async def test_accept_flow_creates_registry_entry_and_stops_suggesting(service):
    await _seed(service, [
        ("2026-05-03", "NETLIFY HOSTING", -19.00),
        ("2026-06-03", "NETLIFY HOSTING", -19.00),
    ])
    [s] = await service.suggest_recurring()
    await service.add_recurring(
        vendor=s["vendor"], amount_monthly=s["amount_monthly"],
        category=s["category"], billing_day=s["billing_day"],
    )
    assert await service.suggest_recurring() == []
    out = await service.generate_recurring_drafts(period="2026-08")
    assert out["created_count"] == 1
