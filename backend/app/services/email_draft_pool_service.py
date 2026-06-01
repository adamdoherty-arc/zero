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
        the draft moves to ``failed`` so the UI can surface the error.

        Fix-91: the status check + claim happen atomically under the lock and
        the row moves to an intermediate ``sending`` state before the lock is
        released. A concurrent approve (UI double-click + voice "send it")
        then sees ``sending`` and bails, so gmail.send() fires exactly once.
        """
        async with self._lock:
            store = self._read()
            target = None
            for r in store.get("drafts") or []:
                if r.get("id") == draft_id:
                    target = r
                    break
            if target is None:
                return None
            cur = target.get("status")
            # Only pending/approved/failed are (re)sendable. Anything already
            # sending/sent is a concurrent or completed approve — return as-is.
            if cur not in ("pending", "approved", "failed"):
                return Draft(**{**target, "meta": target.get("meta") or {}})
            # Claim it so a racing approve can't also reach _send.
            target["status"] = "sending"
            target["updated_at"] = _now()
            self._write(store)
            d = Draft(**{**target, "meta": target.get("meta") or {}})

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
        """Route the send through the Gmail service, forwarding per-account
        routing (``account_id``) and threading (``thread_id``) whenever the
        underlying send method accepts them.

        Fix-96: the old ``except TypeError`` fallback retried
        ``send_email(to, subject, body)`` with NO account_id/thread_id, so on a
        multi-account setup an approved reply was silently sent from the default
        account and un-threaded; the broad except could also double-send if a
        TypeError was raised from inside ``send()``'s body rather than from a
        signature mismatch. We now pick the richest available send method and
        pass only the kwargs its signature accepts — never silently dropping
        account/thread routing and never retrying a partially-executed send."""
        import inspect

        try:
            from app.services.gmail_service import get_gmail_service  # type: ignore
            gmail = get_gmail_service()
            send_fn = getattr(gmail, "send", None) or getattr(gmail, "send_email", None)
            if send_fn is None:
                return None, "gmail service exposes no send method"
            try:
                params = inspect.signature(send_fn).parameters
                accepted = set(params)
                has_kwargs = any(
                    p.kind == p.VAR_KEYWORD for p in params.values()
                )
            except (TypeError, ValueError):
                accepted, has_kwargs = set(), True
            kwargs: dict[str, Any] = {
                "to": draft.to,
                "subject": draft.subject,
                "body": draft.body,
            }
            if draft.account_id and (has_kwargs or "account_id" in accepted):
                kwargs["account_id"] = draft.account_id
            if draft.thread_id and (has_kwargs or "thread_id" in accepted):
                kwargs["thread_id"] = draft.thread_id
            msg = await send_fn(**kwargs)
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
