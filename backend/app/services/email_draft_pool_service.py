"""
Per-account email draft pool with approve / reject gates.

Reachy drafts; Adam approves. This service is the queue between the two —
every spoken or LLM-generated draft lands here scoped by `(account_id,
thread_id)` and waits for an explicit ``approve`` (which sends via the
existing Gmail service) or ``reject`` (which marks it discarded).

Storage: JSON file at ``workspace/email/draft_pool.json``. We don't need a
DB table for this — the pool is small, append-mostly, and the human-loop
turnover is hours not seconds.

Per-account scoping: Adam runs multiple Gmail accounts. Every draft must
carry an ``account_id`` so the UI can group them and the send step routes
through the right OAuth token. ``account_id="default"`` falls back to the
single-account path so old surfaces continue to work.

Drop-in pattern (called by `email_draft_service` or the supervisor's email
adapter):

    pool = get_email_draft_pool()
    draft_id = await pool.add_draft(
        account_id="work",
        thread_id="msg-12345",
        to="cpa@example.com",
        subject="Re: W-2 vs 1099",
        body="...",
        meta={"source": "voice", "user_text": "draft a reply..."},
    )

    # later, from the dashboard or "send it" voice command:
    await pool.approve(draft_id)
    # or:
    await pool.reject(draft_id, reason="adam said no")
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import structlog

logger = structlog.get_logger()

POOL_PATH = Path("workspace") / "email" / "draft_pool.json"
MAX_DRAFTS = 500


def _now() -> float:
    return time.time()


@dataclass
class Draft:
    id: str
    account_id: str
    thread_id: Optional[str]
    to: str
    subject: str
    body: str
    status: str  # pending | approved | rejected | sent | failed
    created_at: float
    updated_at: float
    meta: dict[str, Any] = field(default_factory=dict)
    sent_message_id: Optional[str] = None
    error: Optional[str] = None
    rejection_reason: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class EmailDraftPool:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        POOL_PATH.parent.mkdir(parents=True, exist_ok=True)

    def _read(self) -> dict[str, Any]:
        if not POOL_PATH.exists():
            return {"drafts": []}
        try:
            return json.loads(POOL_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("draft_pool_read_failed", error=str(e))
            return {"drafts": []}

    def _write(self, data: dict[str, Any]) -> None:
        tmp = POOL_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(POOL_PATH)

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def add_draft(
        self,
        *,
        account_id: str,
        to: str,
        subject: str,
        body: str,
        thread_id: Optional[str] = None,
        meta: Optional[dict[str, Any]] = None,
    ) -> Draft:
        if not to or not subject:
            raise ValueError("to and subject are required")
        async with self._lock:
            store = self._read()
            drafts = store.get("drafts") or []
            d = Draft(
                id=f"draft-{uuid.uuid4().hex[:12]}",
                account_id=account_id or "default",
                thread_id=thread_id,
                to=to,
                subject=subject,
                body=body or "",
                status="pending",
                created_at=_now(),
                updated_at=_now(),
                meta=dict(meta or {}),
            )
            drafts.append(d.to_dict())
            # Cap pool size: drop oldest non-pending entries first.
            if len(drafts) > MAX_DRAFTS:
                drafts.sort(key=lambda r: (r.get("status") == "pending", r.get("created_at", 0)))
                drafts = drafts[-MAX_DRAFTS:]
            store["drafts"] = drafts
            self._write(store)
            logger.info(
                "draft_pool_add",
                draft_id=d.id, account_id=d.account_id, to=to,
            )
            return d

    async def list_drafts(
        self,
        *,
        account_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> list[Draft]:
        async with self._lock:
            store = self._read()
            drafts = store.get("drafts") or []
        out = []
        for r in sorted(drafts, key=lambda x: x.get("updated_at", 0), reverse=True):
            if account_id and r.get("account_id") != account_id:
                continue
            if status and r.get("status") != status:
                continue
            out.append(Draft(**{
                **r,
                "meta": r.get("meta") or {},
            }))
            if len(out) >= limit:
                break
        return out

    async def get_draft(self, draft_id: str) -> Optional[Draft]:
        async with self._lock:
            store = self._read()
            for r in store.get("drafts") or []:
                if r.get("id") == draft_id:
                    return Draft(**{**r, "meta": r.get("meta") or {}})
        return None

    async def update_body(self, draft_id: str, body: str) -> Optional[Draft]:
        async with self._lock:
            store = self._read()
            drafts = store.get("drafts") or []
            for r in drafts:
                if r.get("id") == draft_id:
                    r["body"] = body or ""
                    r["updated_at"] = _now()
                    self._write(store)
                    return Draft(**{**r, "meta": r.get("meta") or {}})
        return None

    async def reject(self, draft_id: str, *, reason: str = "") -> Optional[Draft]:
        async with self._lock:
            store = self._read()
            for r in store.get("drafts") or []:
                if r.get("id") == draft_id:
                    r["status"] = "rejected"
                    r["rejection_reason"] = reason or None
                    r["updated_at"] = _now()
                    self._write(store)
                    return Draft(**{**r, "meta": r.get("meta") or {}})
        return None

    async def approve(self, draft_id: str) -> Optional[Draft]:
        """Mark approved and dispatch via the gmail service. On send failure
        the draft moves to ``failed`` so the UI can surface the error."""
        d = await self.get_draft(draft_id)
        if d is None:
            return None
        if d.status not in ("pending", "approved", "failed"):
            return d

        async with self._lock:
            store = self._read()
            for r in store.get("drafts") or []:
                if r.get("id") == draft_id:
                    r["status"] = "approved"
                    r["updated_at"] = _now()
                    self._write(store)
                    break

        sent_id, err = await self._send(d)
        async with self._lock:
            store = self._read()
            for r in store.get("drafts") or []:
                if r.get("id") == draft_id:
                    if sent_id:
                        r["status"] = "sent"
                        r["sent_message_id"] = sent_id
                        r["error"] = None
                    else:
                        r["status"] = "failed"
                        r["error"] = err
                    r["updated_at"] = _now()
                    self._write(store)
                    return Draft(**{**r, "meta": r.get("meta") or {}})
        return None

    async def _send(self, draft: Draft) -> tuple[Optional[str], Optional[str]]:
        """Route the send through the Gmail service. Per-account routing is
        delegated to gmail_service which already takes ``account_id`` on
        multi-account setups; falls back to its default account otherwise."""
        try:
            from app.services.gmail_service import get_gmail_service  # type: ignore
            gmail = get_gmail_service()
            try:
                msg = await gmail.send(
                    account_id=draft.account_id,
                    to=draft.to,
                    subject=draft.subject,
                    body=draft.body,
                    thread_id=draft.thread_id,
                )
                msg_id = (
                    msg.get("id") if isinstance(msg, dict) else getattr(msg, "id", None)
                )
                return str(msg_id) if msg_id else "sent", None
            except TypeError:
                msg = await gmail.send_email(
                    to=draft.to, subject=draft.subject, body=draft.body,
                )
                msg_id = (
                    msg.get("id") if isinstance(msg, dict) else getattr(msg, "id", None)
                )
                return str(msg_id) if msg_id else "sent", None
        except Exception as e:
            logger.warning("draft_pool_send_failed", draft_id=draft.id, error=str(e))
            return None, str(e)

    async def stats(self) -> dict[str, Any]:
        async with self._lock:
            store = self._read()
            drafts = store.get("drafts") or []
        counts: dict[str, int] = {}
        per_account: dict[str, int] = {}
        for r in drafts:
            counts[r.get("status") or "unknown"] = counts.get(r.get("status") or "unknown", 0) + 1
            per_account[r.get("account_id") or "default"] = per_account.get(r.get("account_id") or "default", 0) + 1
        return {
            "total": len(drafts),
            "by_status": counts,
            "by_account": per_account,
        }


@lru_cache(maxsize=1)
def get_email_draft_pool() -> EmailDraftPool:
    return EmailDraftPool()
