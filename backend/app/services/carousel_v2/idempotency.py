"""Idempotency keys for the publish boundary (carosel.txt §6 'Idempotency keys').

key = sha256(carousel_id || sorted(image_sha256s) || caption_hash)

Temporal uses at-least-once execution for activities — the publish call may
fire twice on retry. The first call writes a row to ``idempotency_keys``
with the TikTok ``publish_id``; the second call short-circuits with the
cached response.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

import structlog
from sqlalchemy import select

from app.db.models import IdempotencyKeyModel
from app.infrastructure.database import get_session

logger = structlog.get_logger(__name__)


def make_key(*, carousel_id: str, image_hashes: Iterable[str], caption: str) -> str:
    h = hashlib.sha256()
    h.update((carousel_id or "").encode("utf-8"))
    for img in sorted(image_hashes):
        h.update(b"\x00")
        h.update(img.encode("utf-8"))
    h.update(b"\x00")
    h.update(hashlib.sha256(caption.encode("utf-8")).digest())
    return h.hexdigest()


async def lookup(key: str) -> Optional[dict]:
    async with get_session() as session:
        row = (await session.execute(
            select(IdempotencyKeyModel).where(IdempotencyKeyModel.key == key)
        )).scalar_one_or_none()
    if row is None:
        return None
    return {"publish_id": row.publish_id, "response_payload": row.response_payload}


async def record(
    key: str,
    *,
    scope: str = "tiktok_publish",
    generation_id: Optional[str] = None,
    publish_id: Optional[str] = None,
    response_payload: Optional[dict] = None,
    ttl_days: int = 30,
) -> None:
    expires = datetime.now(timezone.utc) + timedelta(days=ttl_days)
    async with get_session() as session:
        existing = (await session.execute(
            select(IdempotencyKeyModel).where(IdempotencyKeyModel.key == key)
        )).scalar_one_or_none()
        if existing is not None:
            existing.publish_id = publish_id or existing.publish_id
            existing.response_payload = response_payload or existing.response_payload
            existing.expires_at = expires
        else:
            session.add(
                IdempotencyKeyModel(
                    key=key,
                    scope=scope,
                    generation_id=generation_id,
                    publish_id=publish_id,
                    response_payload=response_payload,
                    expires_at=expires,
                )
            )
        await session.flush()
