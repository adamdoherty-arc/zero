"""Daily brief API.

Surface for the dashboard tile and on-demand "speak it" / "send it"
controls. The 7am scheduler is registered separately in main.py.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter()


class SendNowRequest(BaseModel):
    to: str | None = None
    from_account: str = "default"
    regenerate: bool = Field(
        False,
        description="If true, recompose before sending; otherwise use the cached today's brief.",
    )


@router.get("/today")
async def today():
    from app.services.daily_brief_service import get_daily_brief_service
    svc = get_daily_brief_service()
    cached = await svc.latest()
    if cached is not None:
        return cached.to_dict()
    fresh = await svc.compose_today()
    return fresh.to_dict()


@router.post("/regenerate")
async def regenerate():
    from app.services.daily_brief_service import get_daily_brief_service
    return (await get_daily_brief_service().compose_today()).to_dict()


@router.get("/history")
async def history(limit: int = Query(14, ge=1, le=90)):
    from app.services.daily_brief_service import get_daily_brief_service
    briefs = await get_daily_brief_service().history(limit=limit)
    return {"briefs": [b.to_dict() for b in briefs]}


@router.post("/send-now")
async def send_now(req: SendNowRequest):
    from app.services.daily_brief_service import get_daily_brief_service
    from app.services.digest_email_service import get_digest_email_service
    svc = get_daily_brief_service()
    payload = await svc.compose_today() if req.regenerate else (await svc.latest() or await svc.compose_today())
    res = await get_digest_email_service().send(
        markdown=payload.markdown,
        subject=f"Daily brief — {payload.date}",
        to=req.to,
        from_account=req.from_account,
    )
    return {"brief_date": payload.date, **res}
