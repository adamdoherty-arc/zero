"""Company facts service.

KV registry over the `company_facts` table. Captures structured artifacts
emitted at task completion (e.g. EIN value, Florida document number, bank
account last four) and mirrors the registry into a markdown file the existing
docs index picks up.
"""

from __future__ import annotations

import uuid
from functools import lru_cache
from typing import Optional

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
