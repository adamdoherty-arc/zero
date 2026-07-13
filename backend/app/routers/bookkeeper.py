"""ADA AI bookkeeping API.

Voice-friendly snapshot, CSV ingestion (draft only), draft approval flow.
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from app.infrastructure.auth import require_auth

router = APIRouter(dependencies=[Depends(require_auth)])


class IngestRequest(BaseModel):
    source: str = Field(..., description="bank_csv|receipt_ocr|manual")
    csv: str = Field(..., description="raw CSV text from the bank export")
    paid_from: str = Field(
        default="business", max_length=120,
        description="business|personal — personal-paid drafts post against owner equity",
    )


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


@router.get("/categories")
async def categories():
    """First-class expense-category presets for the recurring-expense form."""
    from app.services.bookkeeper_service import RECURRING_CATEGORY_PRESETS
    return {"categories": RECURRING_CATEGORY_PRESETS}


@router.get("/snapshot")
async def snapshot(period: str = Query("YTD", pattern="^(YTD|MTD|QTD)$")):
    from app.services.bookkeeper_service import get_bookkeeper_service
    return (await get_bookkeeper_service().snapshot(period=period)).to_dict()


@router.post("/ingest")
async def ingest(req: IngestRequest):
    from app.services.bookkeeper_service import get_bookkeeper_service
    drafts = await get_bookkeeper_service().ingest_bank_csv(
        source=req.source, csv_text=req.csv, paid_from=req.paid_from,
    )
    return {"drafts": [d.to_dict() for d in drafts], "count": len(drafts)}


@router.post("/ingest-ofx")
async def ingest_ofx(file: UploadFile = File(...), paid_from: str = Form("business")):
    """Upload an OFX/QFX bank export → pending drafts (FITID-deduped)."""
    from app.services.bookkeeper_service import get_bookkeeper_service
    content = await file.read()
    try:
        drafts = await get_bookkeeper_service().ingest_ofx(
            source="bank_ofx", ofx_bytes=content, paid_from=paid_from,
        )
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {"drafts": [d.to_dict() for d in drafts], "count": len(drafts)}


@router.post("/receipts")
async def ingest_receipt(file: UploadFile = File(...), paid_from: str = Form("personal")):
    """Upload a receipt/invoice (PDF or photo) → one pending draft."""
    from app.services.bookkeeper_service import get_bookkeeper_service
    content = await file.read()
    try:
        draft = await get_bookkeeper_service().ingest_receipt(
            filename=file.filename or "receipt", content=content, paid_from=paid_from,
        )
    except ValueError as e:
        raise HTTPException(422, str(e))
    return draft.to_dict()


class RuleCreateRequest(BaseModel):
    match_type: str = Field(default="contains", pattern="^(payee|contains|regex)$")
    pattern: str = Field(..., min_length=1, max_length=200)
    category: str = Field(..., min_length=1)
    priority: int = Field(default=100, ge=0, le=1000)


class RuleUpdateRequest(BaseModel):
    match_type: str | None = Field(default=None, pattern="^(payee|contains|regex)$")
    pattern: str | None = Field(default=None, max_length=200)
    category: str | None = None
    priority: int | None = Field(default=None, ge=0, le=1000)
    active: bool | None = None


@router.get("/rules")
async def list_rules():
    """Categorization rules, highest precedence first."""
    from app.services.bookkeeper_service import get_bookkeeper_service
    rules = await get_bookkeeper_service().list_rules()
    return {"rules": [r.to_dict() for r in rules]}


@router.post("/rules")
async def add_rule(req: RuleCreateRequest):
    from app.services.bookkeeper_service import get_bookkeeper_service
    rule = await get_bookkeeper_service().add_rule(
        match_type=req.match_type, pattern=req.pattern, category=req.category, priority=req.priority,
    )
    return rule.to_dict()


@router.patch("/rules/{rule_id}")
async def update_rule(rule_id: str, req: RuleUpdateRequest):
    from app.services.bookkeeper_service import get_bookkeeper_service
    rule = await get_bookkeeper_service().update_rule(rule_id, **req.model_dump(exclude_unset=True))
    if rule is None:
        raise HTTPException(404, "rule not found")
    return rule.to_dict()


@router.delete("/rules/{rule_id}")
async def delete_rule(rule_id: str):
    from app.services.bookkeeper_service import get_bookkeeper_service
    ok = await get_bookkeeper_service().delete_rule(rule_id)
    if not ok:
        raise HTTPException(404, "rule not found")
    return {"status": "deleted", "id": rule_id}


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


@router.get("/recurring/suggestions")
async def recurring_suggestions():
    """Subscription-like spend detected in the ledger but not yet tracked."""
    from app.services.bookkeeper_service import get_bookkeeper_service
    return {"suggestions": await get_bookkeeper_service().suggest_recurring()}


class SuggestionAcceptRequest(BaseModel):
    vendor: str = Field(..., min_length=1, max_length=120)
    amount_monthly: float = Field(..., ge=0)
    category: str = Field(default="Expenses:Software:AI")
    billing_day: int = Field(default=1, ge=1, le=31)
    paid_from: str = Field(default="business", max_length=120)


@router.post("/recurring/suggestions/accept")
async def accept_recurring_suggestion(req: SuggestionAcceptRequest):
    """One-click 'Track' on a detected subscription → recurring registry entry."""
    from app.services.bookkeeper_service import get_bookkeeper_service
    entry = await get_bookkeeper_service().add_recurring(
        vendor=req.vendor,
        amount_monthly=req.amount_monthly,
        category=req.category,
        billing_day=req.billing_day,
        paid_from=req.paid_from,
        notes="Detected by the bookkeeper (find-schedules)",
    )
    return entry.to_dict()


@router.post("/recurring/run")
async def run_recurring(period: str | None = Query(default=None, pattern="^[0-9]{4}-[0-9]{2}$")):
    """Generate this month's (or `period` YYYY-MM) expense drafts. Idempotent."""
    from app.services.bookkeeper_service import get_bookkeeper_service
    return await get_bookkeeper_service().generate_recurring_drafts(period=period)


@router.post("/metered/run")
async def run_metered(period: str | None = Query(default=None, pattern="^[0-9]{4}-[0-9]{2}$")):
    """Draft the month's metered LLM API spend from llm_usage (default: previous month). Idempotent."""
    from app.services.bookkeeper_service import get_bookkeeper_service
    return await get_bookkeeper_service().generate_metered_ai_draft(period=period)


@router.get("/voice")
async def voice_question(q: str = Query(..., min_length=2, max_length=400)):
    from app.services.bookkeeper_service import get_bookkeeper_service
    answer = await get_bookkeeper_service().answer_voice_question(q)
    return {"answer": answer}
