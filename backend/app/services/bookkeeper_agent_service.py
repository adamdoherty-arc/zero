"""AI bookkeeper agent for ADA AI LLC.

The tax tracker (Feature-106) gives Adam every worksheet he needs — this agent
makes sure they actually get filled and stay current. Three jobs:

1. **Onboarding interview** — converts empty-tracker gaps into typed
   ``CompanyAgentQuestionModel`` check-ins (answered in /company/inbox). Each
   question carries an ``apply`` spec in its context; when Adam answers, the
   operator's answer hook calls :meth:`apply_answer`, which parses the answer
   and writes it to the right store (company_facts worksheet, recurring
   registry, or asset register) — the tracker fills itself.
2. **Daily gap sweep** — auto-fixes what is safe (generating the month's
   recurring + metered drafts is draft-only) and nags about what needs Adam
   (pending drafts aging, stale books, 1040-ES deadlines) with per-check
   cooldowns so it never spams.
3. **Books health** (phase G) — a deterministic 0-100 grade reported to
   Legion's loop registry.

Question workflows adapted from Receiptor-AI/bookkeeping-skills (MIT-style
skill prompts for month-end close and bank reconciliation). Delivery is
inbox-only by design (user decision 2026-07-13): no Discord/email/toast push.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import structlog
from sqlalchemy import select

from app.db.models import CompanyAgentQuestionModel
from app.infrastructure.database import get_session

logger = structlog.get_logger(__name__)

# State lives beside the ledger in the workspace volume so it survives rebuilds.
STATE_PATH = Path("workspace") / "ada_ai" / "bookkeeper_agent_state.json"
# Self-improvement knowledge (ADA platform-auditor pattern): evolvable weights,
# pruned audit history, and per-question ask/answer/dismiss stats.
KNOWLEDGE_DIR = Path("workspace") / "ada_ai" / "bookkeeper_knowledge"

DEFAULT_DIMENSION_WEIGHTS = {
    "completeness": 0.35,
    "freshness": 0.20,
    "reconciliation": 0.20,
    "deduction_capture": 0.25,
}
AUDIT_HISTORY_LIMIT = 20

SOURCE_ONBOARDING = "bookkeeper_onboarding"
SOURCE_AGENT = "bookkeeper_agent"

# Per-check nag cooldowns.
COOLDOWN_DEFAULT = timedelta(hours=72)
COOLDOWN_CRITICAL = timedelta(hours=24)
# A check dismissed this many times stops firing entirely.
DISMISS_SUPPRESS_COUNT = 2

_SKIP_ANSWERS = {"skip", "n/a", "na", "none", "not applicable", "later", "-"}

_MONEY_RE = re.compile(r"\$?\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)")
_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
# "Claude Max $200" / "ChatGPT - 20" / "Cursor: $20/mo"
_SUBSCRIPTION_RE = re.compile(
    r"([A-Za-z][\w .+&'/-]{1,60}?)\s*[-–—:@]?\s*\$?\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)(?:\s*/\s*mo(?:nth)?)?",
)

# 1040-ES quarterly due dates (month, day); Jan 15 belongs to the prior tax year.
_ES_DATES = ((1, 15), (4, 15), (6, 15), (9, 15))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_number(raw: str) -> Optional[float]:
    m = _MONEY_RE.search(raw or "")
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Onboarding interview — one spec per gap the tracker needs filled.
# ---------------------------------------------------------------------------
# apply.kind ∈ company_fact | recurring_list | asset_contribution | asset_purchase
ONBOARDING_SPECS: list[dict[str, Any]] = [
    {
        "bk_key": "home_office.exclusive_sqft",
        "question": "How many square feet of your home are used EXCLUSIVELY for the business (your office area)?",
        "answer_type": "number",
        "why_needed": "Drives both home-office methods: simplified pays $5/sqft (capped at 300), actual uses the sqft ratio.",
        "apply": {"kind": "company_fact", "key": "home_office.exclusive_sqft", "label": "Home office exclusive sqft", "parse": "number"},
    },
    {
        "bk_key": "home_office.total_sqft",
        "question": "What is the total square footage of your home?",
        "answer_type": "number",
        "why_needed": "office sqft ÷ total sqft = the business-use % applied to home costs under the actual method.",
        "apply": {"kind": "company_fact", "key": "home_office.total_sqft", "label": "Total home square feet", "parse": "number"},
    },
    {
        "bk_key": "home_office.rent_or_mortgage_monthly",
        "question": "What do you pay monthly in rent (or mortgage interest, if you own)?",
        "answer_type": "currency",
        "why_needed": "The largest indirect home cost the actual method allocates to the office.",
        "apply": {"kind": "company_fact", "key": "home_office.rent_or_mortgage_monthly", "label": "Monthly rent or mortgage interest", "parse": "number"},
    },
    {
        "bk_key": "home_office.electricity_monthly",
        "question": "What is your average monthly ELECTRICITY bill?",
        "answer_type": "currency",
        "why_needed": "Electricity is allocated to the home office by business-use % under the actual method.",
        "apply": {"kind": "company_fact", "key": "home_office.electricity_monthly", "label": "Monthly electricity", "parse": "number"},
    },
    {
        "bk_key": "home_office.utilities_monthly",
        "question": "What do other utilities run monthly (water, gas, trash — electricity is asked separately)?",
        "answer_type": "currency",
        "why_needed": "Utilities are indirect home costs the actual method allocates by business-use %.",
        "apply": {"kind": "company_fact", "key": "home_office.utilities_monthly", "label": "Monthly utilities (water/gas/trash)", "parse": "number"},
    },
    {
        "bk_key": "home_office.insurance_monthly",
        "question": "What is your monthly renters/homeowners insurance premium? (answer 'skip' if none)",
        "answer_type": "currency",
        "why_needed": "Home insurance is another indirect cost the actual method can allocate.",
        "apply": {"kind": "company_fact", "key": "home_office.insurance_monthly", "label": "Monthly home insurance", "parse": "number"},
    },
    {
        "bk_key": "home_office.internet_monthly",
        "question": "What is your monthly INTERNET bill?",
        "answer_type": "currency",
        "why_needed": "Business internet is deductible under either home-office method (standalone line under simplified).",
        "apply": {"kind": "company_fact", "key": "home_office.internet_monthly", "label": "Monthly internet", "parse": "number"},
    },
    {
        "bk_key": "home_office.internet_business_pct",
        "question": "Roughly what % of your internet use is business?",
        "answer_type": "percent",
        "options": ["50", "70", "90", "100"],
        "why_needed": "Only the business share of internet is deductible.",
        "apply": {"kind": "company_fact", "key": "home_office.internet_business_pct", "label": "Internet business-use %", "parse": "number"},
    },
    {
        "bk_key": "cell_phone.monthly",
        "question": "What is your monthly CELLPHONE bill?",
        "answer_type": "currency",
        "why_needed": "The business share of your cellphone is deductible (Schedule C line 25).",
        "apply": {"kind": "company_fact", "key": "cell_phone.monthly", "label": "Monthly cell phone bill", "parse": "number"},
    },
    {
        "bk_key": "cell_phone.business_pct",
        "question": "Roughly what % of your cellphone use is business?",
        "answer_type": "percent",
        "options": ["50", "70", "90", "100"],
        "why_needed": "Only the business share of the bill is deductible.",
        "apply": {"kind": "company_fact", "key": "cell_phone.business_pct", "label": "Cell phone business-use %", "parse": "number"},
    },
    {
        "bk_key": "subscriptions.ai",
        "question": (
            "List every AI/software subscription the business pays monthly, with amounts — "
            "e.g. 'Claude Max $200, ChatGPT $20, Cursor $20'. Include anything you pay from "
            "a personal card; it still counts."
        ),
        "answer_type": "text",
        "why_needed": "Each becomes a tracked recurring expense that auto-drafts into the books every month — your monthly AI spend.",
        "apply": {"kind": "recurring_list"},
    },
    {
        "bk_key": "asset.computer_contribution",
        "question": (
            "Your computer entering the LLC: what is it worth today (FMV), what did you originally pay, "
            "and since when has it been used for the business? Format: FMV, original cost, date — "
            "e.g. '1800, 3200, 2026-05-01'."
        ),
        "answer_type": "text",
        "why_needed": (
            "Registers the computer as an owner capital contribution: deduction basis is the LESSER of FMV "
            "or original cost, and an owner-equity entry posts automatically."
        ),
        "apply": {"kind": "asset_contribution", "name": "Computer (owner contribution)", "asset_type": "computer"},
    },
    {
        "bk_key": "asset.monitor_purchase",
        "question": (
            "The monitor you bought for the business: how much did it cost and when did you buy it? "
            "Format: cost, date — e.g. '350, 2026-06-15'."
        ),
        "answer_type": "text",
        "why_needed": "Registers the monitor in the asset register (de-minimis full expensing under $2,500).",
        "apply": {"kind": "asset_purchase", "name": "Monitor", "asset_type": "monitor"},
    },
]


class BookkeeperAgentService:
    """Onboards, populates, and nags — the bookkeeper who never forgets."""

    # ------------------------------------------------------------------
    # State (cooldowns, last report) — plain JSON in the workspace volume.
    # ------------------------------------------------------------------
    def _read_state(self) -> dict[str, Any]:
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _write_state(self, state: dict[str, Any]) -> None:
        try:
            STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
        except Exception as e:
            logger.warning("bookkeeper_agent_state_write_failed", error=str(e))

    # ------------------------------------------------------------------
    # Gap detection — which onboarding questions are still needed?
    # ------------------------------------------------------------------
    async def _pending_onboarding_specs(self) -> list[dict[str, Any]]:
        from app.services.asset_service import get_asset_service
        from app.services.bookkeeper_service import get_bookkeeper_service
        from app.services.company_facts_service import get_company_facts_service

        facts = get_company_facts_service()
        ho = await facts.home_office_summary()
        ho_inputs = {k: v for k, v in (ho.get("inputs") or {}).items() if str(v).strip()}
        deds = await facts.deductions_summary()
        recurring = await get_bookkeeper_service().list_recurring()
        assets = await get_asset_service().list_assets(year=date.today().year)

        has_contributed = any(a.acquisition_type == "contributed" for a in assets)
        has_monitor = any("monitor" in (a.name or "").lower() for a in assets)

        def needed(spec: dict[str, Any]) -> bool:
            key = spec["bk_key"]
            if key.startswith("home_office."):
                return key.split(".", 1)[1] not in ho_inputs
            if key == "cell_phone.monthly":
                return deds["cell_phone"].get("monthly") is None
            if key == "cell_phone.business_pct":
                return deds["cell_phone"].get("business_pct") is None
            if key == "subscriptions.ai":
                return not recurring
            if key == "asset.computer_contribution":
                return not has_contributed
            if key == "asset.monitor_purchase":
                return not has_monitor
            return False

        return [s for s in ONBOARDING_SPECS if needed(s)]

    async def _existing_bk_keys(self) -> set[str]:
        """bk_keys of every bookkeeper question ever asked (any status)."""
        async with get_session() as session:
            rows = (
                await session.execute(
                    select(CompanyAgentQuestionModel.context).where(
                        CompanyAgentQuestionModel.source.in_([SOURCE_ONBOARDING, SOURCE_AGENT])
                    )
                )
            ).scalars().all()
        return {str((ctx or {}).get("bk_key")) for ctx in rows if (ctx or {}).get("bk_key")}

    async def _dismiss_counts(self) -> dict[str, int]:
        async with get_session() as session:
            rows = (
                await session.execute(
                    select(CompanyAgentQuestionModel.context).where(
                        CompanyAgentQuestionModel.source.in_([SOURCE_ONBOARDING, SOURCE_AGENT]),
                        CompanyAgentQuestionModel.status == "dismissed",
                    )
                )
            ).scalars().all()
        counts: dict[str, int] = {}
        for ctx in rows:
            key = str((ctx or {}).get("bk_key") or "")
            # nag keys carry a period/date suffix — count by check kind
            kind = key.rsplit(".", 1)[0] if key.startswith("nag.") else key
            if kind:
                counts[kind] = counts.get(kind, 0) + 1
        return counts

    async def _create_question(
        self,
        *,
        bk_key: str,
        question: str,
        why_needed: str,
        source: str,
        answer_type: str = "text",
        options: Optional[list[str]] = None,
        priority: str = "high",
        apply: Optional[dict[str, Any]] = None,
        extra_context: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        context: dict[str, Any] = {
            "bk_key": bk_key,
            "why_needed": why_needed,
            "blocks_progress": False,
            "decision_type": "bookkeeping",
            **(extra_context or {}),
        }
        if apply:
            context["apply"] = apply
        row = CompanyAgentQuestionModel(
            id=f"caq-{uuid.uuid4().hex[:12]}",
            question=question,
            context=context,
            answer_type=answer_type,
            options=options or [],
            priority=priority,
            status="open",
            asked_by_agent="bookkeeper",
            source=source,
        )
        async with get_session() as session:
            session.add(row)
            await session.flush()
            from app.services.company_operator_service import _serialize_question

            serialized = _serialize_question(row)
        self.record_question_event(bk_key, "asked")
        logger.info("bookkeeper_question_created", bk_key=bk_key, source=source)
        return serialized

    # ------------------------------------------------------------------
    # Onboarding
    # ------------------------------------------------------------------
    async def seed_onboarding_questions(self) -> dict[str, Any]:
        """Ask (once) for every datum the empty tracker still needs. Idempotent."""
        pending = await self._pending_onboarding_specs()
        asked = await self._existing_bk_keys()
        created: list[dict[str, Any]] = []
        for spec in pending:
            if spec["bk_key"] in asked:
                continue
            created.append(
                await self._create_question(
                    bk_key=spec["bk_key"],
                    question=spec["question"],
                    why_needed=spec["why_needed"],
                    source=SOURCE_ONBOARDING,
                    answer_type=spec.get("answer_type", "text"),
                    options=spec.get("options"),
                    priority="high",
                    apply=spec.get("apply"),
                )
            )
        return {
            "created_count": len(created),
            "pending_gaps": len(pending),
            "created": [{"id": q["id"], "bk_key": q["context"]["bk_key"]} for q in created],
        }

    # ------------------------------------------------------------------
    # Answer application — the hook target from answer_question().
    # ------------------------------------------------------------------
    async def apply_answer(self, serialized_question: dict[str, Any]) -> dict[str, Any]:
        context = serialized_question.get("context") or {}
        apply = context.get("apply") or {}
        answer = str(serialized_question.get("answer") or "").strip()
        answered_by = str(serialized_question.get("answered_by") or "user")
        bk_key = str(context.get("bk_key") or "")
        kind = str(apply.get("kind") or "")
        question_id = str(serialized_question.get("id") or "")

        if not kind:
            return {"applied": False, "reason": "no_apply_spec"}
        if answer.lower() in _SKIP_ANSWERS:
            logger.info("bookkeeper_answer_skipped", bk_key=bk_key)
            return {"applied": False, "reason": "skipped_by_user"}

        try:
            if kind == "company_fact":
                result = await self._apply_company_fact(apply, answer, answered_by)
            elif kind == "recurring_list":
                result = await self._apply_recurring_list(answer)
            elif kind == "asset_contribution":
                result = await self._apply_asset_contribution(apply, answer, answered_by)
            elif kind == "asset_purchase":
                result = await self._apply_asset_purchase(apply, answer, answered_by)
            else:
                return {"applied": False, "reason": f"unknown_kind:{kind}"}
        except _ParseError as e:
            await self._reopen_with_hint(question_id, str(e))
            return {"applied": False, "reason": "parse_error", "hint": str(e)}
        except Exception as e:
            logger.warning("bookkeeper_apply_failed", bk_key=bk_key, error=str(e))
            await self._reopen_with_hint(
                question_id, f"Could not apply the answer ({e}). Please try again."
            )
            return {"applied": False, "reason": "error", "error": str(e)}

        self.record_question_event(bk_key, "answered")
        logger.info("bookkeeper_answer_applied", bk_key=bk_key, kind=kind, detail=result)
        return {"applied": True, "kind": kind, "detail": result}

    async def _reopen_with_hint(self, question_id: str, hint: str) -> None:
        if not question_id:
            return
        async with get_session() as session:
            row = await session.get(CompanyAgentQuestionModel, question_id)
            if not row:
                return
            context = dict(row.context or {})
            context["parse_error"] = hint
            row.context = context
            row.status = "open"
            row.answer = None
            row.answered_at = None
            row.updated_at = _now()
            await session.flush()

    async def _apply_company_fact(
        self, apply: dict[str, Any], answer: str, answered_by: str
    ) -> dict[str, Any]:
        from app.models.company_facts import CompanyFactCreate
        from app.services.company_facts_service import get_company_facts_service

        if apply.get("parse") == "number":
            value = _parse_number(answer)
            if value is None:
                raise _ParseError("I need a number — e.g. '350' or '$1,200'.")
            value_str = f"{value:g}"
        else:
            value_str = answer
        fact = await get_company_facts_service().upsert_fact(
            CompanyFactCreate(
                key=str(apply["key"]),
                label=str(apply.get("label") or apply["key"]),
                value=value_str,
                domain="finance",
            ),
            created_by=answered_by,
            source=SOURCE_ONBOARDING,
        )
        return {"fact_key": fact.key, "value": value_str}

    async def _apply_recurring_list(self, answer: str) -> dict[str, Any]:
        from app.services.bookkeeper_service import get_bookkeeper_service

        pairs = self._parse_subscriptions(answer)
        if not pairs:
            pairs = await self._llm_parse_subscriptions(answer)
        if not pairs:
            raise _ParseError(
                "I couldn't read any 'vendor amount' pairs — try e.g. 'Claude Max $200, ChatGPT $20'."
            )
        svc = get_bookkeeper_service()
        existing = {r.vendor.strip().lower() for r in await svc.list_recurring()}
        added = []
        for vendor, amount in pairs:
            if vendor.strip().lower() in existing:
                continue
            entry = await svc.add_recurring(
                vendor=vendor, amount_monthly=amount, paid_from="personal card",
                notes="Added by bookkeeper onboarding",
            )
            added.append({"vendor": entry.vendor, "amount_monthly": entry.amount_monthly})
        return {"added": added, "parsed_count": len(pairs)}

    @staticmethod
    def _parse_subscriptions(answer: str) -> list[tuple[str, float]]:
        pairs: list[tuple[str, float]] = []
        for segment in re.split(r"[,\n;]+", answer):
            segment = segment.strip()
            if not segment:
                continue
            m = _SUBSCRIPTION_RE.match(segment)
            if not m:
                continue
            vendor = m.group(1).strip(" -–—:@")
            try:
                amount = float(m.group(2).replace(",", ""))
            except Exception:
                continue
            if vendor and amount > 0:
                pairs.append((vendor, amount))
        return pairs

    async def _llm_parse_subscriptions(self, answer: str) -> list[tuple[str, float]]:
        """Cheap local-model fallback when the regex finds nothing."""
        try:
            from app.infrastructure.unified_llm_client import get_unified_llm_client

            result = await get_unified_llm_client().structured_chat(
                prompt=(
                    "Extract the software subscriptions and their monthly USD amounts from this text. "
                    f"Text: {answer!r}"
                ),
                output_schema={"subscriptions": [{"vendor": "string", "amount_monthly": 0.0}]},
                task_type="bookkeeper_agent",
                max_tokens=512,
            )
            items = result.get("subscriptions") if isinstance(result, dict) else None
            pairs = []
            for item in items or []:
                vendor = str(item.get("vendor") or "").strip()
                amount = float(item.get("amount_monthly") or 0)
                if vendor and amount > 0:
                    pairs.append((vendor, amount))
            return pairs
        except Exception as e:
            logger.warning("bookkeeper_llm_parse_failed", error=str(e))
            return []

    @staticmethod
    def _parse_amounts_and_date(answer: str) -> tuple[list[float], Optional[str]]:
        date_match = _DATE_RE.search(answer)
        found_date = date_match.group(1) if date_match else None
        # Strip the date before scanning for money so '2026' isn't read as $2,026.
        scrubbed = _DATE_RE.sub("", answer)
        amounts = [float(m.replace(",", "")) for m in _MONEY_RE.findall(scrubbed)]
        return amounts, found_date

    async def _apply_asset_contribution(
        self, apply: dict[str, Any], answer: str, answered_by: str
    ) -> dict[str, Any]:
        from app.models.business_asset import AssetTransferItem
        from app.services.asset_service import get_asset_service

        amounts, found_date = self._parse_amounts_and_date(answer)
        if not amounts:
            raise _ParseError("I need at least the FMV — e.g. '1800, 3200, 2026-05-01'.")
        fmv = amounts[0]
        original = amounts[1] if len(amounts) > 1 else None
        placed = date.fromisoformat(found_date) if found_date else date.today()
        assets = await get_asset_service().record_contribution_batch(
            [
                AssetTransferItem(
                    name=str(apply.get("name") or "Contributed equipment"),
                    asset_type=apply.get("asset_type"),
                    fmv=fmv,
                    original_cost=original,
                    placed_in_service=placed,
                    notes="Registered by bookkeeper onboarding",
                )
            ],
            actor=answered_by,
        )
        a = assets[0]
        return {"asset_id": a.id, "fmv": fmv, "original_cost": original, "deduction": a.current_year_deduction}

    async def _apply_asset_purchase(
        self, apply: dict[str, Any], answer: str, answered_by: str
    ) -> dict[str, Any]:
        from app.models.business_asset import BusinessAssetCreate
        from app.services.asset_service import DE_MINIMIS_CEILING, get_asset_service

        amounts, found_date = self._parse_amounts_and_date(answer)
        if not amounts:
            raise _ParseError("I need the cost — e.g. '350, 2026-06-15'.")
        cost = amounts[0]
        placed = date.fromisoformat(found_date) if found_date else date.today()
        asset = await get_asset_service().create_asset(
            BusinessAssetCreate(
                name=str(apply.get("name") or "Equipment"),
                asset_type=apply.get("asset_type"),
                cost=cost,
                placed_in_service=placed,
                method="de_minimis" if cost < DE_MINIMIS_CEILING else "section_179",
                notes="Registered by bookkeeper onboarding",
            ),
            year=placed.year,
            created_by=answered_by,
        )
        return {"asset_id": asset.id, "cost": cost, "deduction": asset.current_year_deduction}

    # ------------------------------------------------------------------
    # Daily sweep — auto-fix what's safe, nag about what needs Adam.
    # ------------------------------------------------------------------
    async def daily_sweep(self, *, requested_by: str = "scheduler") -> dict[str, Any]:
        from app.services.asset_service import get_asset_service
        from app.services.bookkeeper_service import get_bookkeeper_service

        svc = get_bookkeeper_service()
        now = _now()
        today = date.today()
        state = self._read_state()
        cooldowns: dict[str, Any] = state.get("cooldowns") or {}
        dismiss_counts = await self._dismiss_counts()
        actions: list[dict[str, Any]] = []
        nags: list[dict[str, Any]] = []

        # 1. Onboarding gaps → seed questions (idempotent).
        seeded = await self.seed_onboarding_questions()
        if seeded["created_count"]:
            actions.append({"type": "onboarding_seeded", **seeded})

        # 2. Auto-fix: previous month's drafts not generated by the 3rd —
        #    draft-only, so safe to run without asking.
        prev_period = svc._previous_period()
        prev_summary = await svc.recurring_summary(period=prev_period)
        if today.day >= 3 and prev_summary["active_count"] and not prev_summary["all_generated"]:
            gen = await svc.generate_recurring_drafts(period=prev_period)
            metered = await svc.generate_metered_ai_draft(period=prev_period)
            actions.append({
                "type": "auto_generated_monthly_drafts",
                "period": prev_period,
                "recurring_created": gen.get("created_count", 0),
                "metered": metered.get("reason"),
            })

        # 3. Nags (inbox questions, cooled down + dismissal-suppressed).
        async def nag(
            check_key: str, question: str, why: str, *, priority: str = "medium",
            cooldown: timedelta = COOLDOWN_DEFAULT,
        ) -> None:
            kind = check_key.rsplit(".", 1)[0]
            if dismiss_counts.get(kind, 0) >= DISMISS_SUPPRESS_COUNT:
                return
            last = cooldowns.get(check_key, {}).get("last_fired_at")
            if last:
                try:
                    if now - datetime.fromisoformat(last) < cooldown:
                        return
                except Exception:
                    pass
            if await self._open_question_exists(check_key):
                return
            q = await self._create_question(
                bk_key=check_key, question=question, why_needed=why,
                source=SOURCE_AGENT, priority=priority,
            )
            cooldowns[check_key] = {
                "last_fired_at": now.isoformat(),
                "times_fired": cooldowns.get(check_key, {}).get("times_fired", 0) + 1,
            }
            nags.append({"check": check_key, "question_id": q["id"], "priority": priority})

        # 3a. Pending drafts aging.
        pending = await svc.list_drafts(status="pending")
        if pending:
            oldest_days = max(
                (now - datetime.fromtimestamp(d.created_at, tz=timezone.utc)).days
                for d in pending if d.created_at
            ) if any(d.created_at for d in pending) else 0
            if len(pending) > 5 or oldest_days > 7:
                from app.services.bookkeeper_prompts import DRAFT_REVIEW_GUIDANCE

                await nag(
                    f"nag.drafts.{today.strftime('%Y-%m')}",
                    f"{len(pending)} bookkeeping draft(s) await review (oldest {oldest_days}d). "
                    "Accept or reject them on /company/tax so the books stay current.",
                    DRAFT_REVIEW_GUIDANCE,
                    priority="high" if oldest_days > 14 else "medium",
                )

        # 3b. Books gone quiet — no ledger activity in 30 days.
        snap = await svc.snapshot(period="YTD")
        if snap.last_entry_at:
            try:
                last_entry = date.fromisoformat(str(snap.last_entry_at)[:10])
                if (today - last_entry).days > 30:
                    await nag(
                        f"nag.stale_books.{today.strftime('%Y-%m')}",
                        f"No ledger activity since {last_entry.isoformat()}. Upload a bank CSV/OFX or run "
                        "the month's recurring expenses on /company/tax.",
                        "Books over a month stale mean missed deductions and a scramble at filing time.",
                    )
            except Exception:
                pass

        # 3c. Assets missing placed-in-service dates.
        assets = await get_asset_service().list_assets(year=today.year)
        undated = [a.name for a in assets if a.placed_in_service is None]
        if undated:
            await nag(
                f"nag.asset_dates.{today.strftime('%Y-%m')}",
                f"Asset(s) missing a placed-in-service date: {', '.join(undated[:5])}. "
                "Without the date they contribute $0 deduction.",
                "The deduction year is keyed to the placed-in-service date.",
            )

        # 3d. Quarterly estimated-tax deadlines (T-14 and T-3).
        for month, day in _ES_DATES:
            due = date(today.year, month, day)
            if due < today:
                due = date(today.year + 1, month, day)
            days_out = (due - today).days
            if days_out in range(0, 4):
                await nag(
                    f"nag.1040es.{due.isoformat()}.t3",
                    f"Federal estimated tax (1040-ES) is due {due.isoformat()} — {days_out} day(s) away. "
                    "The Tax Calendar on /company/tax has the current quarterly estimate.",
                    "Late estimated payments accrue underpayment penalties.",
                    priority="critical", cooldown=COOLDOWN_CRITICAL,
                )
            elif days_out in range(4, 15):
                await nag(
                    f"nag.1040es.{due.isoformat()}.t14",
                    f"Heads up: federal estimated tax (1040-ES) is due {due.isoformat()}.",
                    "Two weeks' notice to fund the payment.",
                )

        state["cooldowns"] = cooldowns
        report = {
            "computed_at": now.isoformat(),
            "requested_by": requested_by,
            "onboarding_open_gaps": seeded["pending_gaps"],
            "actions": actions,
            "nags": nags,
            "pending_drafts": len(pending),
        }
        state["last_sweep"] = report
        self._write_state(state)
        logger.info(
            "bookkeeper_agent_sweep_done",
            gaps=seeded["pending_gaps"], actions=len(actions), nags=len(nags),
        )
        return report

    async def _open_question_exists(self, bk_key: str) -> bool:
        async with get_session() as session:
            rows = (
                await session.execute(
                    select(CompanyAgentQuestionModel.context).where(
                        CompanyAgentQuestionModel.status == "open",
                        CompanyAgentQuestionModel.source.in_([SOURCE_ONBOARDING, SOURCE_AGENT]),
                    )
                )
            ).scalars().all()
        return any(str((ctx or {}).get("bk_key")) == bk_key for ctx in rows)

    def status(self) -> dict[str, Any]:
        state = self._read_state()
        return {
            "last_sweep": state.get("last_sweep"),
            "last_health": state.get("last_health"),
            "cooldowns": state.get("cooldowns", {}),
        }

    # ------------------------------------------------------------------
    # Books health — deterministic 0-100 grade + weekly Legion report.
    # ------------------------------------------------------------------
    def _read_knowledge(self, name: str, default: Any) -> Any:
        try:
            return json.loads((KNOWLEDGE_DIR / name).read_text(encoding="utf-8"))
        except Exception:
            return default

    def _write_knowledge(self, name: str, value: Any) -> None:
        try:
            KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
            (KNOWLEDGE_DIR / name).write_text(
                json.dumps(value, indent=2, sort_keys=True), encoding="utf-8"
            )
        except Exception as e:
            logger.warning("bookkeeper_knowledge_write_failed", file=name, error=str(e))

    def record_question_event(self, bk_key: str, event: str) -> None:
        """Track asked/answered/dismissed per bk_key — tunes future asks."""
        if not bk_key:
            return
        stats = self._read_knowledge("question_stats.json", {})
        entry = stats.setdefault(bk_key, {"asked": 0, "answered": 0, "dismissed": 0})
        if event in entry:
            entry[event] += 1
        self._write_knowledge("question_stats.json", stats)

    async def books_health(self) -> dict[str, Any]:
        """Deterministic 0-100 books grade with per-dimension detail."""
        from app.services.bookkeeper_service import get_bookkeeper_service
        from app.services.tax_summary_service import get_tax_summary_service

        svc = get_bookkeeper_service()
        today = date.today()
        weights = {
            **DEFAULT_DIMENSION_WEIGHTS,
            **(self._read_knowledge("dimension_weights.json", {}) or {}),
        }

        # completeness — share of onboarding gaps filled.
        pending = await self._pending_onboarding_specs()
        total_specs = len(ONBOARDING_SPECS)
        completeness = round(100 * (total_specs - len(pending)) / total_specs, 1)

        # freshness — how recently the ledger saw an accepted entry.
        snap = await svc.snapshot(period="YTD")
        freshness = 0.0
        if snap.last_entry_at:
            try:
                last_entry = date.fromisoformat(str(snap.last_entry_at)[:10])
                age = (today - last_entry).days
                if age <= 7:
                    freshness = 100.0
                elif age <= 30:
                    freshness = round(100 - (age - 7) * (60 / 23), 1)  # 100 → 40
                elif age <= 60:
                    freshness = round(40 - (age - 30) * (40 / 30), 1)  # 40 → 0
            except Exception:
                pass

        # reconciliation — month drafts generated + no aging backlog.
        prev = await svc.recurring_summary(period=svc._previous_period())
        reconciliation = 0.0
        if not prev["active_count"] or prev["all_generated"]:
            reconciliation += 50.0
        pending_drafts = await svc.list_drafts(status="pending")
        oldest_days = 0
        if pending_drafts:
            stamps = [d.created_at for d in pending_drafts if d.created_at]
            if stamps:
                oldest_days = max(
                    (_now() - datetime.fromtimestamp(s, tz=timezone.utc)).days for s in stamps
                )
        if oldest_days <= 7:
            reconciliation += 50.0
        elif oldest_days <= 14:
            reconciliation += 25.0

        # deduction_capture — core deduction lines actually carrying amounts.
        summary = await get_tax_summary_service().summary(year=today.year)
        amounts = {li["key"]: li["amount"] for li in summary["line_items"]}
        core = ("ledger", "home_office", "cell_phone", "hardware")
        deduction_capture = round(100 * sum(1 for k in core if amounts.get(k, 0) > 0) / len(core), 1)

        dimensions = {
            "completeness": completeness,
            "freshness": freshness,
            "reconciliation": reconciliation,
            "deduction_capture": deduction_capture,
        }
        total_weight = sum(weights.get(k, 0) for k in dimensions) or 1.0
        score = round(sum(dimensions[k] * weights.get(k, 0) for k in dimensions) / total_weight, 1)
        return {
            "score": score,
            "dimensions": dimensions,
            "weights": weights,
            "signals": {
                "onboarding_gaps": len(pending),
                "pending_drafts": len(pending_drafts),
                "oldest_pending_days": oldest_days,
                "last_entry_at": snap.last_entry_at,
                "total_deductible": summary["total_deductible"],
                "est_total_tax_saved": summary["est_total_tax_saved"],
            },
            "computed_at": _now().isoformat(),
        }

    async def weekly_health_run(self, *, requested_by: str = "scheduler") -> dict[str, Any]:
        """Grade the books, narrate, report to Legion, mirror into facts."""
        health = await self.books_health()

        # Narrative — best effort (kimi-k2.5 via unified client).
        try:
            from app.infrastructure.unified_llm_client import get_unified_llm_client
            from app.services.bookkeeper_prompts import BOOKS_HEALTH_NARRATIVE_PROMPT

            narrative = await get_unified_llm_client().chat(
                prompt=BOOKS_HEALTH_NARRATIVE_PROMPT.format(
                    snapshot=json.dumps(health, indent=2)
                ),
                task_type="bookkeeper_health_narrative",
                max_tokens=400,
            )
            health["narrative"] = str(narrative)[:1500] if narrative else None
        except Exception as e:
            logger.warning("bookkeeper_health_narrative_failed", error=str(e))
            health["narrative"] = None

        # Report to Legion's loop registry (idempotent per day via zero_run_id).
        try:
            from app.services.loop_report_sink_client import get_loop_sink

            envelope = {
                "zero_run_id": int(f"77{date.today():%Y%m%d}"),
                "loop_name": "zero-bookkeeper-agent",
                "owner_project": "zero",
                "variant_label": None,
                "status": "success",
                "judge_score": health["score"] / 100.0,
                "duration_s": None,
                "vault_path": None,
                "cost_tokens": None,
                "payload": {
                    "dimensions": health["dimensions"],
                    "signals": health["signals"],
                    "requested_by": requested_by,
                },
            }
            push = await get_loop_sink().push(envelope)
            health["legion_push"] = push.get("status")
        except Exception as e:
            logger.warning("bookkeeper_health_legion_push_failed", error=str(e))
            health["legion_push"] = "failed"

        # Mirror into company_facts for the UI + daily brief.
        try:
            from app.models.company_facts import CompanyFactCreate
            from app.services.company_facts_service import get_company_facts_service

            facts = get_company_facts_service()
            await facts.upsert_fact(
                CompanyFactCreate(
                    key="books_health.score",
                    label="Books health score (0-100)",
                    value=str(health["score"]),
                    domain="finance",
                ),
                created_by="bookkeeper_agent",
                source=SOURCE_AGENT,
            )
            await facts.upsert_fact(
                CompanyFactCreate(
                    key="books_health.graded_at",
                    label="Books health graded at",
                    value=health["computed_at"],
                    domain="finance",
                ),
                created_by="bookkeeper_agent",
                source=SOURCE_AGENT,
            )
        except Exception as e:
            logger.warning("bookkeeper_health_facts_mirror_failed", error=str(e))

        # Audit history (pruned) + state.
        history = self._read_knowledge("audit_history.json", [])
        history.append({
            "computed_at": health["computed_at"],
            "score": health["score"],
            "dimensions": health["dimensions"],
        })
        self._write_knowledge("audit_history.json", history[-AUDIT_HISTORY_LIMIT:])
        state = self._read_state()
        state["last_health"] = {k: health[k] for k in ("score", "dimensions", "computed_at", "narrative") if k in health}
        self._write_state(state)

        logger.info("bookkeeper_health_run_done", score=health["score"], legion=health.get("legion_push"))
        return health


class _ParseError(ValueError):
    """Answer text the agent could not turn into data — reopens the question."""


@lru_cache(maxsize=1)
def get_bookkeeper_agent_service() -> BookkeeperAgentService:
    return BookkeeperAgentService()
