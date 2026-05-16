"""Company facts API.

Read/write surface over the `company_facts` KV registry. The complete-task
endpoint (in routers/company_work_items.py) writes facts as a side effect;
this router exposes manual list/create/update/delete.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.infrastructure.auth import require_auth
from app.models.company_facts import CompanyFact, CompanyFactCreate, CompanyFactUpdate
from app.services.company_facts_service import get_company_facts_service


router = APIRouter(
    prefix="/api/company/facts",
    tags=["company-facts"],
    dependencies=[Depends(require_auth)],
)


class CompanyFactCreateRequest(CompanyFactCreate):
    actor: str = Field(default="user", max_length=100)


@router.get("", response_model=list[CompanyFact])
async def list_facts(
    domain: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None),
):
    return await get_company_facts_service().list_facts(domain=domain, search=search)


@router.get("/by-key/{key}", response_model=CompanyFact)
async def get_by_key(key: str):
    fact = await get_company_facts_service().get_fact(key)
    if not fact:
        raise HTTPException(404, f"Company fact key '{key}' not found")
    return fact


@router.post("", response_model=CompanyFact)
async def upsert_fact(req: CompanyFactCreateRequest):
    payload = CompanyFactCreate(
        key=req.key,
        label=req.label,
        value=req.value,
        domain=req.domain,
        evidence_url=req.evidence_url,
        sensitive=req.sensitive,
        notes=req.notes,
    )
    return await get_company_facts_service().upsert_fact(payload, created_by=req.actor, source="manual")


@router.patch("/{fact_id}", response_model=CompanyFact)
async def patch_fact(fact_id: str, updates: CompanyFactUpdate):
    fact = await get_company_facts_service().patch_fact(fact_id, updates)
    if not fact:
        raise HTTPException(404, f"Company fact {fact_id} not found")
    return fact


@router.delete("/{fact_id}")
async def delete_fact(fact_id: str):
    ok = await get_company_facts_service().delete_fact(fact_id)
    if not ok:
        raise HTTPException(404, f"Company fact {fact_id} not found")
    return {"status": "deleted", "id": fact_id}
