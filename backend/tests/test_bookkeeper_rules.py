"""Tests for the categorization rules engine, category learning, and OFX ingest."""

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


OFX_FIXTURE = """OFXHEADER:100
DATA:OFXSGML
VERSION:102
SECURITY:NONE
ENCODING:USASCII
CHARSET:1252
COMPRESSION:NONE
OLDFILEUID:NONE
NEWFILEUID:NONE

<OFX>
<SIGNONMSGSRSV1><SONRS><STATUS><CODE>0<SEVERITY>INFO</STATUS><DTSERVER>20260701120000<LANGUAGE>ENG</SONRS></SIGNONMSGSRSV1>
<BANKMSGSRSV1><STMTTRNRS><TRNUID>1<STATUS><CODE>0<SEVERITY>INFO</STATUS>
<STMTRS><CURDEF>USD<BANKACCTFROM><BANKID>123456789<ACCTID>000123456<ACCTTYPE>CHECKING</BANKACCTFROM>
<BANKTRANLIST><DTSTART>20260601<DTEND>20260630
<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20260605<TRNAMT>-200.00<FITID>FIT001<NAME>CLAUDE.AI SUBSCRIPTION</STMTTRN>
<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20260610<TRNAMT>-54.20<FITID>FIT002<NAME>AWS</STMTTRN>
</BANKTRANLIST>
<LEDGERBAL><BALAMT>1000.00<DTASOF>20260630</LEDGERBAL>
</STMTRS></STMTTRNRS></BANKMSGSRSV1>
</OFX>
"""


# ---------------------------------------------------------------------------
# Payee normalization
# ---------------------------------------------------------------------------

def test_normalize_payee_strips_noise(service):
    norm = service._normalize_payee
    assert norm("CLAUDE.AI *MAX 07/01 CARD 1234") == "claude.ai max"
    assert norm("AWS.AMAZON.COM PURCHASE #99182") == "aws.amazon.com"
    assert norm("Uber   Trip 2026-06-01") == "uber trip"


# ---------------------------------------------------------------------------
# Rule precedence + matching
# ---------------------------------------------------------------------------

async def test_rule_beats_keyword_fallback(service):
    # Keyword table would put 'openai' under Expenses:Software.
    assert service._suggest_category("OPENAI CHATGPT", -20) == "Expenses:Software"
    await service.add_rule(match_type="contains", pattern="openai", category="Expenses:Software:AI")
    assert service._suggest_category("OPENAI CHATGPT", -20) == "Expenses:Software:AI"


async def test_rule_priority_order(service):
    await service.add_rule(match_type="contains", pattern="cloud", category="Expenses:Office", priority=200)
    await service.add_rule(match_type="contains", pattern="cloud", category="Expenses:Cloud", priority=10)
    assert service._suggest_category("SOMECLOUD HOSTING", -5) == "Expenses:Cloud"


async def test_regex_rule(service):
    await service.add_rule(match_type="regex", pattern=r"^GH\s?PRO", category="Expenses:Software")
    assert service._suggest_category("GH PRO subscription", -4) == "Expenses:Software"


# ---------------------------------------------------------------------------
# Learning from accepted drafts
# ---------------------------------------------------------------------------

async def test_accept_with_override_learns_payee_rule(service):
    drafts = await service.ingest_bank_csv(
        source="bank_csv",
        csv_text="date,description,amount\n2026-07-01,CLAUDE.AI *MAX 07/01,-200.00\n",
    )
    await service.accept_draft(drafts[0].id, category="Expenses:Software:AI")

    rules = await service.list_rules()
    learned = [r for r in rules if r.learned]
    assert len(learned) == 1
    assert learned[0].match_type == "payee"
    assert learned[0].pattern == "claude.ai max"
    assert learned[0].category == "Expenses:Software:AI"

    # Next ingest of the same payee auto-suggests the learned category.
    drafts2 = await service.ingest_bank_csv(
        source="bank_csv",
        csv_text="date,description,amount\n2026-08-01,CLAUDE.AI *MAX 08/01,-200.00\n",
    )
    assert drafts2[0].suggested_category == "Expenses:Software:AI"


async def test_plain_accept_bumps_hits_not_rules(service):
    await service.add_rule(match_type="contains", pattern="aws", category="Expenses:Cloud")
    drafts = await service.ingest_bank_csv(
        source="bank_csv", csv_text="date,description,amount\n2026-07-01,AWS,-50.00\n",
    )
    assert drafts[0].suggested_category == "Expenses:Cloud"
    await service.accept_draft(drafts[0].id)

    rules = await service.list_rules()
    assert len(rules) == 1  # no new rule learned
    assert rules[0].hits == 1  # confidence bumped


async def test_learning_override_updates_existing_learned_rule(service):
    drafts = await service.ingest_bank_csv(
        source="bank_csv",
        csv_text=(
            "date,description,amount\n"
            "2026-07-01,NEWVENDOR X,-10.00\n"
            "2026-08-01,NEWVENDOR X,-10.00\n"
        ),
    )
    # Keyword default for an unknown vendor is Expenses:Office, so both of
    # these are genuine overrides.
    await service.accept_draft(drafts[0].id, category="Expenses:Education")
    await service.accept_draft(drafts[1].id, category="Expenses:Software")

    rules = [r for r in await service.list_rules() if r.learned]
    assert len(rules) == 1
    assert rules[0].category == "Expenses:Software"  # latest override wins
    assert rules[0].hits == 2


# ---------------------------------------------------------------------------
# OFX ingest
# ---------------------------------------------------------------------------

async def test_ofx_ingest_creates_drafts(service):
    drafts = await service.ingest_ofx(source="bank_ofx", ofx_bytes=OFX_FIXTURE.encode())
    assert len(drafts) == 2
    by_fitid = {d.raw["fitid"]: d for d in drafts}
    assert by_fitid["FIT001"].amount == -200.0
    assert "CLAUDE.AI" in by_fitid["FIT001"].description
    assert by_fitid["FIT002"].suggested_category == "Expenses:Cloud"  # aws keyword
    assert by_fitid["FIT001"].date == "2026-06-05"


async def test_ofx_reupload_dedupes_on_fitid(service):
    first = await service.ingest_ofx(source="bank_ofx", ofx_bytes=OFX_FIXTURE.encode())
    assert len(first) == 2
    second = await service.ingest_ofx(source="bank_ofx", ofx_bytes=OFX_FIXTURE.encode())
    assert second == []
    assert len(await service.list_drafts()) == 2


async def test_ofx_garbage_raises_value_error(service):
    with pytest.raises(ValueError):
        await service.ingest_ofx(source="bank_ofx", ofx_bytes=b"not an ofx file at all")
