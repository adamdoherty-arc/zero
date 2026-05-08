"""
Multi-account OAuth management.

Lists every connected Google account (personal + work + ...), surfaces
account-scoped settings (label, default flag, quiet hours), and exposes
disconnect. The auth flow itself lives in `routers/google_oauth.py` —
adding a new account = `GET /api/google/auth/start?label=work`.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import structlog

from app.services.gmail_oauth_service import get_gmail_oauth_service

router = APIRouter()
logger = structlog.get_logger(__name__)


class QuietHoursPayload(BaseModel):
    start: str | None = None  # "09:00"
    end: str | None = None  # "17:00"
    weekdays_only: bool | None = None
    enabled: bool | None = None  # opt-in switch; missing = off


class LabelPayload(BaseModel):
    label: str


@router.get("")
async def list_accounts() -> dict:
    """All connected Google accounts."""
    accounts = await get_gmail_oauth_service().list_accounts()
    return {"accounts": accounts, "total": len(accounts)}


@router.get("/{account_id}")
async def get_account(account_id: str) -> dict:
    svc = get_gmail_oauth_service()
    account = await svc.get_account(account_id)
    if account is None:
        raise HTTPException(404, "Account not found")
    return {
        "id": account.id,
        "label": account.label,
        "email": account.email,
        "is_default": account.is_default,
        "scopes": account.scopes or [],
        "quiet_hours": account.quiet_hours or {},
        "metadata": account.metadata_ or {},
        "connected_at": account.connected_at.isoformat() if account.connected_at else None,
        "last_refreshed_at": account.last_refreshed_at.isoformat() if account.last_refreshed_at else None,
    }


@router.post("/{account_id}/default")
async def set_default(account_id: str) -> dict:
    svc = get_gmail_oauth_service()
    account = await svc.get_account(account_id)
    if account is None:
        raise HTTPException(404, "Account not found")
    await svc.set_default(account_id)
    return {"status": "ok", "default_account_id": account_id}


@router.patch("/{account_id}/label")
async def set_label(account_id: str, payload: LabelPayload) -> dict:
    label = (payload.label or "").strip()
    if not label:
        raise HTTPException(400, "Label required")
    svc = get_gmail_oauth_service()
    account = await svc.get_account(account_id)
    if account is None:
        raise HTTPException(404, "Account not found")
    await svc.set_label(account_id, label)
    return {"status": "ok", "label": label}


@router.patch("/{account_id}/quiet-hours")
async def set_quiet_hours(account_id: str, payload: QuietHoursPayload) -> dict:
    """Configure when Reachy should NOT announce emails for this account.

    Empty payload (or `enabled=false`) disables quiet hours and Reachy
    announces normally for this account.
    """
    svc = get_gmail_oauth_service()
    account = await svc.get_account(account_id)
    if account is None:
        raise HTTPException(404, "Account not found")
    qh = payload.model_dump(exclude_none=True)
    if not qh.get("enabled"):
        qh = {}
    await svc.set_quiet_hours(account_id, qh)
    return {"status": "ok", "quiet_hours": qh}


@router.delete("/{account_id}")
async def disconnect_account(account_id: str) -> dict:
    """Disconnect an account (revoke tokens at Google + remove DB row)."""
    svc = get_gmail_oauth_service()
    ok = await svc.disconnect(account_id=account_id)
    if not ok:
        raise HTTPException(404, "Account not found")
    return {"status": "disconnected", "account_id": account_id}
