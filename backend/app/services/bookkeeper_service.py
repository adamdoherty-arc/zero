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
ENTITY_NAME = os.getenv("ADA_AI_LEGAL_NAME", "ADA AI LLC")
DEFAULT_CURRENCY = os.getenv("ADA_AI_CURRENCY", "USD")
QUARTERLY_TAX_RATE = float(os.getenv("ADA_AI_TAX_RATE_EST", "0.22"))


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
            f"1970-01-01 open Expenses:Cloud                {DEFAULT_CURRENCY}\n"
            f"1970-01-01 open Expenses:Hardware             {DEFAULT_CURRENCY}\n"
            f"1970-01-01 open Expenses:Office               {DEFAULT_CURRENCY}\n"
            f"1970-01-01 open Expenses:Travel               {DEFAULT_CURRENCY}\n"
            f"1970-01-01 open Expenses:Meals                {DEFAULT_CURRENCY}\n"
            f"1970-01-01 open Expenses:Legal                {DEFAULT_CURRENCY}\n"
            f"1970-01-01 open Expenses:Tax:Federal          {DEFAULT_CURRENCY}\n"
            f"1970-01-01 open Expenses:Tax:State            {DEFAULT_CURRENCY}\n"
            f"1970-01-01 open Equity:Owner:Adam             {DEFAULT_CURRENCY}\n"
        )
        LEDGER_PATH.write_text(opening, encoding="utf-8")

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
    # CSV ingestion — draft-only; LLM categorizes; user must accept.
    # ------------------------------------------------------------------
    async def ingest_bank_csv(
        self, *, source: str, csv_text: str
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

    def _append_journal_entry(self, d: DraftEntry, category: str) -> None:
        side = "Assets:Bank:Mercury"
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
