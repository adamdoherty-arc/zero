"""Tests for the metered AI-spend draft generation (llm_usage → bookkeeper bridge)."""

from __future__ import annotations

import pytest

import app.services.bookkeeper_service as bk
import app.services.llm_spend_service as spend_mod


@pytest.fixture()
def service(tmp_path, monkeypatch):
    monkeypatch.setattr(bk, "LEDGER_DIR", tmp_path)
    monkeypatch.setattr(bk, "LEDGER_PATH", tmp_path / "ledger.beancount")
    monkeypatch.setattr(bk, "DRAFT_PATH", tmp_path / "ledger_drafts.json")
    monkeypatch.setattr(bk, "RECURRING_PATH", tmp_path / "recurring_expenses.json")
    monkeypatch.setattr(bk, "RULES_PATH", tmp_path / "categorization_rules.json")
    return bk.BookkeeperService()


class _FakeSpend:
    def __init__(self, amount: float):
        self._amount = amount

    async def spend_for_period(self, period: str) -> float:
        return self._amount

    async def monthly_spend(self, *, months: int = 12):
        return [{"period": "2026-06", "cost_usd": self._amount, "calls": 10, "by_provider": {}}]


def _patch_spend(monkeypatch, amount: float):
    monkeypatch.setattr(spend_mod, "get_llm_spend_service", lambda: _FakeSpend(amount))


async def test_metered_draft_created_once(service, monkeypatch):
    _patch_spend(monkeypatch, 42.5)
    first = await service.generate_metered_ai_draft(period="2026-06")
    assert first["reason"] == "created"
    assert first["created"]["amount"] == -42.5
    assert first["created"]["suggested_category"] == bk.AI_EXPENSE_ACCOUNT
    assert first["created"]["source"] == "llm_metered"

    second = await service.generate_metered_ai_draft(period="2026-06")
    assert second["reason"] == "already_generated"
    assert second["created"] is None

    drafts = await service.list_drafts()
    assert sum(1 for d in drafts if d.source == "llm_metered") == 1


async def test_metered_draft_skips_subcent_spend(service, monkeypatch):
    _patch_spend(monkeypatch, 0.004)
    out = await service.generate_metered_ai_draft(period="2026-06")
    assert out["reason"] == "no_metered_spend"
    assert (await service.list_drafts()) == []


async def test_metered_draft_different_periods_are_independent(service, monkeypatch):
    _patch_spend(monkeypatch, 10.0)
    assert (await service.generate_metered_ai_draft(period="2026-05"))["reason"] == "created"
    assert (await service.generate_metered_ai_draft(period="2026-06"))["reason"] == "created"
    drafts = await service.list_drafts()
    assert sum(1 for d in drafts if d.source == "llm_metered") == 2


async def test_recurring_summary_includes_metered_block(service, monkeypatch):
    _patch_spend(monkeypatch, 33.0)
    summary = await service.recurring_summary(period="2026-06")
    assert summary["metered"] == {"period_cost": 33.0, "ytd_cost": 33.0}


async def test_recurring_summary_metered_degrades_to_none(service, monkeypatch):
    class _Boom:
        async def monthly_spend(self, *, months: int = 12):
            raise RuntimeError("db down")

    monkeypatch.setattr(spend_mod, "get_llm_spend_service", lambda: _Boom())
    summary = await service.recurring_summary(period="2026-06")
    assert summary["metered"] is None
