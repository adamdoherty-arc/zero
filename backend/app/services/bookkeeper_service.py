"""
ADA AI bookkeeper.

Wraps Beancount when installed, otherwise operates in a "stub" mode that
keeps a JSON-backed ledger so the surface still answers voice questions
without crashing. Design goals:

* **Plain-text first** — the journal is a Beancount file at
  ``workspace/ada_ai/ledger.beancount`` so Adam can read or edit it by
  hand, version it, and run Fava against it for charts.
* **CSV import is draft-only** — bank exports (Mercury, Chase) become
  *draft* journal entries the LLM categorizes; nothing is auto-posted.
* **Voice-friendly** — ``answer_voice_question`` returns short prose
  prompted from ledger state.

This service is intentionally side-effect light. The supervisor's
bookkeeper adapter calls ``answer_voice_question``; the daily brief and
dashboard call ``snapshot``. Everything else is human-loop.
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Optional

import structlog

logger = structlog.get_logger()

LEDGER_DIR = Path("workspace") / "ada_ai"
LEDGER_PATH = LEDGER_DIR / "ledger.beancount"
DRAFT_PATH = LEDGER_DIR / "ledger_drafts.json"
RECURRING_PATH = LEDGER_DIR / "recurring_expenses.json"
RULES_PATH = LEDGER_DIR / "categorization_rules.json"
ENTITY_NAME = os.getenv("ADA_AI_LEGAL_NAME", "ADA AI LLC")
# Default expense account for AI/LLM subscriptions (Claude Max, ChatGPT, Cursor, ...).
AI_EXPENSE_ACCOUNT = "Expenses:Software:AI"
# Funding sides. Personal-paid business expenses are still deductible for a
# disregarded-entity SMLLC — the paying account only decides the balancing
# posting: business account vs owner capital contribution.
BANK_ACCOUNT = "Assets:Bank:Mercury"
EQUITY_CONTRIB_ACCOUNT = "Equity:Owner:Contributions"
EQUIPMENT_ACCOUNT = "Assets:Equipment"
DEFAULT_CURRENCY = os.getenv("ADA_AI_CURRENCY", "USD")
QUARTERLY_TAX_RATE = float(os.getenv("ADA_AI_TAX_RATE_EST", "0.22"))

# First-class expense categories the recurring-expense form offers as presets.
# Each posts to the matching Beancount account; `_ensure_account_open` opens any
# account lazily on first accepted draft, so adding here is purely UX surfacing.
RECURRING_CATEGORY_PRESETS: list[dict[str, str]] = [
    {"account": "Expenses:Software:AI", "label": "AI / LLM subscriptions"},
    {"account": "Expenses:Software", "label": "Software / SaaS (non-AI)"},
    {"account": "Expenses:Cloud", "label": "Cloud / hosting"},
    {"account": "Expenses:Phone", "label": "Phone / mobile"},
    {"account": "Expenses:Office", "label": "Office / supplies"},
    {"account": "Expenses:Insurance", "label": "Business insurance"},
    {"account": "Expenses:Professional", "label": "Professional services"},
    {"account": "Expenses:Education", "label": "Education / training"},
    {"account": "Expenses:Fees:Bank", "label": "Bank / merchant fees"},
    {"account": "Expenses:Travel", "label": "Travel"},
    {"account": "Expenses:Meals", "label": "Meals (50%)"},
]


@dataclass
class LedgerSnapshot:
    entity: str
    period: str  # "YTD" | "MTD" | "QTD"
    revenue: float
    expenses: float
    net: float
    by_category: dict[str, float] = field(default_factory=dict)
    estimated_tax: float = 0.0
    last_entry_at: Optional[str] = None
    pending_drafts: int = 0
    backend: str = "stub"

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity": self.entity,
            "period": self.period,
            "revenue": round(self.revenue, 2),
            "expenses": round(self.expenses, 2),
            "net": round(self.net, 2),
            "by_category": {k: round(v, 2) for k, v in self.by_category.items()},
            "estimated_tax": round(self.estimated_tax, 2),
            "last_entry_at": self.last_entry_at,
            "pending_drafts": self.pending_drafts,
            "backend": self.backend,
        }


@dataclass
class DraftEntry:
    id: str
    date: str
    description: str
    amount: float
    currency: str
    suggested_category: str
    source: str  # bank_csv | receipt_ocr | voice | manual
    raw: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"  # pending | accepted | rejected
    paid_from: str = "business"  # business | personal (any "personal..." string)
    created_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "date": self.date,
            "description": self.description,
            "amount": round(self.amount, 2),
            "currency": self.currency,
            "suggested_category": self.suggested_category,
            "source": self.source,
            "raw": dict(self.raw),
            "status": self.status,
            "paid_from": self.paid_from,
            "created_at": self.created_at,
        }


@dataclass
class CategorizationRule:
    """A persisted transaction-categorization rule.

    Clean-room reimplementation of Actual Budget's rules model (MIT,
    github.com/actualbudget/actual — conditions→actions + payee category
    learning). Rules are consulted before the keyword fallback; accepting a
    draft with a category override auto-writes a `payee` rule (learned=True),
    and plain accepts bump `hits` as a confidence signal.
    """

    id: str
    match_type: str  # payee | contains | regex
    pattern: str
    category: str
    priority: int = 100  # lower wins
    active: bool = True
    hits: int = 0
    learned: bool = False
    created_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "match_type": self.match_type,
            "pattern": self.pattern,
            "category": self.category,
            "priority": self.priority,
            "active": self.active,
            "hits": self.hits,
            "learned": self.learned,
            "created_at": self.created_at,
        }


@dataclass
class RecurringExpense:
    """A recurring business expense Adam pays on a fixed cadence.

    Built for AI/LLM subscriptions (Claude Max, ChatGPT, Cursor, ...) that are
    flat-rate and don't show up in Zero's metered `llm_usage` table, but works
    for any monthly business expense. Each active entry emits one reviewable
    ``DraftEntry`` per month via ``generate_recurring_drafts``.
    """

    id: str
    vendor: str
    amount_monthly: float
    category: str = AI_EXPENSE_ACCOUNT
    billing_day: int = 1
    paid_from: str = "personal card"
    active: bool = True
    notes: str = ""
    created_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "vendor": self.vendor,
            "amount_monthly": round(self.amount_monthly, 2),
            "category": self.category,
            "billing_day": self.billing_day,
            "paid_from": self.paid_from,
            "active": self.active,
            "notes": self.notes,
            "created_at": self.created_at,
        }


class BookkeeperService:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        LEDGER_DIR.mkdir(parents=True, exist_ok=True)
        if not LEDGER_PATH.exists():
            self._write_initial_ledger()
        if not DRAFT_PATH.exists():
            DRAFT_PATH.write_text(json.dumps({"drafts": []}, indent=2), encoding="utf-8")
        if not RECURRING_PATH.exists():
            RECURRING_PATH.write_text(json.dumps({"recurring": []}, indent=2), encoding="utf-8")
        if not RULES_PATH.exists():
            RULES_PATH.write_text(json.dumps({"rules": []}, indent=2), encoding="utf-8")

    # ------------------------------------------------------------------
    # Backend detection — Beancount when installed, stub otherwise.
    # ------------------------------------------------------------------
    def _have_beancount(self) -> bool:
        try:
            import beancount  # type: ignore  # noqa: F401
            return True
        except Exception:
            return False

    def _backend_name(self) -> str:
        return "beancount" if self._have_beancount() else "stub"

    # ------------------------------------------------------------------
    # File IO
    # ------------------------------------------------------------------
    def _write_initial_ledger(self) -> None:
        opening = (
            f'option "title" "{ENTITY_NAME}"\n'
            f'option "operating_currency" "{DEFAULT_CURRENCY}"\n\n'
            f"; Open the standard chart of accounts for a single-member LLC.\n"
            f"1970-01-01 open Assets:Bank:Mercury           {DEFAULT_CURRENCY}\n"
            f"1970-01-01 open Assets:Bank:Chase             {DEFAULT_CURRENCY}\n"
            f"1970-01-01 open Income:Software:Sales         {DEFAULT_CURRENCY}\n"
            f"1970-01-01 open Income:Consulting             {DEFAULT_CURRENCY}\n"
            f"1970-01-01 open Expenses:Software             {DEFAULT_CURRENCY}\n"
            f"1970-01-01 open Expenses:Software:AI          {DEFAULT_CURRENCY}\n"
            f"1970-01-01 open Expenses:Cloud                {DEFAULT_CURRENCY}\n"
            f"1970-01-01 open Expenses:Hardware             {DEFAULT_CURRENCY}\n"
            f"1970-01-01 open Expenses:Office               {DEFAULT_CURRENCY}\n"
            f"1970-01-01 open Expenses:Phone                {DEFAULT_CURRENCY}\n"
            f"1970-01-01 open Expenses:Travel               {DEFAULT_CURRENCY}\n"
            f"1970-01-01 open Expenses:Meals                {DEFAULT_CURRENCY}\n"
            f"1970-01-01 open Expenses:Auto                 {DEFAULT_CURRENCY}\n"
            f"1970-01-01 open Expenses:Education            {DEFAULT_CURRENCY}\n"
            f"1970-01-01 open Expenses:Insurance            {DEFAULT_CURRENCY}\n"
            f"1970-01-01 open Expenses:Professional         {DEFAULT_CURRENCY}\n"
            f"1970-01-01 open Expenses:Fees:Bank            {DEFAULT_CURRENCY}\n"
            f"1970-01-01 open Expenses:Legal                {DEFAULT_CURRENCY}\n"
            f"1970-01-01 open Expenses:Tax:Federal          {DEFAULT_CURRENCY}\n"
            f"1970-01-01 open Expenses:Tax:State            {DEFAULT_CURRENCY}\n"
            f"1970-01-01 open Equity:Owner:Adam             {DEFAULT_CURRENCY}\n"
            f"1970-01-01 open Equity:Owner:Contributions    {DEFAULT_CURRENCY}\n"
            f"1970-01-01 open Assets:Equipment              {DEFAULT_CURRENCY}\n"
        )
        LEDGER_PATH.write_text(opening, encoding="utf-8")

    def _ensure_account_open(self, account: str) -> None:
        """Idempotently append a Beancount `open` directive for `account`.

        New ledgers get the full chart from `_write_initial_ledger`, but ledgers
        created before a category existed (e.g. Expenses:Software:AI) need the
        account opened before a transaction can post against it. No-op in stub
        mode (snapshot derives from accepted drafts, not the file), harmless in
        beancount mode.
        """
        try:
            existing = LEDGER_PATH.read_text(encoding="utf-8")
        except Exception:
            return
        if re.search(rf"^\s*\d{{4}}-\d{{2}}-\d{{2}}\s+open\s+{re.escape(account)}\b", existing, re.M):
            return
        try:
            with open(LEDGER_PATH, "a", encoding="utf-8") as f:
                f.write(f"1970-01-01 open {account}    {DEFAULT_CURRENCY}\n")
        except Exception as e:
            logger.warning("bookkeeper_open_account_failed", account=account, error=str(e))

    def _read_drafts(self) -> list[DraftEntry]:
        try:
            data = json.loads(DRAFT_PATH.read_text(encoding="utf-8"))
        except Exception:
            return []
        out: list[DraftEntry] = []
        for r in data.get("drafts") or []:
            try:
                out.append(DraftEntry(**{**r, "raw": r.get("raw") or {}}))
            except Exception:
                continue
        return out

    def _write_drafts(self, drafts: list[DraftEntry]) -> None:
        DRAFT_PATH.write_text(
            json.dumps(
                {"drafts": [d.to_dict() for d in drafts]},
                indent=2, sort_keys=True,
            ),
            encoding="utf-8",
        )

    # ------------------------------------------------------------------
    # Categorization rules — persisted, learned from accepted drafts.
    # ------------------------------------------------------------------
    def _read_rules(self) -> list[CategorizationRule]:
        try:
            data = json.loads(RULES_PATH.read_text(encoding="utf-8"))
        except Exception:
            return []
        out: list[CategorizationRule] = []
        for r in data.get("rules") or []:
            try:
                out.append(CategorizationRule(**r))
            except Exception:
                continue
        return out

    def _write_rules(self, rules: list[CategorizationRule]) -> None:
        RULES_PATH.write_text(
            json.dumps({"rules": [r.to_dict() for r in rules]}, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    @staticmethod
    def _normalize_payee(description: str) -> str:
        """Stable payee key from a raw bank description.

        Strips dates, card suffixes, and trailing numbers ('CLAUDE.AI *MAX
        07/01 CARD 1234' → 'claude.ai max'), keeps the first three tokens.
        """
        text = (description or "").lower()
        text = re.sub(r"\d{1,4}[/-]\d{1,2}([/-]\d{2,4})?", " ", text)  # dates
        text = re.sub(r"\b(card|ref|conf|auth|txn|purchase|payment)\b\s*#?\s*\d*", " ", text)
        text = re.sub(r"[*#]+", " ", text)
        text = re.sub(r"\b\d{3,}\b", " ", text)  # long digit runs
        tokens = [t for t in re.split(r"[^a-z0-9.&'+-]+", text) if t]
        return " ".join(tokens[:3])

    def _match_rule(self, description: str) -> Optional[CategorizationRule]:
        desc = (description or "").lower()
        payee = self._normalize_payee(description)
        rules = sorted(
            (r for r in self._read_rules() if r.active),
            key=lambda r: (r.priority, -r.hits),
        )
        for rule in rules:
            try:
                if rule.match_type == "payee" and payee and payee == rule.pattern.lower():
                    return rule
                if rule.match_type == "contains" and rule.pattern.lower() in desc:
                    return rule
                if rule.match_type == "regex" and re.search(rule.pattern, description or "", re.I):
                    return rule
            except Exception:
                continue
        return None

    def _learn_rule(self, description: str, category: str) -> None:
        """Adam overrode the suggestion — remember the payee→category mapping."""
        payee = self._normalize_payee(description)
        if not payee or not category:
            return
        rules = self._read_rules()
        for rule in rules:
            if rule.match_type == "payee" and rule.pattern.lower() == payee:
                rule.category = category
                rule.hits += 1
                self._write_rules(rules)
                return
        rules.append(
            CategorizationRule(
                id=f"rule-{uuid.uuid4().hex[:10]}",
                match_type="payee",
                pattern=payee,
                category=category,
                priority=50,  # learned rules beat manual defaults
                learned=True,
                hits=1,
                created_at=time.time(),
            )
        )
        self._write_rules(rules)
        logger.info("bookkeeper_rule_learned", payee=payee, category=category)

    def _bump_rule_hit(self, description: str) -> None:
        rule = self._match_rule(description)
        if not rule:
            return
        rules = self._read_rules()
        for r in rules:
            if r.id == rule.id:
                r.hits += 1
                self._write_rules(rules)
                return

    async def list_rules(self) -> list[CategorizationRule]:
        async with self._lock:
            rules = self._read_rules()
        rules.sort(key=lambda r: (r.priority, -r.hits))
        return rules

    async def add_rule(
        self, *, match_type: str, pattern: str, category: str, priority: int = 100
    ) -> CategorizationRule:
        rule = CategorizationRule(
            id=f"rule-{uuid.uuid4().hex[:10]}",
            match_type=match_type if match_type in ("payee", "contains", "regex") else "contains",
            pattern=pattern.strip()[:200],
            category=category.strip(),
            priority=int(priority),
            created_at=time.time(),
        )
        async with self._lock:
            rules = self._read_rules()
            rules.append(rule)
            self._write_rules(rules)
        return rule

    async def update_rule(self, rule_id: str, **fields: Any) -> Optional[CategorizationRule]:
        async with self._lock:
            rules = self._read_rules()
            for rule in rules:
                if rule.id != rule_id:
                    continue
                for key in ("match_type", "pattern", "category"):
                    if fields.get(key):
                        setattr(rule, key, str(fields[key]).strip())
                if fields.get("priority") is not None:
                    rule.priority = int(fields["priority"])
                if fields.get("active") is not None:
                    rule.active = bool(fields["active"])
                self._write_rules(rules)
                return rule
        return None

    async def delete_rule(self, rule_id: str) -> bool:
        async with self._lock:
            rules = self._read_rules()
            kept = [r for r in rules if r.id != rule_id]
            if len(kept) == len(rules):
                return False
            self._write_rules(kept)
        return True

    # ------------------------------------------------------------------
    # Recurring expenses — manual AI-subscription registry.
    # ------------------------------------------------------------------
    def _read_recurring(self) -> list[RecurringExpense]:
        try:
            data = json.loads(RECURRING_PATH.read_text(encoding="utf-8"))
        except Exception:
            return []
        out: list[RecurringExpense] = []
        for r in data.get("recurring") or []:
            try:
                out.append(RecurringExpense(**r))
            except Exception:
                continue
        return out

    def _write_recurring(self, items: list[RecurringExpense]) -> None:
        RECURRING_PATH.write_text(
            json.dumps(
                {"recurring": [r.to_dict() for r in items]},
                indent=2, sort_keys=True,
            ),
            encoding="utf-8",
        )

    @staticmethod
    def _clamp_billing_day(day: Any) -> int:
        try:
            d = int(day)
        except Exception:
            d = 1
        return max(1, min(28, d))

    @staticmethod
    def _current_period() -> str:
        today = date.today()
        return f"{today.year:04d}-{today.month:02d}"

    @staticmethod
    def _previous_period() -> str:
        today = date.today()
        year, month = today.year, today.month - 1
        if month == 0:
            year, month = year - 1, 12
        return f"{year:04d}-{month:02d}"

    async def list_recurring(self) -> list[RecurringExpense]:
        async with self._lock:
            items = self._read_recurring()
        items.sort(key=lambda r: (not r.active, r.vendor.lower()))
        return items

    async def add_recurring(
        self,
        *,
        vendor: str,
        amount_monthly: float,
        category: str = AI_EXPENSE_ACCOUNT,
        billing_day: int = 1,
        paid_from: str = "personal card",
        notes: str = "",
    ) -> RecurringExpense:
        entry = RecurringExpense(
            id=f"rec-{uuid.uuid4().hex[:10]}",
            vendor=vendor.strip()[:120] or "Unnamed subscription",
            amount_monthly=abs(float(amount_monthly or 0)),
            category=(category or AI_EXPENSE_ACCOUNT).strip() or AI_EXPENSE_ACCOUNT,
            billing_day=self._clamp_billing_day(billing_day),
            paid_from=(paid_from or "personal card").strip()[:120],
            active=True,
            notes=(notes or "").strip()[:500],
            created_at=time.time(),
        )
        async with self._lock:
            items = self._read_recurring()
            items.append(entry)
            self._write_recurring(items)
        logger.info("bookkeeper_recurring_add", vendor=entry.vendor, amount=entry.amount_monthly)
        return entry

    async def update_recurring(self, recurring_id: str, **fields: Any) -> Optional[RecurringExpense]:
        async with self._lock:
            items = self._read_recurring()
            for entry in items:
                if entry.id != recurring_id:
                    continue
                if "vendor" in fields and fields["vendor"] is not None:
                    entry.vendor = str(fields["vendor"]).strip()[:120] or entry.vendor
                if "amount_monthly" in fields and fields["amount_monthly"] is not None:
                    entry.amount_monthly = abs(float(fields["amount_monthly"]))
                if "category" in fields and fields["category"]:
                    entry.category = str(fields["category"]).strip()
                if "billing_day" in fields and fields["billing_day"] is not None:
                    entry.billing_day = self._clamp_billing_day(fields["billing_day"])
                if "paid_from" in fields and fields["paid_from"] is not None:
                    entry.paid_from = str(fields["paid_from"]).strip()[:120]
                if "active" in fields and fields["active"] is not None:
                    entry.active = bool(fields["active"])
                if "notes" in fields and fields["notes"] is not None:
                    entry.notes = str(fields["notes"]).strip()[:500]
                self._write_recurring(items)
                return entry
        return None

    async def delete_recurring(self, recurring_id: str) -> bool:
        async with self._lock:
            items = self._read_recurring()
            kept = [r for r in items if r.id != recurring_id]
            if len(kept) == len(items):
                return False
            self._write_recurring(kept)
        return True

    async def generate_recurring_drafts(self, *, period: Optional[str] = None) -> dict[str, Any]:
        """Emit one draft per active recurring expense for `period` (YYYY-MM).

        Idempotent on (recurring_id, period): re-running never double-posts. The
        draft amount is negative (expense convention used by CSV ingestion) so
        accepting it posts a debit against the recurring entry's category.
        """
        period = period or self._current_period()
        async with self._lock:
            recurring = [r for r in self._read_recurring() if r.active]
            drafts = self._read_drafts()
            already = {
                (d.raw.get("recurring_id"), d.raw.get("period"))
                for d in drafts
                if d.source == "recurring"
            }
            created: list[DraftEntry] = []
            for entry in recurring:
                if (entry.id, period) in already:
                    continue
                day = self._clamp_billing_day(entry.billing_day)
                draft = DraftEntry(
                    id=f"draft-{uuid.uuid4().hex[:10]}",
                    date=f"{period}-{day:02d}",
                    description=f"{entry.vendor} — recurring ({period})",
                    amount=-abs(entry.amount_monthly),
                    currency=DEFAULT_CURRENCY,
                    suggested_category=entry.category,
                    source="recurring",
                    raw={
                        "period": period,
                        "recurring_id": entry.id,
                        "vendor": entry.vendor,
                        "paid_from": entry.paid_from,
                    },
                    status="pending",
                    paid_from=entry.paid_from,
                    created_at=time.time(),
                )
                created.append(draft)
            if created:
                drafts.extend(created)
                self._write_drafts(drafts)
        logger.info("bookkeeper_recurring_run", period=period, created=len(created))
        return {
            "period": period,
            "created": [d.to_dict() for d in created],
            "created_count": len(created),
        }

    async def generate_metered_ai_draft(self, *, period: Optional[str] = None) -> dict[str, Any]:
        """Emit ONE draft for the month's metered LLM API spend (llm_usage rollup).

        Complements the flat-rate recurring subscriptions: metered Bifrost/vLLM/
        provider-API cost is already recorded per call in llm_usage, so the
        bookkeeper pulls the month total instead of asking Adam to type it.
        Idempotent on (source="llm_metered", period); skips sub-cent months.
        """
        from app.services.llm_spend_service import get_llm_spend_service

        period = period or self._previous_period()
        spend = await get_llm_spend_service().spend_for_period(period)
        async with self._lock:
            drafts = self._read_drafts()
            if any(d.source == "llm_metered" and d.raw.get("period") == period for d in drafts):
                return {"period": period, "created": None, "reason": "already_generated"}
            if spend < 0.01:
                return {"period": period, "created": None, "reason": "no_metered_spend"}
            draft = DraftEntry(
                id=f"draft-{uuid.uuid4().hex[:10]}",
                date=f"{period}-28",
                description=f"Zero metered LLM APIs — {period}",
                amount=-abs(spend),
                currency=DEFAULT_CURRENCY,
                suggested_category=AI_EXPENSE_ACCOUNT,
                source="llm_metered",
                raw={"period": period, "spend_usd": spend},
                status="pending",
                paid_from="business",
                created_at=time.time(),
            )
            drafts.append(draft)
            self._write_drafts(drafts)
        logger.info("bookkeeper_metered_ai_draft", period=period, spend=spend)
        return {"period": period, "created": draft.to_dict(), "reason": "created"}

    async def recurring_summary(self, *, period: Optional[str] = None) -> dict[str, Any]:
        """Totals + this-period generation status for the AI-spend widget."""
        period = period or self._current_period()
        async with self._lock:
            recurring = self._read_recurring()
            drafts = self._read_drafts()
        active = [r for r in recurring if r.active]
        generated_ids = {
            d.raw.get("recurring_id")
            for d in drafts
            if d.source == "recurring" and d.raw.get("period") == period
        }
        by_category: dict[str, float] = {}
        for r in active:
            by_category[r.category] = by_category.get(r.category, 0.0) + r.amount_monthly
        total_monthly = sum(r.amount_monthly for r in active)

        # Metered API spend (llm_usage) — best effort; a DB hiccup must never
        # break the AI-spend panel, so this block degrades to None.
        metered: Optional[dict[str, Any]] = None
        try:
            from app.services.llm_spend_service import get_llm_spend_service

            spend_svc = get_llm_spend_service()
            months = await spend_svc.monthly_spend(months=12)
            year_prefix = period.split("-")[0]
            metered = {
                "period_cost": next(
                    (m["cost_usd"] for m in months if m["period"] == period), 0.0
                ),
                "ytd_cost": round(
                    sum(m["cost_usd"] for m in months if m["period"].startswith(year_prefix)), 2
                ),
            }
        except Exception as e:
            logger.warning("bookkeeper_metered_summary_failed", error=str(e))

        return {
            "period": period,
            "total_monthly": round(total_monthly, 2),
            "active_count": len(active),
            "by_category": {k: round(v, 2) for k, v in by_category.items()},
            "generated_for_period": sorted(i for i in generated_ids if i),
            "all_generated": bool(active) and all(r.id in generated_ids for r in active),
            "metered": metered,
        }

    # ------------------------------------------------------------------
    # CSV ingestion — draft-only; LLM categorizes; user must accept.
    # ------------------------------------------------------------------
    async def ingest_bank_csv(
        self, *, source: str, csv_text: str, paid_from: str = "business"
    ) -> list[DraftEntry]:
        rows = self._parse_csv(csv_text)
        new_drafts: list[DraftEntry] = []
        for r in rows:
            try:
                amount = float(r.get("amount") or 0)
            except Exception:
                continue
            if amount == 0:
                continue
            d = DraftEntry(
                id=f"draft-{uuid.uuid4().hex[:10]}",
                date=str(r.get("date") or date.today().isoformat()),
                description=str(r.get("description") or "")[:200],
                amount=amount,
                currency=DEFAULT_CURRENCY,
                suggested_category=self._suggest_category(r.get("description") or "", amount),
                source=source,
                raw=r,
                status="pending",
                paid_from=paid_from,
                created_at=time.time(),
            )
            new_drafts.append(d)
        if not new_drafts:
            return []
        async with self._lock:
            existing = self._read_drafts()
            existing.extend(new_drafts)
            self._write_drafts(existing)
        logger.info("bookkeeper_ingest", source=source, count=len(new_drafts))
        return new_drafts

    async def ingest_ofx(
        self, *, source: str, ofx_bytes: bytes, paid_from: str = "business"
    ) -> list[DraftEntry]:
        """Parse an OFX/QFX bank export into pending drafts.

        Dedupes on the bank's FITID, so re-uploading an overlapping statement
        is safe — only unseen transactions become drafts.
        """
        from ofxparse import OfxParser  # MIT — github.com/jseutter/ofxparse

        try:
            ofx = OfxParser.parse(io.BytesIO(ofx_bytes))
        except Exception as e:
            logger.warning("bookkeeper_ofx_parse_failed", error=str(e))
            raise ValueError(f"Could not parse OFX file: {e}") from e

        accounts = list(getattr(ofx, "accounts", None) or [])
        if not accounts and getattr(ofx, "account", None):
            accounts = [ofx.account]

        async with self._lock:
            existing = self._read_drafts()
            seen_fitids = {str(d.raw.get("fitid")) for d in existing if d.raw.get("fitid")}
            new_drafts: list[DraftEntry] = []
            for acct in accounts:
                statement = getattr(acct, "statement", None)
                for txn in getattr(statement, "transactions", None) or []:
                    fitid = str(getattr(txn, "id", "") or "").strip()
                    if fitid and fitid in seen_fitids:
                        continue
                    try:
                        amount = float(txn.amount)
                    except Exception:
                        continue
                    if amount == 0:
                        continue
                    desc = " ".join(
                        part for part in (
                            str(getattr(txn, "payee", "") or "").strip(),
                            str(getattr(txn, "memo", "") or "").strip(),
                        ) if part
                    ) or "OFX transaction"
                    txn_date = getattr(txn, "date", None)
                    d = DraftEntry(
                        id=f"draft-{uuid.uuid4().hex[:10]}",
                        date=txn_date.date().isoformat() if txn_date else date.today().isoformat(),
                        description=desc[:200],
                        amount=amount,
                        currency=DEFAULT_CURRENCY,
                        suggested_category=self._suggest_category(desc, amount),
                        source=source,
                        raw={"fitid": fitid, "txn_type": str(getattr(txn, "type", "") or "")},
                        status="pending",
                        paid_from=paid_from,
                        created_at=time.time(),
                    )
                    new_drafts.append(d)
                    if fitid:
                        seen_fitids.add(fitid)
            if new_drafts:
                existing.extend(new_drafts)
                self._write_drafts(existing)
        logger.info("bookkeeper_ofx_ingest", source=source, count=len(new_drafts))
        return new_drafts

    async def ingest_receipt(
        self, *, filename: str, content: bytes, paid_from: str = "personal"
    ) -> DraftEntry:
        """Receipt/invoice file (PDF or photo) → one pending draft.

        Pipeline: invoice2data template extraction → raw-text extraction
        (pdftotext for PDFs, tesseract for images) + LLM structured extract
        (TaxHacker-style fallback). Raises ValueError when nothing works.
        """
        import tempfile

        suffix = Path(filename or "receipt").suffix.lower() or ".pdf"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)
        try:
            extracted = await asyncio.to_thread(self._invoice2data_extract, tmp_path)
            if not extracted:
                text = await self._extract_receipt_text(tmp_path, suffix)
                if not text.strip():
                    raise ValueError(
                        "Could not read any text from the receipt (template match and OCR both failed)."
                    )
                extracted = await self._llm_extract_receipt(text)
            vendor = str(extracted.get("vendor") or extracted.get("issuer") or "Receipt").strip()
            amount = abs(float(extracted.get("amount") or 0.0))
            if amount <= 0:
                raise ValueError(f"No total amount found on the receipt ({vendor}).")
            receipt_date = str(extracted.get("date") or date.today().isoformat())[:10]
            d = DraftEntry(
                id=f"draft-{uuid.uuid4().hex[:10]}",
                date=receipt_date,
                description=f"{vendor} — receipt ({filename})"[:200],
                amount=-amount,
                currency=DEFAULT_CURRENCY,
                suggested_category=self._suggest_category(vendor, -amount),
                source="receipt_ocr",
                raw={"filename": filename, "extractor": extracted.get("extractor", "unknown")},
                status="pending",
                paid_from=paid_from,
                created_at=time.time(),
            )
            async with self._lock:
                drafts = self._read_drafts()
                drafts.append(d)
                self._write_drafts(drafts)
            logger.info("bookkeeper_receipt_ingest", vendor=vendor, amount=amount)
            return d
        finally:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass

    @staticmethod
    def _invoice2data_extract(path: Path) -> Optional[dict[str, Any]]:
        try:
            from invoice2data import extract_data  # MIT — github.com/invoice-x/invoice2data

            result = extract_data(str(path))
            if not result:
                return None
            raw_date = result.get("date")
            return {
                "vendor": result.get("issuer"),
                "amount": result.get("amount"),
                "date": raw_date.date().isoformat() if hasattr(raw_date, "date") else raw_date,
                "extractor": "invoice2data",
            }
        except Exception as e:
            logger.debug("bookkeeper_invoice2data_miss", error=str(e))
            return None

    @staticmethod
    async def _extract_receipt_text(path: Path, suffix: str) -> str:
        """pdftotext (poppler) for PDFs; tesseract for photos. Best effort."""
        import subprocess

        def _run(cmd: list[str]) -> str:
            try:
                out = subprocess.run(cmd, capture_output=True, timeout=60)
                return out.stdout.decode("utf-8", errors="replace") if out.returncode == 0 else ""
            except Exception:
                return ""

        if suffix == ".pdf":
            return await asyncio.to_thread(_run, ["pdftotext", "-layout", str(path), "-"])
        return await asyncio.to_thread(_run, ["tesseract", str(path), "stdout"])

    @staticmethod
    async def _llm_extract_receipt(text: str) -> dict[str, Any]:
        """LLM fallback for unmatched receipt formats (TaxHacker-style prompt)."""
        from app.infrastructure.unified_llm_client import get_unified_llm_client

        result = await get_unified_llm_client().structured_chat(
            prompt=(
                "Extract the merchant/vendor name, total amount paid (USD number), and purchase "
                "date (YYYY-MM-DD) from this receipt text. Use the FINAL total including tax.\n\n"
                f"{text[:6000]}"
            ),
            output_schema={"vendor": "string", "amount": 0.0, "date": "YYYY-MM-DD"},
            task_type="bookkeeper_receipt",
            max_tokens=256,
        )
        if not isinstance(result, dict):
            raise ValueError("Receipt LLM extraction returned no structured data.")
        result["extractor"] = "llm"
        return result

    def _parse_csv(self, csv_text: str) -> list[dict[str, Any]]:
        try:
            reader = csv.DictReader(io.StringIO(csv_text))
            rows = []
            for raw in reader:
                norm = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
                amount = norm.get("amount") or norm.get("debit") or norm.get("credit") or "0"
                amount = amount.replace("$", "").replace(",", "")
                rows.append({
                    "date": norm.get("date") or norm.get("posted") or norm.get("transaction date"),
                    "description": norm.get("description") or norm.get("memo") or norm.get("payee"),
                    "amount": amount,
                    **norm,
                })
            return rows
        except Exception as e:
            logger.warning("bookkeeper_csv_parse_failed", error=str(e))
            return []

    def _suggest_category(self, description: str, amount: float) -> str:
        # Persisted rules (incl. learned payee mappings) beat the keyword table.
        rule = self._match_rule(description)
        if rule:
            return rule.category
        d = (description or "").lower()
        if amount > 0:
            if any(k in d for k in ("stripe", "invoice", "client", "subscription", "saas")):
                return "Income:Software:Sales"
            if any(k in d for k in ("consulting", "contract")):
                return "Income:Consulting"
            return "Income:Software:Sales"
        if any(k in d for k in ("aws", "gcp", "azure", "vercel", "fly.io", "render")):
            return "Expenses:Cloud"
        if any(k in d for k in ("github", "openai", "anthropic", "stripe fee", "saas", "subscription")):
            return "Expenses:Software"
        if any(k in d for k in ("staples", "office", "supplies")):
            return "Expenses:Office"
        if any(k in d for k in ("airline", "delta", "uber", "hotel", "marriott", "lyft")):
            return "Expenses:Travel"
        if any(k in d for k in ("doordash", "ubereats", "restaurant", "coffee", "starbucks", "lunch", "dinner")):
            return "Expenses:Meals"
        if any(k in d for k in ("law", "legal", "attorney", "sunbiz", "delaware")):
            return "Expenses:Legal"
        if any(k in d for k in ("nvidia", "amazon", "best buy", "newegg")):
            return "Expenses:Hardware"
        return "Expenses:Office"

    async def list_drafts(self, *, status: Optional[str] = None) -> list[DraftEntry]:
        async with self._lock:
            drafts = self._read_drafts()
        if status:
            drafts = [d for d in drafts if d.status == status]
        drafts.sort(key=lambda d: d.created_at, reverse=True)
        return drafts

    async def accept_draft(self, draft_id: str, *, category: Optional[str] = None) -> Optional[DraftEntry]:
        async with self._lock:
            drafts = self._read_drafts()
            for d in drafts:
                if d.id != draft_id:
                    continue
                if d.status != "pending":
                    return d
                cat = category or d.suggested_category
                # Category learning (Actual Budget's learn_categories): an
                # override writes a payee rule; a plain accept is a confidence
                # signal for whichever rule made the suggestion.
                if category and category != d.suggested_category:
                    self._learn_rule(d.description, category)
                else:
                    self._bump_rule_hit(d.description)
                self._ensure_account_open(cat)
                self._append_journal_entry(d, cat)
                d.status = "accepted"
                d.suggested_category = cat
                self._write_drafts(drafts)
                return d
        return None

    async def reject_draft(self, draft_id: str) -> Optional[DraftEntry]:
        async with self._lock:
            drafts = self._read_drafts()
            for d in drafts:
                if d.id == draft_id:
                    d.status = "rejected"
                    self._write_drafts(drafts)
                    return d
        return None

    @staticmethod
    def _funding_account(paid_from: str | None) -> str:
        """Balancing account for a draft: owner equity when paid personally.

        Recurring-registry values are freeform ("personal card", "Amex personal",
        "business checking"), so match on the word, not equality.
        """
        if "personal" in (paid_from or "").lower():
            return EQUITY_CONTRIB_ACCOUNT
        return BANK_ACCOUNT

    def _append_journal_entry(self, d: DraftEntry, category: str) -> None:
        # Recurring drafts carry the registry's paid_from in raw (including
        # drafts persisted before DraftEntry grew the field); other sources set
        # the dataclass field directly.
        side = self._funding_account(str(d.raw.get("paid_from") or d.paid_from))
        self._ensure_account_open(side)
        amount_signed = d.amount
        # Beancount convention: positive on the income side, negative on
        # the asset side decreases bank; we just emit a balanced txn.
        safe_desc = d.description.replace('"', "'")
        block = (
            f'\n{d.date} * "{safe_desc}"\n'
            f"  {category}                {amount_signed:.2f} {d.currency}\n"
            f"  {side}                   {-amount_signed:.2f} {d.currency}\n"
        )
        try:
            with open(LEDGER_PATH, "a", encoding="utf-8") as f:
                f.write(block)
        except Exception as e:
            logger.warning("bookkeeper_append_failed", error=str(e))

    async def post_owner_contribution(self, *, date_str: str, description: str, amount: float) -> None:
        """Record personal property entering the LLC: equipment up, owner equity up.

        Posts Assets:Equipment (NOT Expenses:Hardware) so the tax summary's
        asset-register line stays the single source for the deduction — this
        entry only keeps the balance sheet honest.
        """
        amount = abs(float(amount or 0.0))
        if amount <= 0:
            return
        async with self._lock:
            self._ensure_account_open(EQUIPMENT_ACCOUNT)
            self._ensure_account_open(EQUITY_CONTRIB_ACCOUNT)
            safe_desc = (description or "Owner capital contribution").replace('"', "'")
            block = (
                f'\n{date_str} * "{safe_desc}"\n'
                f"  {EQUIPMENT_ACCOUNT}                {amount:.2f} {DEFAULT_CURRENCY}\n"
                f"  {EQUITY_CONTRIB_ACCOUNT}                   {-amount:.2f} {DEFAULT_CURRENCY}\n"
            )
            try:
                with open(LEDGER_PATH, "a", encoding="utf-8") as f:
                    f.write(block)
            except Exception as e:
                logger.warning("bookkeeper_contribution_append_failed", error=str(e))
        logger.info("bookkeeper_owner_contribution", description=description, amount=amount)

    # ------------------------------------------------------------------
    # Snapshot — feeds the daily brief + dashboard tile.
    # ------------------------------------------------------------------
    async def snapshot(self, *, period: str = "YTD") -> LedgerSnapshot:
        backend = self._backend_name()
        revenue = 0.0
        expenses = 0.0
        by_category: dict[str, float] = {}
        last_entry_at: Optional[str] = None

        if backend == "beancount":
            try:
                from beancount import loader  # type: ignore
                from beancount.core import data as bd  # type: ignore
                entries, _, _ = loader.load_file(str(LEDGER_PATH))
                year_start = date(date.today().year, 1, 1)
                for entry in entries:
                    if not isinstance(entry, bd.Transaction):
                        continue
                    if period == "YTD" and entry.date < year_start:
                        continue
                    last_entry_at = entry.date.isoformat()
                    for posting in entry.postings:
                        amt = float(posting.units.number) if posting.units else 0.0
                        acct = posting.account
                        if acct.startswith("Income:"):
                            revenue += -amt  # income is credited (negative on the income side in BC convention)
                            by_category[acct] = by_category.get(acct, 0.0) + (-amt)
                        elif acct.startswith("Expenses:"):
                            expenses += amt
                            by_category[acct] = by_category.get(acct, 0.0) + amt
            except Exception as e:
                logger.warning("bookkeeper_beancount_snapshot_failed", error=str(e))
                backend = "stub"

        if backend != "beancount":
            # Stub: derive from accepted drafts only — keeps the surface
            # alive without a real ledger parse.
            async with self._lock:
                drafts = self._read_drafts()
            for d in drafts:
                if d.status != "accepted":
                    continue
                last_entry_at = d.date
                if d.suggested_category.startswith("Income:"):
                    revenue += d.amount
                    by_category[d.suggested_category] = by_category.get(d.suggested_category, 0.0) + d.amount
                elif d.suggested_category.startswith("Expenses:"):
                    expenses += abs(d.amount)
                    by_category[d.suggested_category] = by_category.get(d.suggested_category, 0.0) + abs(d.amount)

        net = revenue - expenses
        est_tax = max(net * QUARTERLY_TAX_RATE, 0.0)
        pending = sum(1 for d in await self.list_drafts(status="pending"))

        return LedgerSnapshot(
            entity=ENTITY_NAME,
            period=period,
            revenue=revenue,
            expenses=expenses,
            net=net,
            by_category=by_category,
            estimated_tax=est_tax,
            last_entry_at=last_entry_at,
            pending_drafts=pending,
            backend=backend,
        )

    # ------------------------------------------------------------------
    # Voice — short prose answers for the supervisor adapter.
    # ------------------------------------------------------------------
    async def answer_voice_question(self, question: str) -> str:
        q = (question or "").lower()
        snap = await self.snapshot()
        if "tax" in q:
            return (
                f"{snap.entity} {snap.period} net is "
                f"{snap.net:,.0f} dollars; estimated quarterly tax at "
                f"{int(QUARTERLY_TAX_RATE*100)} percent is about "
                f"{snap.estimated_tax:,.0f} dollars."
            )
        if "revenue" in q or "income" in q or "sales" in q:
            return f"{snap.entity} {snap.period} revenue is {snap.revenue:,.0f} dollars."
        if "expense" in q or "spend" in q or "burn" in q:
            return f"{snap.entity} {snap.period} expenses are {snap.expenses:,.0f} dollars."
        if "draft" in q or "pending" in q:
            return f"You have {snap.pending_drafts} pending bookkeeping drafts to review."
        return (
            f"{snap.entity} {snap.period}: revenue {snap.revenue:,.0f}, "
            f"expenses {snap.expenses:,.0f}, net {snap.net:,.0f} dollars. "
            f"{snap.pending_drafts} pending drafts."
        )


@lru_cache(maxsize=1)
def get_bookkeeper_service() -> BookkeeperService:
    return BookkeeperService()
