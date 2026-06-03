"""ADA AI bookkeeping API.

Voice-friendly snapshot, CSV ingestion (draft only), draft approval flow.
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.infrastructure.auth import require_auth

router = APIRouter(dependencies=[Depends(require_auth)])


class IngestRequest(BaseModel):
    source: str = Field(..., description="bank_csv|receipt_ocr|manual")
    csv: str = Field(..., description="raw CSV text from the bank export")


class AcceptRequest(BaseModel):
    category: str | None = None


class RecurringCreateRequest(BaseModel):
    # billing_day accepts 1-31 (the UI lets you type any day); the service
    # clamps to 28 so short months never drop a charge. Keeping the router
    # range at 31 avoids a confusing 422 on day 29-31.
    vendor: str = Field(..., min_length=1, max_length=120, description="e.g. Anthropic Claude Max")
    amount_monthly: float = Field(..., ge=0, description="flat monthly charge in USD")
    category: str = Field(default="Expenses:Software:AI")
    billing_day: int = Field(default=1, ge=1, le=31)
    paid_from: str = Field(default="personal card", max_length=120)
    notes: str = Field(default="", max_length=500)


class RecurringUpdateRequest(BaseModel):
    vendor: str | None = Field(default=None, max_length=120)
    amount_monthly: float | None = Field(default=None, ge=0)
    category: str | None = None
    billing_day: int | None = Field(default=None, ge=1, le=31)
    paid_from: str | None = Field(default=None, max_length=120)
    active: bool | None = None
    notes: str | None = Field(default=None, max_length=500)


@router.get("/snapshot")
async def snapshot(period: str = Query("YTD", pattern="^(YTD|MTD|QTD)$")):
    from app.services.bookkeeper_service import get_bookkeeper_service
    return (await get_bookkeeper_service().snapshot(period=period)).to_dict()


@router.post("/ingest")
async def ingest(req: IngestRequest):
    from app.services.bookkeeper_service import get_bookkeeper_service
    drafts = await get_bookkeeper_service().ingest_bank_csv(
        source=req.source, csv_text=req.csv,
    )
    return {"drafts": [d.to_dict() for d in drafts], "count": len(drafts)}


@router.get("/drafts")
async def list_drafts(status: str | None = None):
    from app.services.bookkeeper_service import get_bookkeeper_service
    drafts = await get_bookkeeper_service().list_drafts(status=status)
    return {"drafts": [d.to_dict() for d in drafts]}


@router.post("/drafts/{draft_id}/accept")
async def accept(draft_id: str, req: AcceptRequest = Body(default=AcceptRequest())):
    from app.services.bookkeeper_service import get_bookkeeper_service
    d = await get_bookkeeper_service().accept_draft(draft_id, category=req.category)
    if d is None:
        raise HTTPException(404, "draft not found")
    return d.to_dict()


@router.post("/drafts/{draft_id}/reject")
async def reject(draft_id: str):
    from app.services.bookkeeper_service import get_bookkeeper_service
    d = await get_bookkeeper_service().reject_draft(draft_id)
    if d is None:
        raise HTTPException(404, "draft not found")
    return d.to_dict()


@router.get("/recurring")
async def list_recurring():
    """List recurring business expenses (AI subscriptions, etc.) + this month's totals."""
    from app.services.bookkeeper_service import get_bookkeeper_service
    svc = get_bookkeeper_service()
    items = await svc.list_recurring()
    summary = await svc.recurring_summary()
    return {"recurring": [r.to_dict() for r in items], "summary": summary}


@router.post("/recurring")
async def add_recurring(req: RecurringCreateRequest):
    from app.services.bookkeeper_service import get_bookkeeper_service
    if not req.vendor.strip():
        raise HTTPException(422, "vendor cannot be blank")
    entry = await get_bookkeeper_service().add_recurring(
        vendor=req.vendor,
        amount_monthly=req.amount_monthly,
        category=req.category,
        billing_day=req.billing_day,
        paid_from=req.paid_from,
        notes=req.notes,
    )
    return entry.to_dict()


@router.patch("/recurring/{recurring_id}")
async def update_recurring(recurring_id: str, req: RecurringUpdateRequest):
    from app.services.bookkeeper_service import get_bookkeeper_service
    entry = await get_bookkeeper_service().update_recurring(
        recurring_id, **req.model_dump(exclude_unset=True)
    )
    if entry is None:
        raise HTTPException(404, "recurring expense not found")
    return entry.to_dict()


@router.delete("/recurring/{recurring_id}")
async def delete_recurring(recurring_id: str):
    from app.services.bookkeeper_service import get_bookkeeper_service
    ok = await get_bookkeeper_service().delete_recurring(recurring_id)
    if not ok:
        raise HTTPException(404, "recurring expense not found")
    return {"status": "deleted", "id": recurring_id}


@router.post("/recurring/run")
async def run_recurring(period: str | None = Query(default=None, pattern="^[0-9]{4}-[0-9]{2}$")):
    """Generate this month's (or `period` YYYY-MM) expense drafts. Idempotent."""
    from app.services.bookkeeper_service import get_bookkeeper_service
    return await get_bookkeeper_service().generate_recurring_drafts(period=period)


@router.get("/voice")
async def voice_question(q: str = Query(..., min_length=2, max_length=400)):
    from app.services.bookkeeper_service import get_bookkeeper_service
    answer = await get_bookkeeper_service().answer_voice_question(q)
    return {"answer": answer}
