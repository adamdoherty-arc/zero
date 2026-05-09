"""ADA AI bookkeeping API.

Voice-friendly snapshot, CSV ingestion (draft only), draft approval flow.
"""

from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter()


class IngestRequest(BaseModel):
    source: str = Field(..., description="bank_csv|receipt_ocr|manual")
    csv: str = Field(..., description="raw CSV text from the bank export")


class AcceptRequest(BaseModel):
    category: str | None = None


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


@router.get("/voice")
async def voice_question(q: str = Query(..., min_length=2, max_length=400)):
    from app.services.bookkeeper_service import get_bookkeeper_service
    answer = await get_bookkeeper_service().answer_voice_question(q)
    return {"answer": answer}
