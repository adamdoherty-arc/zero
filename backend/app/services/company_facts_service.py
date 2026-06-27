"""Company facts service.

KV registry over the `company_facts` table. Captures structured artifacts
emitted at task completion (e.g. EIN value, Florida document number, bank
account last four) and mirrors the registry into a markdown file the existing
docs index picks up.
"""

from __future__ import annotations

import uuid
from functools import lru_cache
from typing import Any, Optional

from sqlalchemy import or_, select

from app.db.models import CompanyFactModel
from app.infrastructure.database import get_session
from app.models.company_facts import CompanyFact, CompanyFactCreate, CompanyFactUpdate


def _mask(value: str, *, sensitive: bool) -> str:
    if not sensitive or not value:
        return value
    if len(value) <= 4:
        return "****"
    return f"{'*' * (len(value) - 4)}{value[-4:]}"


class CompanyFactsService:
    """CRUD over the company_facts registry."""

    async def list_facts(self, *, domain: Optional[str] = None, search: Optional[str] = None) -> list[CompanyFact]:
        async with get_session() as session:
            stmt = select(CompanyFactModel)
            if domain:
                stmt = stmt.where(CompanyFactModel.domain == domain)
            if search:
                like = f"%{search.lower()}%"
                stmt = stmt.where(
                    or_(
                        CompanyFactModel.key.ilike(like),
                        CompanyFactModel.label.ilike(like),
                        CompanyFactModel.value.ilike(like),
                    )
                )
            stmt = stmt.order_by(CompanyFactModel.domain.nullsfirst(), CompanyFactModel.label)
            rows = (await session.execute(stmt)).scalars().all()
        return [CompanyFact.model_validate(row, from_attributes=True) for row in rows]

    async def home_office_summary(self) -> dict[str, Any]:
        """Deduction-ready summary from `home_office.*` facts.

        Surfaces BOTH the simplified ($5/sqft, 300 sqft / $1,500 cap) and actual
        (% of indirect costs + internet allocation) estimates so the CPA elects
        the method at tax time (IRS Pub 587). Reads facts keyed `home_office.*`
        written by the Finance-tab worksheet. Nothing here is tax advice.
        """
        async with get_session() as session:
            rows = (
                await session.execute(
                    select(CompanyFactModel).where(CompanyFactModel.key.like("home_office.%"))
                )
            ).scalars().all()
        values: dict[str, str] = {row.key.split("home_office.", 1)[-1]: (row.value or "") for row in rows}

        def _num(name: str, *, lo: Optional[float] = None, hi: Optional[float] = None) -> Optional[float]:
            raw = values.get(name)
            if raw is None or str(raw).strip() == "":
                return None
            try:
                v = float(str(raw).replace("$", "").replace(",", "").replace("%", "").strip())
            except Exception:
                return None
            # Clamp out-of-range typos so a stray "-50" sqft or ">100%" can't
            # surface a negative/over-allocated deduction estimate.
            if lo is not None:
                v = max(lo, v)
            if hi is not None:
                v = min(hi, v)
            return v

        exclusive = _num("exclusive_sqft", lo=0)
        total = _num("total_sqft", lo=0)
        explicit_pct = _num("business_use_pct", lo=0, hi=100)
        if explicit_pct is not None:
            business_use_pct: Optional[float] = explicit_pct
        elif exclusive and total:
            business_use_pct = round(100 * exclusive / total, 2) if total else None
        else:
            business_use_pct = None

        simplified_estimate = round(min(exclusive, 300) * 5, 2) if exclusive else None

        rent = _num("rent_or_mortgage_monthly", lo=0)
        utilities = _num("utilities_monthly", lo=0)
        electricity = _num("electricity_monthly", lo=0)
        insurance = _num("insurance_monthly", lo=0)
        repairs = _num("repairs_ytd", lo=0) or 0.0
        internet = _num("internet_monthly", lo=0)
        internet_pct = _num("internet_business_pct", lo=0, hi=100)

        actual_estimate_annual: Optional[float] = None
        if business_use_pct is not None and any(v is not None for v in (rent, utilities, electricity, insurance)):
            indirect_annual = (
                ((rent or 0.0) + (utilities or 0.0) + (electricity or 0.0) + (insurance or 0.0)) * 12
            ) + repairs
            actual = indirect_annual * (business_use_pct / 100.0)
            if internet is not None and internet_pct is not None:
                actual += internet * 12 * (internet_pct / 100.0)
            actual_estimate_annual = round(actual, 2)

        required = {
            "exclusive_sqft": "Exclusive business-use square feet",
            "total_sqft": "Total home square feet",
            "rent_or_mortgage_monthly": "Monthly rent or mortgage interest",
            "utilities_monthly": "Monthly utilities",
            "internet_monthly": "Monthly internet",
            "internet_business_pct": "Internet business-use %",
        }
        missing_fields = [label for key, label in required.items() if _num(key) is None]

        return {
            "method": values.get("method") or "undecided",
            "business_use_pct": business_use_pct,
            "simplified_estimate": simplified_estimate,
            "simplified_note": "$5/sqft, max 300 sqft ($1,500/yr cap) — IRS Pub 587 simplified method.",
            "actual_estimate_annual": actual_estimate_annual,
            "inputs": values,
            "missing_fields": missing_fields,
            "facts_count": len(rows),
        }

    # IRS 2026 business standard mileage rate (Notice 2026-10). Stored as the
    # `tax.mileage_rate` fact so it's editable in the UI and updatable each year.
    DEFAULT_MILEAGE_RATE = 0.725

    async def deductions_summary(self) -> dict[str, Any]:
        """Annualized deductible estimate for the mixed-use worksheets.

        Reads `cell_phone.*` (monthly bill x business-use %), `vehicle.*`
        (business miles YTD x standard mileage rate), and the editable
        `tax.mileage_rate` fact. Internet stays in the home-office worksheet to
        avoid double counting; it is NOT included here. Nothing is tax advice.
        """
        async with get_session() as session:
            rows = (
                await session.execute(
                    select(CompanyFactModel).where(
                        or_(
                            CompanyFactModel.key.like("cell_phone.%"),
                            CompanyFactModel.key.like("vehicle.%"),
                            CompanyFactModel.key == "tax.mileage_rate",
                        )
                    )
                )
            ).scalars().all()
        values: dict[str, str] = {row.key: (row.value or "") for row in rows}

        def _num(key: str, *, lo: Optional[float] = None, hi: Optional[float] = None) -> Optional[float]:
            raw = values.get(key)
            if raw is None or str(raw).strip() == "":
                return None
            try:
                v = float(str(raw).replace("$", "").replace(",", "").replace("%", "").strip())
            except Exception:
                return None
            if lo is not None:
                v = max(lo, v)
            if hi is not None:
                v = min(hi, v)
            return v

        cell_monthly = _num("cell_phone.monthly", lo=0)
        cell_pct = _num("cell_phone.business_pct", lo=0, hi=100)
        cell_annual: Optional[float] = None
        if cell_monthly is not None and cell_pct is not None:
            cell_annual = round(cell_monthly * 12 * (cell_pct / 100.0), 2)

        miles = _num("vehicle.business_miles_ytd", lo=0)
        mileage_rate = _num("tax.mileage_rate", lo=0) or self.DEFAULT_MILEAGE_RATE
        vehicle_annual: Optional[float] = None
        if miles is not None:
            vehicle_annual = round(miles * mileage_rate, 2)

        return {
            "cell_phone": {
                "monthly": cell_monthly,
                "business_pct": cell_pct,
                "annual_deductible": cell_annual,
            },
            "vehicle": {
                "business_miles_ytd": miles,
                "mileage_rate": mileage_rate,
                "annual_deductible": vehicle_annual,
                "rate_note": f"IRS standard mileage rate (default {self.DEFAULT_MILEAGE_RATE}/mi, 2026).",
            },
            "total_annual_deductible": round((cell_annual or 0.0) + (vehicle_annual or 0.0), 2),
        }

    async def get_fact(self, key: str) -> Optional[CompanyFact]:
        async with get_session() as session:
            row = (
                await session.execute(select(CompanyFactModel).where(CompanyFactModel.key == key).limit(1))
            ).scalars().first()
        return CompanyFact.model_validate(row, from_attributes=True) if row else None

    async def get_facts_for_task(self, task_id: str) -> list[CompanyFact]:
        async with get_session() as session:
            rows = (
                await session.execute(
                    select(CompanyFactModel).where(CompanyFactModel.source_task_id == task_id).order_by(CompanyFactModel.label)
                )
            ).scalars().all()
        return [CompanyFact.model_validate(row, from_attributes=True) for row in rows]

    async def upsert_fact(
        self,
        data: CompanyFactCreate,
        *,
        created_by: str = "user",
        source: str = "task_completion",
        source_task_id: Optional[str] = None,
    ) -> CompanyFact:
        async with get_session() as session:
            existing = (
                await session.execute(select(CompanyFactModel).where(CompanyFactModel.key == data.key).limit(1))
            ).scalars().first()
            if existing:
                existing.label = data.label
                existing.value = data.value
                existing.domain = data.domain
                existing.evidence_url = data.evidence_url
                existing.sensitive = data.sensitive
                existing.notes = data.notes
                if source_task_id:
                    existing.source_task_id = source_task_id
                existing.source = source
                if created_by:
                    existing.created_by = created_by
                await session.flush()
                fact = CompanyFact.model_validate(existing, from_attributes=True)
            else:
                row = CompanyFactModel(
                    id=f"cf-{uuid.uuid4().hex[:12]}",
                    key=data.key,
                    label=data.label,
                    value=data.value,
                    domain=data.domain,
                    source_task_id=source_task_id,
                    source=source,
                    evidence_url=data.evidence_url,
                    sensitive=data.sensitive,
                    notes=data.notes,
                    created_by=created_by,
                )
                session.add(row)
                await session.flush()
                fact = CompanyFact.model_validate(row, from_attributes=True)

        from app.services.company_facts_markdown_mirror import get_company_facts_mirror

        await get_company_facts_mirror().refresh()
        return fact

    async def patch_fact(self, fact_id: str, updates: CompanyFactUpdate) -> Optional[CompanyFact]:
        async with get_session() as session:
            row = (
                await session.execute(select(CompanyFactModel).where(CompanyFactModel.id == fact_id).limit(1))
            ).scalars().first()
            if not row:
                return None
            data = updates.model_dump(exclude_unset=True)
            for field, value in data.items():
                setattr(row, field, value)
            await session.flush()
            fact = CompanyFact.model_validate(row, from_attributes=True)

        from app.services.company_facts_markdown_mirror import get_company_facts_mirror

        await get_company_facts_mirror().refresh()
        return fact

    async def delete_fact(self, fact_id: str) -> bool:
        async with get_session() as session:
            row = (
                await session.execute(select(CompanyFactModel).where(CompanyFactModel.id == fact_id).limit(1))
            ).scalars().first()
            if not row:
                return False
            await session.delete(row)

        from app.services.company_facts_markdown_mirror import get_company_facts_mirror

        await get_company_facts_mirror().refresh()
        return True


@lru_cache()
def get_company_facts_service() -> CompanyFactsService:
    return CompanyFactsService()
