"""Tests for the AI bookkeeper agent: onboarding seed/dedupe, answer application,
parse failure reopen, triage exemption, and daily-sweep cooldowns.

DB-backed tests run against the shared zero_test database (same bootstrap the
`client` fixture uses); bookkeeper files and agent state are tmp_path-scoped.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from sqlalchemy import select

from tests import conftest as _conftest

import app.services.bookkeeper_agent_service as agent_mod
import app.services.bookkeeper_service as bk
from app.services.bookkeeper_agent_service import (
    ONBOARDING_SPECS,
    SOURCE_AGENT,
    SOURCE_ONBOARDING,
    BookkeeperAgentService,
)


@pytest.fixture
async def db():
    await _conftest._ensure_test_database(_conftest._test_postgres_url())


@pytest.fixture
def agent(tmp_path, monkeypatch):
    monkeypatch.setattr(bk, "LEDGER_DIR", tmp_path)
    monkeypatch.setattr(bk, "LEDGER_PATH", tmp_path / "ledger.beancount")
    monkeypatch.setattr(bk, "DRAFT_PATH", tmp_path / "ledger_drafts.json")
    monkeypatch.setattr(bk, "RECURRING_PATH", tmp_path / "recurring_expenses.json")
    monkeypatch.setattr(bk, "RULES_PATH", tmp_path / "categorization_rules.json")
    monkeypatch.setattr(bk, "get_bookkeeper_service", lambda: bk.BookkeeperService())
    monkeypatch.setattr(agent_mod, "STATE_PATH", tmp_path / "agent_state.json")
    monkeypatch.setattr(agent_mod, "KNOWLEDGE_DIR", tmp_path / "knowledge")
    return BookkeeperAgentService()


async def _purge_bookkeeper_questions():
    from app.db.models import CompanyAgentQuestionModel
    from app.infrastructure.database import get_session

    async with get_session() as session:
        rows = (
            await session.execute(
                select(CompanyAgentQuestionModel).where(
                    CompanyAgentQuestionModel.source.in_([SOURCE_ONBOARDING, SOURCE_AGENT])
                )
            )
        ).scalars().all()
        for row in rows:
            await session.delete(row)


# ---------------------------------------------------------------------------
# Pure parsers
# ---------------------------------------------------------------------------

def test_parse_subscriptions_variants():
    parse = BookkeeperAgentService._parse_subscriptions
    assert parse("Claude Max $200, ChatGPT $20, Cursor $20") == [
        ("Claude Max", 200.0), ("ChatGPT", 20.0), ("Cursor", 20.0),
    ]
    assert parse("Claude Max - 200\nGitHub Copilot: $10/mo") == [
        ("Claude Max", 200.0), ("GitHub Copilot", 10.0),
    ]
    assert parse("nothing here") == []


def test_parse_amounts_and_date_keeps_date_out_of_money():
    amounts, found = BookkeeperAgentService._parse_amounts_and_date("1800, 3200, 2026-05-01")
    assert amounts == [1800.0, 3200.0]
    assert found == "2026-05-01"

    amounts, found = BookkeeperAgentService._parse_amounts_and_date("$1,250.50")
    assert amounts == [1250.5]
    assert found is None


# ---------------------------------------------------------------------------
# Onboarding seed + dedupe
# ---------------------------------------------------------------------------

async def test_seed_is_idempotent_and_gap_driven(db, agent):
    await _purge_bookkeeper_questions()
    first = await agent.seed_onboarding_questions()
    assert first["created_count"] == first["pending_gaps"] > 0

    second = await agent.seed_onboarding_questions()
    assert second["created_count"] == 0

    # An answered question is never re-asked, even while the gap persists.
    from app.db.models import CompanyAgentQuestionModel
    from app.infrastructure.database import get_session

    async with get_session() as session:
        row = (
            await session.execute(
                select(CompanyAgentQuestionModel)
                .where(CompanyAgentQuestionModel.source == SOURCE_ONBOARDING)
                .limit(1)
            )
        ).scalars().first()
        row.status = "answered"
    third = await agent.seed_onboarding_questions()
    assert third["created_count"] == 0


# ---------------------------------------------------------------------------
# Answer application
# ---------------------------------------------------------------------------

def _spec(bk_key: str) -> dict:
    return next(s for s in ONBOARDING_SPECS if s["bk_key"] == bk_key)


def _serialized(spec: dict, answer: str, question_id: str = "") -> dict:
    return {
        "id": question_id,
        "answer": answer,
        "answered_by": "pytest",
        "source": SOURCE_ONBOARDING,
        "context": {"bk_key": spec["bk_key"], "apply": spec["apply"]},
    }


async def test_apply_company_fact_fills_worksheet(db, agent):
    from app.services.company_facts_service import get_company_facts_service

    result = await agent.apply_answer(_serialized(_spec("home_office.exclusive_sqft"), "150"))
    assert result["applied"] is True
    fact = await get_company_facts_service().get_fact("home_office.exclusive_sqft")
    assert fact is not None and fact.value == "150"

    ho = await get_company_facts_service().home_office_summary()
    assert "Exclusive business-use square feet" not in ho["missing_fields"]
    assert ho["simplified_estimate"] == 750.0  # 150 sqft x $5


async def test_apply_currency_strips_formatting(db, agent):
    result = await agent.apply_answer(_serialized(_spec("cell_phone.monthly"), "$1,234.50"))
    assert result["applied"] is True
    assert result["detail"]["value"] == "1234.5"


async def test_apply_recurring_list_populates_registry(db, agent):
    result = await agent.apply_answer(
        _serialized(_spec("subscriptions.ai"), "Claude Max $200, ChatGPT $20")
    )
    assert result["applied"] is True
    vendors = {r.vendor for r in await bk.get_bookkeeper_service().list_recurring()}
    assert vendors == {"Claude Max", "ChatGPT"}


async def test_apply_asset_contribution_registers_and_posts_equity(db, agent, tmp_path):
    from app.services.asset_service import get_asset_service

    result = await agent.apply_answer(
        _serialized(_spec("asset.computer_contribution"), "1800, 3200, 2026-05-01")
    )
    assert result["applied"] is True
    assert result["detail"]["deduction"] == 1800.0  # lesser of FMV/original x 100%

    assets = await get_asset_service().list_assets(year=2026)
    contributed = [a for a in assets if a.acquisition_type == "contributed"]
    assert contributed and contributed[0].fmv_at_contribution == 1800.0

    ledger = (tmp_path / "ledger.beancount").read_text(encoding="utf-8")
    assert bk.EQUITY_CONTRIB_ACCOUNT in ledger

    # cleanup so other tests' gap detection is unaffected across runs
    for a in contributed:
        await get_asset_service().delete_asset(a.id)


async def test_skip_answer_is_not_applied(db, agent):
    result = await agent.apply_answer(_serialized(_spec("home_office.insurance_monthly"), "skip"))
    assert result["applied"] is False
    assert result["reason"] == "skipped_by_user"


async def test_parse_failure_reopens_question_with_hint(db, agent, monkeypatch):
    from app.db.models import CompanyAgentQuestionModel
    from app.infrastructure.database import get_session

    monkeypatch.setattr(
        BookkeeperAgentService, "_llm_parse_subscriptions", staticmethod_async_empty
    )
    spec = _spec("subscriptions.ai")
    qid = f"caq-{uuid.uuid4().hex[:12]}"
    async with get_session() as session:
        session.add(
            CompanyAgentQuestionModel(
                id=qid, question=spec["question"], status="answered",
                answer="total gibberish with no amounts",
                context={"bk_key": spec["bk_key"], "apply": spec["apply"]},
                source=SOURCE_ONBOARDING, asked_by_agent="bookkeeper",
            )
        )

    result = await agent.apply_answer(_serialized(spec, "total gibberish with no amounts", qid))
    assert result["applied"] is False
    assert result["reason"] == "parse_error"

    async with get_session() as session:
        row = await session.get(CompanyAgentQuestionModel, qid)
        assert row.status == "open"
        assert row.context.get("parse_error")
        await session.delete(row)


async def staticmethod_async_empty(self, answer):  # noqa: ANN001
    return []


# ---------------------------------------------------------------------------
# Triage exemption
# ---------------------------------------------------------------------------

async def test_triage_never_dismisses_bookkeeper_questions(db, agent):
    from app.db.models import CompanyAgentQuestionModel
    from app.infrastructure.database import get_session
    from app.services.company_operator_service import get_company_operator_service

    # This text matches LOW_VALUE_QUESTION_RE — a normal agent question with it
    # would be auto-dismissed by triage.
    qid = f"caq-{uuid.uuid4().hex[:12]}"
    async with get_session() as session:
        session.add(
            CompanyAgentQuestionModel(
                id=qid,
                question="What confirmation or source should Zero attach for the ledger?",
                status="open", priority="high",
                context={"bk_key": "nag.test"},
                source=SOURCE_AGENT, asked_by_agent="bookkeeper",
            )
        )

    await get_company_operator_service().triage_questions(requested_by="pytest")

    async with get_session() as session:
        row = await session.get(CompanyAgentQuestionModel, qid)
        assert row.status == "open"
        await session.delete(row)


# ---------------------------------------------------------------------------
# Daily sweep — nag dedupe + cooldowns
# ---------------------------------------------------------------------------

async def test_daily_sweep_nags_once_and_respects_cooldown(db, agent):
    await _purge_bookkeeper_questions()
    svc = bk.get_bookkeeper_service()
    # Six pending drafts trips the drafts nag (> 5).
    csv_rows = "\n".join(f"2026-07-0{i},Vendor {i},-10.00" for i in range(1, 7))
    await svc.ingest_bank_csv(source="bank_csv", csv_text="date,description,amount\n" + csv_rows)

    first = await agent.daily_sweep(requested_by="pytest")
    draft_nags = [n for n in first["nags"] if n["check"].startswith("nag.drafts.")]
    assert len(draft_nags) == 1

    second = await agent.daily_sweep(requested_by="pytest")
    assert not [n for n in second["nags"] if n["check"].startswith("nag.drafts.")]

    await _purge_bookkeeper_questions()


# ---------------------------------------------------------------------------
# Books health grading
# ---------------------------------------------------------------------------

class _FakeTaxSummary:
    def __init__(self, amounts: dict[str, float]):
        self._amounts = amounts

    async def summary(self, *, year: int):
        return {
            "line_items": [{"key": k, "amount": v} for k, v in self._amounts.items()],
            "total_deductible": sum(self._amounts.values()),
            "est_total_tax_saved": 0.0,
        }


async def _no_gaps(self):
    return []


async def test_books_health_scores_dimensions(agent, monkeypatch):
    import app.services.tax_summary_service as ts_mod

    monkeypatch.setattr(BookkeeperAgentService, "_pending_onboarding_specs", _no_gaps)
    monkeypatch.setattr(
        ts_mod, "get_tax_summary_service",
        lambda: _FakeTaxSummary({"ledger": 100.0, "home_office": 1000.0, "cell_phone": 600.0, "hardware": 1800.0}),
    )
    # Fresh accepted entry today → freshness 100.
    svc = bk.get_bookkeeper_service()
    drafts = await svc.ingest_bank_csv(
        source="bank_csv",
        csv_text=f"date,description,amount\n{dt.date.today().isoformat()},AWS,-50.00\n",
    )
    await svc.accept_draft(drafts[0].id)

    health = await agent.books_health()
    dims = health["dimensions"]
    assert dims["completeness"] == 100.0
    assert dims["freshness"] == 100.0
    assert dims["reconciliation"] == 100.0  # no active recurring + no old drafts
    assert dims["deduction_capture"] == 100.0
    assert health["score"] == 100.0


async def test_books_health_weights_override(agent, monkeypatch):
    import app.services.tax_summary_service as ts_mod

    monkeypatch.setattr(BookkeeperAgentService, "_pending_onboarding_specs", _no_gaps)
    monkeypatch.setattr(
        ts_mod, "get_tax_summary_service", lambda: _FakeTaxSummary({"ledger": 0.0}),
    )
    # All weight on completeness (100) → perfect score despite empty books.
    agent._write_knowledge(
        "dimension_weights.json",
        {"completeness": 1.0, "freshness": 0.0, "reconciliation": 0.0, "deduction_capture": 0.0},
    )
    health = await agent.books_health()
    assert health["score"] == 100.0
    assert health["dimensions"]["deduction_capture"] == 0.0


def test_question_stats_recording(agent):
    agent.record_question_event("home_office.total_sqft", "asked")
    agent.record_question_event("home_office.total_sqft", "answered")
    agent.record_question_event("nag.drafts.2026-07", "dismissed")
    stats = agent._read_knowledge("question_stats.json", {})
    assert stats["home_office.total_sqft"] == {"asked": 1, "answered": 1, "dismissed": 0}
    assert stats["nag.drafts.2026-07"]["dismissed"] == 1


async def test_1040es_t3_window_fires_critical_nag(db, agent, monkeypatch):
    await _purge_bookkeeper_questions()

    class _FakeDate(dt.date):
        @classmethod
        def today(cls):
            return cls(2026, 9, 13)  # 2 days before the Sep 15 1040-ES date

    monkeypatch.setattr(agent_mod, "date", _FakeDate)
    report = await agent.daily_sweep(requested_by="pytest")
    es_nags = [n for n in report["nags"] if n["check"].startswith("nag.1040es.2026-09-15")]
    assert es_nags and es_nags[0]["priority"] == "critical"

    await _purge_bookkeeper_questions()
