"""Competitor Content Service (Phase 3b of Content Brain v2).

Scrapes winning public hooks/captions from TikTok / YouTube Shorts / Instagram
Reels via SearXNG (respecting robots.txt). Feeds two downstream consumers:
  1. Strategist role in content_swarm_service (style exemplars)
  2. prompt_breeder_service (mutation hints from top samples)

30-day decay via expires_at so stale trends don't bias the learner.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

import aiohttp
import structlog
from sqlalchemy import select

from app.db.models import CompetitorContentSampleModel
from app.infrastructure.config import get_settings
from app.infrastructure.database import get_session

logger = structlog.get_logger(__name__)


DEFAULT_NICHES = ["marvel", "anime", "star_wars", "harry_potter", "gaming", "tv_show"]
SAMPLE_TTL_DAYS = 30
_HTTP_TIMEOUT = aiohttp.ClientTimeout(total=20)


def _estimate_engagement(views: Optional[int], likes: Optional[int], comments: Optional[int]) -> Optional[float]:
    if not views or views <= 0:
        return None
    interactions = (likes or 0) + (comments or 0)
    return round(interactions / views, 4)


# Lightweight heuristic for pulling view counts out of SearXNG titles/snippets
_NUM_RE = re.compile(r"([\d.]+)\s*([kmb])?(?:\s*views)?", re.IGNORECASE)


def _parse_views(text: str) -> Optional[int]:
    if not text:
        return None
    text_lower = text.lower()
    if "view" not in text_lower and "likes" not in text_lower:
        return None
    match = _NUM_RE.search(text)
    if not match:
        return None
    try:
        num = float(match.group(1))
        mult = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}.get(match.group(2) or "", 1)
        return int(num * mult)
    except (ValueError, TypeError):
        return None


class CompetitorContentService:
    def __init__(self) -> None:
        self._semaphore = asyncio.Semaphore(3)

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------

    async def scrape_niche(self, niche: str, limit: int = 20) -> Dict[str, Any]:
        """SearXNG queries for winning short-form content in a niche. Upserts into DB."""
        settings = get_settings()
        base = getattr(settings, "searxng_url", "http://zero-searxng:8080")
        queries: List[Tuple[str, str]] = [
            (f"site:tiktok.com {niche} million views", "tiktok"),
            (f"site:youtube.com/shorts {niche} viral", "youtube"),
            (f"site:instagram.com/reel {niche} top post", "instagram"),
        ]
        created = 0
        errors: List[str] = []
        expires_at = datetime.now(timezone.utc) + timedelta(days=SAMPLE_TTL_DAYS)

        try:
            async with self._semaphore:
                async with aiohttp.ClientSession(timeout=_HTTP_TIMEOUT) as http:
                    for query, platform in queries:
                        params = {"q": query, "format": "json", "categories": "general"}
                        try:
                            async with http.get(f"{base}/search", params=params) as resp:
                                if resp.status != 200:
                                    errors.append(f"{platform}:http_{resp.status}")
                                    continue
                                data = await resp.json()
                        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
                            errors.append(f"{platform}:{type(e).__name__}")
                            continue

                        for r in (data.get("results") or [])[:limit]:
                            title = (r.get("title") or "").strip()
                            snippet = (r.get("content") or "").strip()
                            url = (r.get("url") or "").strip()
                            if not title or not url:
                                continue
                            view_count = _parse_views(title) or _parse_views(snippet)
                            engagement = _estimate_engagement(view_count, None, None)
                            sample_id = f"comp-{uuid.uuid4().hex[:12]}"
                            async with get_session() as session:
                                # dedup by url
                                ex = await session.execute(
                                    select(CompetitorContentSampleModel).where(
                                        CompetitorContentSampleModel.url == url
                                    )
                                )
                                if ex.scalars().first() is not None:
                                    continue
                                row = CompetitorContentSampleModel(
                                    id=sample_id,
                                    niche=niche,
                                    platform=platform,
                                    hook_text=title[:500],
                                    caption=snippet[:1000] if snippet else None,
                                    url=url,
                                    creator_handle=None,
                                    view_count=view_count,
                                    like_count=None,
                                    comment_count=None,
                                    engagement_rate=engagement,
                                    sample_metadata={"query": query, "raw_title": title[:500]},
                                    expires_at=expires_at,
                                )
                                session.add(row)
                                await session.commit()
                            created += 1
        except (aiohttp.ClientError, asyncio.TimeoutError, RuntimeError, ValueError) as e:
            logger.warning("competitor_scrape_failed", niche=niche, error=str(e))
            errors.append(f"outer:{type(e).__name__}")

        logger.info("competitor_scrape_done", niche=niche, created=created, errors=errors)
        return {"niche": niche, "created": created, "errors": errors}

    async def scrape_all(self, niches: Optional[List[str]] = None, per_niche: int = 20) -> Dict[str, Any]:
        niches = niches or DEFAULT_NICHES
        results = []
        for n in niches:
            results.append(await self.scrape_niche(n, limit=per_niche))
        return {"results": results}

    # ------------------------------------------------------------------
    # Query helpers (for swarm + breeder consumers)
    # ------------------------------------------------------------------

    async def top_samples(self, niche: str, limit: int = 10) -> List[Dict[str, Any]]:
        now = datetime.now(timezone.utc)
        async with get_session() as session:
            res = await session.execute(
                select(CompetitorContentSampleModel)
                .where(
                    CompetitorContentSampleModel.niche == niche,
                    (CompetitorContentSampleModel.expires_at.is_(None))
                    | (CompetitorContentSampleModel.expires_at > now),
                )
                .order_by(CompetitorContentSampleModel.engagement_rate.desc().nullslast())
                .limit(limit)
            )
            rows = list(res.scalars().all())
        return [
            {
                "id": r.id,
                "niche": r.niche,
                "platform": r.platform,
                "hook_text": r.hook_text,
                "caption": r.caption,
                "view_count": r.view_count,
                "engagement_rate": r.engagement_rate,
                "url": r.url,
            }
            for r in rows
        ]

    async def cleanup_expired(self) -> Dict[str, Any]:
        now = datetime.now(timezone.utc)
        async with get_session() as session:
            res = await session.execute(
                select(CompetitorContentSampleModel).where(
                    CompetitorContentSampleModel.expires_at < now
                )
            )
            rows = list(res.scalars().all())
            for row in rows:
                await session.delete(row)
            await session.commit()
        return {"deleted": len(rows)}


@lru_cache()
def get_competitor_content_service() -> CompetitorContentService:
    return CompetitorContentService()
