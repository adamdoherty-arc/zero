"""Atomic facts service — citation-grounded ledger writes + reads.

Every published carousel claim cites an ``atomic_facts.id`` via
``[fact_id:NNN]``. The ledger enforces:

- ``trust_tier`` ∈ {1,2,3,4} per the carosel.txt §3 tiered source ledger
- ``sha256(subject || predicate || object || source_url)`` uniqueness, so
  re-ingestion of the same wiki revision is idempotent
- ``cross_source_rule()`` — every published fact requires ≥2 Tier-1/2 sources
  OR a single Tier-1
"""

from __future__ import annotations

import hashlib
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Iterable, Optional

import structlog
from sqlalchemy import select

from app.db.models import AtomicFactModel
from app.infrastructure.database import get_session
from app.models.carousel import AtomicFact, Source, SourceKind, TrustTier

logger = structlog.get_logger(__name__)


def _hash(subject: str, predicate: str, obj: str, url: str) -> str:
    h = hashlib.sha256()
    for part in (subject, predicate, obj, url):
        h.update((part or "").strip().encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


async def upsert(fact: AtomicFact) -> AtomicFact:
    """Idempotent insert keyed on ``sha256``.

    Handles the race where two parallel research calls compute the same hash:
    on ``IntegrityError`` we re-read the existing row and return it.
    """
    sha = fact.sha256 or _hash(fact.subject, fact.predicate, fact.object, fact.source.url)
    async with get_session() as session:
        existing = await session.execute(
            select(AtomicFactModel).where(AtomicFactModel.sha256 == sha)
        )
        row = existing.scalar_one_or_none()
        if row is not None:
            return _to_pydantic(row)

        new = AtomicFactModel(
            id=fact.id or uuid.uuid4().hex,
            subject=fact.subject,
            predicate=fact.predicate,
            object=fact.object,
            source=(fact.source.kind.value if isinstance(fact.source.kind, SourceKind) else fact.source.kind),
            source_url=fact.source.url,
            source_quote=fact.source.quote,
            trust_tier=int(fact.trust_tier),
            entity_type=fact.entity_type,
            entity_id=fact.entity_id,
            franchise=fact.franchise,
            sha256=sha,
            supersedes_id=fact.supersedes_id,
            fetched_at=fact.source.fetched_at or datetime.now(timezone.utc),
        )
        session.add(new)
        try:
            await session.flush()
        except Exception as exc:  # noqa: BLE001 — IntegrityError on parallel insert
            from sqlalchemy.exc import IntegrityError
            if not isinstance(exc, IntegrityError):
                raise
            await session.rollback()
            existing = await session.execute(
                select(AtomicFactModel).where(AtomicFactModel.sha256 == sha)
            )
            row = existing.scalar_one_or_none()
            if row is not None:
                return _to_pydantic(row)
            raise
        return _to_pydantic(new)


async def lookup_ids(ids: Iterable[str]) -> list[AtomicFact]:
    ids = list(ids)
    if not ids:
        return []
    async with get_session() as session:
        rows = (await session.execute(
            select(AtomicFactModel).where(AtomicFactModel.id.in_(ids))
        )).scalars().all()
    return [_to_pydantic(r) for r in rows]


def cross_source_rule(facts: list[AtomicFact]) -> bool:
    """At least one Tier-1 source, OR ≥2 Tier-1/2 sources for the same predicate.

    ``facts`` here are the supporting evidence for a single claim (the same
    subject + predicate). The rule is per-claim, not per-carousel.
    """
    if not facts:
        return False
    tier_counts: dict[int, int] = defaultdict(int)
    for f in facts:
        tier_counts[int(f.trust_tier)] += 1
    if tier_counts.get(1, 0) >= 1:
        return True
    return tier_counts.get(1, 0) + tier_counts.get(2, 0) >= 2


def _to_pydantic(row: AtomicFactModel) -> AtomicFact:
    return AtomicFact(
        id=row.id,
        subject=row.subject,
        predicate=row.predicate,
        object=row.object,
        trust_tier=TrustTier(row.trust_tier),
        source=Source(
            kind=SourceKind(row.source) if row.source in {k.value for k in SourceKind} else SourceKind.OTHER,
            url=row.source_url,
            quote=row.source_quote,
            fetched_at=row.fetched_at,
        ),
        entity_type=row.entity_type,
        entity_id=row.entity_id,
        franchise=row.franchise,
        sha256=row.sha256,
        supersedes_id=row.supersedes_id,
    )


def make_fact(
    *,
    subject: str,
    predicate: str,
    obj: str,
    source_kind: SourceKind | str,
    source_url: str,
    source_quote: Optional[str] = None,
    trust_tier: TrustTier | int = TrustTier.SEMI_STRUCTURED,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    franchise: Optional[str] = None,
) -> AtomicFact:
    """Convenience constructor used by the Researcher activity (Phase 3)."""
    sha = _hash(subject, predicate, obj, source_url)
    kind = source_kind if isinstance(source_kind, SourceKind) else SourceKind(source_kind)
    return AtomicFact(
        id=uuid.uuid4().hex,
        subject=subject,
        predicate=predicate,
        object=obj,
        trust_tier=TrustTier(int(trust_tier)) if not isinstance(trust_tier, TrustTier) else trust_tier,
        source=Source(
            kind=kind,
            url=source_url,
            quote=source_quote,
            fetched_at=datetime.now(timezone.utc),
        ),
        entity_type=entity_type,
        entity_id=entity_id,
        franchise=franchise,
        sha256=sha,
    )
