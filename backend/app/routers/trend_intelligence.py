"""Trend Intelligence router.

Surfaces upcoming release calendar + viral signals for proactive content prep.
"""

from datetime import date, datetime, timedelta, timezone
from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func as sql_func, select

from app.db.models import TrendingSignalModel
from app.infrastructure.auth import require_auth
from app.infrastructure.database import get_session
from app.models.trending_signals import (
    TrendingSignal,
    TrendingSignalSummary,
    UpcomingRelease,
    TrendRefreshResponse,
    TrendLinkResponse,
)
from app.services.trend_intelligence_service import get_trend_intelligence_service

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/trends", tags=["Trend Intelligence"], dependencies=[Depends(require_auth)])


def _to_summary(row: TrendingSignalModel) -> TrendingSignalSummary:
    return TrendingSignalSummary(
        id=row.id,
        source=row.source,
        signal_type=row.signal_type,
        title=row.title,
        franchise=row.franchise,
        media_type=row.media_type,
        release_date=row.release_date,
        signal_strength=row.signal_strength,
        linked_character_count=len(row.linked_character_ids or []),
        linked_media_title_count=len(row.linked_media_title_ids or []),
        triggered_content_at=row.triggered_content_at,
        discovered_at=row.discovered_at,
    )


def _to_full(row: TrendingSignalModel) -> TrendingSignal:
    return TrendingSignal(
        id=row.id,
        source=row.source,
        signal_type=row.signal_type,
        title=row.title,
        franchise=row.franchise,
        universe=row.universe,
        media_type=row.media_type,
        release_date=row.release_date,
        signal_strength=row.signal_strength,
        score_reasoning=row.score_reasoning,
        metadata=row.signal_metadata or {},
        external_id=row.external_id,
        linked_character_ids=list(row.linked_character_ids or []),
        linked_media_title_ids=list(row.linked_media_title_ids or []),
        processed_at=row.processed_at,
        triggered_content_at=row.triggered_content_at,
        discovered_at=row.discovered_at,
        expires_at=row.expires_at,
    )


@router.get("/signals", response_model=List[TrendingSignalSummary])
async def list_signals(
    source: Optional[str] = None,
    signal_type: Optional[str] = None,
    min_strength: float = 0.0,
    days: int = 7,
    limit: int = 50,
) -> List[TrendingSignalSummary]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    async with get_session() as session:
        stmt = select(TrendingSignalModel).where(
            TrendingSignalModel.discovered_at >= cutoff,
            TrendingSignalModel.signal_strength >= min_strength,
        )
        if source:
            stmt = stmt.where(TrendingSignalModel.source == source)
        if signal_type:
            stmt = stmt.where(TrendingSignalModel.signal_type == signal_type)
        stmt = stmt.order_by(TrendingSignalModel.signal_strength.desc()).limit(limit)
        res = await session.execute(stmt)
        rows = list(res.scalars().all())
    return [_to_summary(r) for r in rows]


@router.get("/upcoming-releases", response_model=List[UpcomingRelease])
async def upcoming_releases(
    days_ahead: int = Query(14, ge=1, le=90),
    min_strength: float = 0.0,
    limit: int = 50,
) -> List[UpcomingRelease]:
    today = date.today()
    cutoff = today + timedelta(days=days_ahead)
    async with get_session() as session:
        res = await session.execute(
            select(TrendingSignalModel)
            .where(
                TrendingSignalModel.release_date.is_not(None),
                TrendingSignalModel.release_date >= today,
                TrendingSignalModel.release_date <= cutoff,
                TrendingSignalModel.signal_strength >= min_strength,
            )
            .order_by(TrendingSignalModel.release_date.asc(), TrendingSignalModel.signal_strength.desc())
            .limit(limit)
        )
        rows = list(res.scalars().all())
    out: List[UpcomingRelease] = []
    for r in rows:
        rel = r.release_date
        if rel is None:
            continue
        out.append(
            UpcomingRelease(
                signal_id=r.id,
                title=r.title,
                franchise=r.franchise,
                media_type=r.media_type,
                release_date=rel,
                days_until=(rel - today).days,
                signal_strength=r.signal_strength,
                linked_character_ids=list(r.linked_character_ids or []),
                linked_media_title_ids=list(r.linked_media_title_ids or []),
                triggered_content_at=r.triggered_content_at,
            )
        )
    return out


@router.get("/signals/{signal_id}", response_model=TrendingSignal)
async def get_signal(signal_id: str) -> TrendingSignal:
    async with get_session() as session:
        res = await session.execute(
            select(TrendingSignalModel).where(TrendingSignalModel.id == signal_id)
        )
        row = res.scalars().first()
    if row is None:
        raise HTTPException(status_code=404, detail="signal_not_found")
    return _to_full(row)


@router.post("/refresh", response_model=TrendRefreshResponse)
async def refresh_signals(sources: Optional[List[str]] = None) -> TrendRefreshResponse:
    """Manual trigger to fetch from all (or listed) sources. Runs inline."""
    svc = get_trend_intelligence_service()
    triggered: List[str] = []
    errors = {}
    mapping = {
        "tmdb_upcoming": svc.fetch_tmdb_upcoming,
        "tvmaze_schedule": svc.fetch_tvmaze_schedule,
        "reddit_rising": svc.fetch_reddit_rising,
        "searxng_pulse": svc.fetch_searxng_pulse,
    }
    targets = sources or list(mapping.keys())
    for name in targets:
        fn = mapping.get(name)
        if fn is None:
            errors[name] = "unknown_source"
            continue
        try:
            await fn()
            triggered.append(name)
        except Exception as e:
            errors[name] = str(e)
    return TrendRefreshResponse(triggered=triggered, errors=errors)


@router.post("/signals/{signal_id}/link", response_model=TrendLinkResponse)
async def link_signal(signal_id: str) -> TrendLinkResponse:
    svc = get_trend_intelligence_service()
    result = await svc.link_signal(signal_id)
    if result.get("error"):
        raise HTTPException(status_code=404, detail=result["error"])
    return TrendLinkResponse(
        signal_id=signal_id,
        linked_character_ids=result.get("linked_character_ids", []),
        linked_media_title_ids=result.get("linked_media_title_ids", []),
        created_media_title_id=result.get("created_media_title_id"),
    )


@router.post("/link-unprocessed")
async def link_unprocessed(limit: int = 50) -> dict:
    svc = get_trend_intelligence_service()
    return await svc.link_unprocessed(limit=limit)


@router.post("/score-unscored")
async def score_unscored(limit: int = 20) -> dict:
    svc = get_trend_intelligence_service()
    return await svc.score_unscored_signals(limit=limit)
