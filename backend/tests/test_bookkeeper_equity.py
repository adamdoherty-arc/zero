"""Tests for the paid_from → funding-account ledger posting and owner contributions.

Uses a real BookkeeperService against a tmp_path ledger (module path constants
monkeypatched), matching the service's file-based storage design.
"""

from __future__ import annotations

import json

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


def _ledger_text(tmp_path) -> str:
    return (tmp_path / "ledger.beancount").read_text(encoding="utf-8")


def test_funding_account_matching():
    assert bk.BookkeeperService._funding_account("personal card") == bk.EQUITY_CONTRIB_ACCOUNT
    assert bk.BookkeeperService._funding_account("Amex PERSONAL") == bk.EQUITY_CONTRIB_ACCOUNT
    assert bk.BookkeeperService._funding_account("business checking") == bk.BANK_ACCOUNT
    assert bk.BookkeeperService._funding_account(None) == bk.BANK_ACCOUNT
    assert bk.BookkeeperService._funding_account("") == bk.BANK_ACCOUNT


async def test_personal_paid_draft_posts_to_owner_equity(service, tmp_path):
    drafts = await service.ingest_bank_csv(
        source="bank_csv",
        csv_text="date,description,amount\n2026-07-01,Claude Max subscription,-200.00\n",
        paid_from="personal",
    )
    assert len(drafts) == 1
    accepted = await service.accept_draft(drafts[0].id, category="Expenses:Software:AI")
    assert accepted.status == "accepted"

    text = _ledger_text(tmp_path)
    assert bk.EQUITY_CONTRIB_ACCOUNT in text
    assert "Expenses:Software:AI" in text
    # Beancount convention: expense leg debits +200, owner equity is credited.
    assert "Expenses:Software:AI                200.00" in text
    assert f"{bk.EQUITY_CONTRIB_ACCOUNT}                   -200.00" in text


async def test_business_paid_draft_posts_to_bank(service, tmp_path):
    drafts = await service.ingest_bank_csv(
        source="bank_csv",
        csv_text="date,description,amount\n2026-07-02,AWS,-50.00\n",
        paid_from="business",
    )
    await service.accept_draft(drafts[0].id)
    text = _ledger_text(tmp_path)
    assert bk.BANK_ACCOUNT in text
    # no equity posting for business-paid entries
    assert text.count(bk.EQUITY_CONTRIB_ACCOUNT) <= text.count("open " + bk.EQUITY_CONTRIB_ACCOUNT)


async def test_recurring_registry_paid_from_flows_to_ledger(service, tmp_path):
    await service.add_recurring(
        vendor="Claude Max", amount_monthly=200.0, paid_from="personal card",
    )
    out = await service.generate_recurring_drafts(period="2026-06")
    assert out["created_count"] == 1
    draft_id = out["created"][0]["id"]
    await service.accept_draft(draft_id)
    text = _ledger_text(tmp_path)
    assert f"{bk.EQUITY_CONTRIB_ACCOUNT}                   -200.00" in text


async def test_legacy_draft_without_paid_from_defaults_to_bank(service, tmp_path):
    # Simulate a draft persisted before DraftEntry grew paid_from.
    legacy = {
        "id": "draft-legacy1",
        "date": "2026-05-01",
        "description": "Old draft",
        "amount": -10.0,
        "currency": "USD",
        "suggested_category": "Expenses:Office",
        "source": "manual",
        "raw": {},
        "status": "pending",
        "created_at": 0.0,
    }
    (tmp_path / "ledger_drafts.json").write_text(
        json.dumps({"drafts": [legacy]}), encoding="utf-8"
    )
    await service.accept_draft("draft-legacy1")
    text = _ledger_text(tmp_path)
    assert f"{bk.BANK_ACCOUNT}                   -10.00" in text


async def test_post_owner_contribution_writes_balanced_block(service, tmp_path):
    await service.post_owner_contribution(
        date_str="2026-07-01", description="Owner capital contribution — Workstation", amount=1200.0
    )
    text = _ledger_text(tmp_path)
    assert f"{bk.EQUIPMENT_ACCOUNT}                1200.00" in text
    assert f"{bk.EQUITY_CONTRIB_ACCOUNT}                   -1200.00" in text
    # both accounts opened
    assert f"open {bk.EQUIPMENT_ACCOUNT}" in text
    assert f"open {bk.EQUITY_CONTRIB_ACCOUNT}" in text


async def test_post_owner_contribution_zero_amount_is_noop(service, tmp_path):
    before = _ledger_text(tmp_path)
    await service.post_owner_contribution(date_str="2026-07-01", description="noop", amount=0)
    assert _ledger_text(tmp_path) == before


async def test_equity_postings_do_not_distort_snapshot(service):
    """Stub snapshot counts Expenses:*/Income:* categories only — equity is invisible."""
    drafts = await service.ingest_bank_csv(
        source="bank_csv",
        csv_text="date,description,amount\n2026-07-01,Claude Max,-200.00\n",
        paid_from="personal",
    )
    await service.accept_draft(drafts[0].id, category="Expenses:Software:AI")
    await service.post_owner_contribution(
        date_str="2026-07-01", description="contribution", amount=5000.0
    )
    snap = await service.snapshot(period="YTD")
    assert snap.expenses == 200.0
    assert snap.revenue == 0.0
