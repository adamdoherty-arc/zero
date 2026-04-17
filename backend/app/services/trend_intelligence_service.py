"""Trend Intelligence Service.

Pulls upcoming release calendars and viral trend signals from multiple free sources,
scores them via Kimi for viewer interest, and links them to existing characters /
media titles so the content pipelines can proactively prep carousels 7-14 days
before a drop instead of reacting to its own backlog.

Sources:
  1. TMDB upcoming + on_the_air (requires tmdp_api_key, already in settings)
  2. TVMaze schedule (no key needed, free)
  3. Reddit fandom rising (reuses CharacterDiscoveryService's UA)
  4. SearXNG over trends.google.com / tiktok trending

The service only produces signals — linking and content triggering happen in
scheduler jobs + CharacterDiscoveryService.from_trend_signal().
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

import aiohttp
import structlog
from sqlalchemy import func as sql_func, select
from sqlalchemy.exc import SQLAlchemyError

from app.db.models import (
    TrendingSignalModel,
    CharacterModel,
    MediaTitleModel,
)
from app.infrastructure.config import get_settings
from app.infrastructure.database import get_session

logger = structlog.get_logger(__name__)


SIGNAL_TTL_DAYS = 30  # ADA-inspired: signals decay after 30d
RELEASE_WINDOW_DAYS = 60  # pull up to 60 days ahead for release calendar


def _normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", (title or "").strip()).lower()


def _parse_date(raw: Optional[str]) -> Optional[date]:
    if not raw:
        return None
    try:
        return datetime.strptime(raw[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


class TrendIntelligenceService:
    """Fetch + score + persist trend signals from multiple sources."""

    def __init__(self) -> None:
        self._http_timeout = aiohttp.ClientTimeout(total=20)
        self._semaphore = asyncio.Semaphore(3)

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    async def _upsert_signal(
        self,
        source: str,
        signal_type: str,
        title: str,
        external_id: Optional[str],
        release_date: Optional[date],
        media_type: Optional[str],
        franchise: Optional[str],
        signal_strength: float,
        metadata: Dict[str, Any],
    ) -> Optional[str]:
        """Upsert by (source, external_id). Returns signal_id or None on error."""
        async with get_session() as session:
            if external_id:
                existing_res = await session.execute(
                    select(TrendingSignalModel).where(
                        TrendingSignalModel.source == source,
                        TrendingSignalModel.external_id == external_id,
                    )
                )
                existing = existing_res.scalars().first()
                if existing:
                    existing.signal_strength = signal_strength
                    existing.title = title
                    existing.release_date = release_date
                    existing.media_type = media_type
                    existing.franchise = franchise
                    existing.signal_metadata = metadata
                    existing.expires_at = datetime.now(timezone.utc) + timedelta(days=SIGNAL_TTL_DAYS)
                    await session.commit()
                    return existing.id

            signal_id = f"trend-{uuid.uuid4().hex[:12]}"
            row = TrendingSignalModel(
                id=signal_id,
                source=source,
                signal_type=signal_type,
                title=title,
                franchise=franchise,
                media_type=media_type,
                release_date=release_date,
                signal_strength=signal_strength,
                signal_metadata=metadata,
                external_id=external_id,
                expires_at=datetime.now(timezone.utc) + timedelta(days=SIGNAL_TTL_DAYS),
            )
            session.add(row)
            try:
                await session.commit()
            except SQLAlchemyError as e:
                logger.warning("trend_signal_commit_failed", error=str(e))
                await session.rollback()
                return None
            return signal_id

    # ------------------------------------------------------------------
    # Source: TMDB upcoming + on_the_air (release-aware)
    # ------------------------------------------------------------------

    async def fetch_tmdb_upcoming(self, days_ahead: int = RELEASE_WINDOW_DAYS) -> Dict[str, Any]:
        settings = get_settings()
        api_key = getattr(settings, "tmdp_api_key", None) or getattr(settings, "tmdp_read_access_token", None)
        if not api_key:
            return {"source": "tmdb_upcoming", "error": "no_api_key", "created": 0}

        cutoff = date.today() + timedelta(days=days_ahead)
        endpoints: List[Tuple[str, str, str]] = [
            ("https://api.themoviedb.org/3/movie/upcoming", "movie", "tmdb_upcoming"),
            ("https://api.themoviedb.org/3/tv/on_the_air", "tv_show", "tmdb_on_the_air"),
            ("https://api.themoviedb.org/3/tv/airing_today", "tv_show", "tmdb_airing_today"),
        ]
        created = 0
        skipped = 0
        try:
            async with self._semaphore:
                async with aiohttp.ClientSession(timeout=self._http_timeout) as http:
                    params = {"api_key": api_key} if not api_key.startswith("eyJ") else {}
                    headers = {"Authorization": f"Bearer {api_key}"} if api_key.startswith("eyJ") else {}

                    for url, media_type, source_label in endpoints:
                        try:
                            async with http.get(url, params=params, headers=headers) as resp:
                                if resp.status != 200:
                                    continue
                                data = await resp.json()
                        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
                            logger.warning("tmdb_upcoming_fetch_failed", url=url, error=str(e))
                            continue

                        for item in (data.get("results") or [])[:20]:
                            tmdb_id = item.get("id")
                            title = item.get("title") or item.get("name")
                            rel = _parse_date(item.get("release_date") or item.get("first_air_date"))
                            if not title or not tmdb_id:
                                continue
                            if rel and rel > cutoff:
                                skipped += 1
                                continue

                            popularity = float(item.get("popularity") or 0.0)
                            vote_avg = float(item.get("vote_average") or 0.0)
                            strength = min(100.0, (popularity * 0.7) + (vote_avg * 5.0))
                            signal_id = await self._upsert_signal(
                                source=source_label,
                                signal_type="release" if rel else "trending",
                                title=title,
                                external_id=str(tmdb_id),
                                release_date=rel,
                                media_type=media_type,
                                franchise=title,
                                signal_strength=strength,
                                metadata={
                                    "tmdb_id": tmdb_id,
                                    "popularity": popularity,
                                    "vote_average": vote_avg,
                                    "overview": item.get("overview", "")[:500],
                                    "poster_path": item.get("poster_path"),
                                    "backdrop_path": item.get("backdrop_path"),
                                    "genre_ids": item.get("genre_ids", []),
                                },
                            )
                            if signal_id:
                                created += 1
        except (aiohttp.ClientError, asyncio.TimeoutError, RuntimeError, ValueError) as e:
            logger.warning("tmdb_upcoming_failed", error=str(e))
            return {"source": "tmdb_upcoming", "error": str(e), "created": created}

        logger.info("tmdb_upcoming_fetched", created=created, skipped=skipped)
        return {"source": "tmdb_upcoming", "created": created, "skipped_outside_window": skipped}

    # ------------------------------------------------------------------
    # Source: TVMaze schedule (no key, free)
    # ------------------------------------------------------------------

    async def fetch_tvmaze_schedule(self, days_ahead: int = 14) -> Dict[str, Any]:
        created = 0
        today = date.today()
        try:
            async with self._semaphore:
                async with aiohttp.ClientSession(timeout=self._http_timeout) as http:
                    for delta in range(days_ahead):
                        target = today + timedelta(days=delta)
                        url = f"https://api.tvmaze.com/schedule?date={target.isoformat()}"
                        try:
                            async with http.get(url) as resp:
                                if resp.status != 200:
                                    continue
                                items = await resp.json()
                        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
                            continue

                        for ep in items[:30]:
                            show = ep.get("show") or {}
                            tvmaze_id = show.get("id")
                            name = show.get("name")
                            if not name or not tvmaze_id:
                                continue
                            # Only keep "first aired" premieres to avoid flooding with every episode
                            if ep.get("number") and ep["number"] > 1:
                                continue
                            premiered = _parse_date(show.get("premiered"))
                            rating = ((show.get("rating") or {}).get("average") or 0.0)
                            strength = min(100.0, float(rating) * 10.0 + 30.0)
                            signal_id = await self._upsert_signal(
                                source="tvmaze_schedule",
                                signal_type="release",
                                title=name,
                                external_id=str(tvmaze_id),
                                release_date=target,
                                media_type="tv_show",
                                franchise=name,
                                signal_strength=strength,
                                metadata={
                                    "tvmaze_id": tvmaze_id,
                                    "rating": rating,
                                    "premiered": premiered.isoformat() if premiered else None,
                                    "genres": show.get("genres") or [],
                                    "network": ((show.get("network") or {}).get("name")
                                                or (show.get("webChannel") or {}).get("name")),
                                    "episode_name": ep.get("name"),
                                    "airstamp": ep.get("airstamp"),
                                },
                            )
                            if signal_id:
                                created += 1
        except (aiohttp.ClientError, asyncio.TimeoutError, RuntimeError, ValueError) as e:
            logger.warning("tvmaze_fetch_failed", error=str(e))
            return {"source": "tvmaze_schedule", "error": str(e), "created": created}

        logger.info("tvmaze_schedule_fetched", created=created)
        return {"source": "tvmaze_schedule", "created": created}

    # ------------------------------------------------------------------
    # Source: Reddit rising (reuses UA pattern)
    # ------------------------------------------------------------------

    async def fetch_reddit_rising(self) -> Dict[str, Any]:
        subs = ["movies", "television", "marvelstudios", "popculturechat", "entertainment"]
        created = 0
        try:
            async with self._semaphore:
                async with aiohttp.ClientSession(timeout=self._http_timeout) as http:
                    for sub in subs:
                        url = f"https://www.reddit.com/r/{sub}/rising.json?limit=15"
                        try:
                            async with http.get(
                                url, headers={"User-Agent": "Zero-TrendIntel/1.0"}
                            ) as resp:
                                if resp.status != 200:
                                    continue
                                data = await resp.json()
                        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
                            continue
                        for post in (data.get("data", {}).get("children") or [])[:10]:
                            pd = post.get("data") or {}
                            title = pd.get("title") or ""
                            post_id = pd.get("id")
                            if not title or not post_id:
                                continue
                            ups = int(pd.get("ups") or 0)
                            strength = min(100.0, 30.0 + (ups / 100.0))
                            signal_id = await self._upsert_signal(
                                source="reddit_rising",
                                signal_type="viral",
                                title=title[:280],
                                external_id=post_id,
                                release_date=None,
                                media_type=None,
                                franchise=None,
                                signal_strength=strength,
                                metadata={
                                    "subreddit": sub,
                                    "ups": ups,
                                    "num_comments": pd.get("num_comments", 0),
                                    "permalink": pd.get("permalink"),
                                    "url": pd.get("url"),
                                },
                            )
                            if signal_id:
                                created += 1
        except (aiohttp.ClientError, asyncio.TimeoutError, RuntimeError, ValueError) as e:
            logger.warning("reddit_rising_failed", error=str(e))
            return {"source": "reddit_rising", "error": str(e), "created": created}

        logger.info("reddit_rising_fetched", created=created)
        return {"source": "reddit_rising", "created": created}

    # ------------------------------------------------------------------
    # Source: SearXNG pulse (Google trends proxy)
    # ------------------------------------------------------------------

    async def fetch_searxng_pulse(self, queries: Optional[List[str]] = None) -> Dict[str, Any]:
        settings = get_settings()
        base = getattr(settings, "searxng_url", "http://zero-searxng:8080")
        queries = queries or [
            "upcoming movies this month",
            "new netflix shows releasing",
            "marvel release schedule",
            "viral tiktok trend",
            "trending show right now",
        ]
        created = 0
        try:
            async with self._semaphore:
                async with aiohttp.ClientSession(timeout=self._http_timeout) as http:
                    for q in queries:
                        params = {"q": q, "format": "json", "categories": "general"}
                        try:
                            async with http.get(f"{base}/search", params=params) as resp:
                                if resp.status != 200:
                                    continue
                                data = await resp.json()
                        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
                            continue
                        for r in (data.get("results") or [])[:10]:
                            title = (r.get("title") or "")[:280]
                            link = r.get("url") or ""
                            if not title:
                                continue
                            signal_id = await self._upsert_signal(
                                source="searxng_pulse",
                                signal_type="trending",
                                title=title,
                                external_id=link[:100] if link else None,
                                release_date=None,
                                media_type=None,
                                franchise=None,
                                signal_strength=40.0,  # low baseline, refined by score_signals()
                                metadata={
                                    "query": q,
                                    "url": link,
                                    "content": (r.get("content") or "")[:500],
                                },
                            )
                            if signal_id:
                                created += 1
        except (aiohttp.ClientError, asyncio.TimeoutError, RuntimeError, ValueError) as e:
            logger.warning("searxng_pulse_failed", error=str(e))
            return {"source": "searxng_pulse", "error": str(e), "created": created}

        logger.info("searxng_pulse_fetched", created=created)
        return {"source": "searxng_pulse", "created": created}

    # ------------------------------------------------------------------
    # LLM scoring pass (refines signal_strength for non-release signals)
    # ------------------------------------------------------------------

    async def score_unscored_signals(self, limit: int = 20) -> Dict[str, Any]:
        """Use Kimi to score recently ingested signals that have no score_reasoning."""
        from app.infrastructure.unified_llm_client import get_unified_llm_client

        async with get_session() as session:
            res = await session.execute(
                select(TrendingSignalModel)
                .where(
                    TrendingSignalModel.score_reasoning.is_(None),
                    TrendingSignalModel.source.in_(
                        ["reddit_rising", "searxng_pulse"]
                    ),
                )
                .order_by(TrendingSignalModel.discovered_at.desc())
                .limit(limit)
            )
            rows = list(res.scalars().all())

        if not rows:
            return {"scored": 0}

        client = get_unified_llm_client()
        scored = 0
        for row in rows:
            prompt = (
                "Rate this item for viewer interest 0-100 (how much content engagement it could drive). "
                "Factor: how culturally big the topic is, how timely, how easy to turn into viral content.\n\n"
                f"Title: {row.title}\n"
                f"Source: {row.source}\n"
                f"Context: {json.dumps(row.signal_metadata)[:500]}\n\n"
                'Return JSON: {"score": 0-100, "reason": "one sentence"}.'
            )
            try:
                raw = await client.chat(
                    prompt=prompt,
                    system="You are a pop culture trend analyst. Return only JSON.",
                    task_type="classification",
                    temperature=0.2,
                    max_tokens=200,
                )
                match = re.search(r"\{.*?\}", raw, re.DOTALL)
                if not match:
                    continue
                parsed = json.loads(match.group(0))
                new_score = float(parsed.get("score") or row.signal_strength)
                reason = (parsed.get("reason") or "")[:500]
            except (ValueError, KeyError, AttributeError, TypeError, json.JSONDecodeError) as e:
                logger.debug("trend_scoring_skip", signal_id=row.id, error=str(e))
                continue

            async with get_session() as session:
                res = await session.execute(
                    select(TrendingSignalModel).where(TrendingSignalModel.id == row.id)
                )
                current = res.scalars().first()
                if current is None:
                    continue
                current.signal_strength = max(0.0, min(100.0, new_score))
                current.score_reasoning = reason
                await session.commit()
            scored += 1

        return {"scored": scored, "total_unscored": len(rows)}

    # ------------------------------------------------------------------
    # Linker: attach signal to existing characters / media titles
    # ------------------------------------------------------------------

    async def link_signal(self, signal_id: str) -> Dict[str, Any]:
        """Attach signal to matching character(s) + media_title(s). Create media_title if missing and source is release-bearing."""
        async with get_session() as session:
            sres = await session.execute(
                select(TrendingSignalModel).where(TrendingSignalModel.id == signal_id)
            )
            signal = sres.scalars().first()
            if signal is None:
                return {"error": "signal_not_found"}

            linked_chars: List[str] = list(signal.linked_character_ids or [])
            linked_media: List[str] = list(signal.linked_media_title_ids or [])
            created_media_id: Optional[str] = None
            norm = _normalize_title(signal.title)
            norm_franchise = _normalize_title(signal.franchise or "")

            # 1. Match characters by franchise
            if signal.franchise:
                cres = await session.execute(
                    select(CharacterModel).where(
                        sql_func.lower(CharacterModel.franchise) == norm_franchise
                    ).limit(20)
                )
                for ch in cres.scalars().all():
                    if ch.id not in linked_chars:
                        linked_chars.append(ch.id)

            # 2. Match existing media titles by tmdb_id or title
            mt: Optional[MediaTitleModel] = None
            tmdb_id = (signal.signal_metadata or {}).get("tmdb_id")
            if tmdb_id:
                mres = await session.execute(
                    select(MediaTitleModel).where(MediaTitleModel.tmdb_id == int(tmdb_id))
                )
                mt = mres.scalars().first()

            if mt is None and signal.title:
                mres = await session.execute(
                    select(MediaTitleModel).where(
                        sql_func.lower(MediaTitleModel.title) == norm
                    ).limit(1)
                )
                mt = mres.scalars().first()

            # 3. If release-bearing signal and no media title, create one so the media pipeline can research it
            if mt is None and signal.signal_type == "release" and signal.media_type in ("movie", "tv_show"):
                mt_id = f"media-{uuid.uuid4().hex[:12]}"
                md = signal.signal_metadata or {}
                year = signal.release_date.year if signal.release_date else None
                mt = MediaTitleModel(
                    id=mt_id,
                    media_type=signal.media_type,
                    title=signal.title,
                    year=year,
                    franchise=signal.franchise,
                    universe="other",
                    synopsis=(md.get("overview") or "")[:1000] or None,
                    poster_url=(f"https://image.tmdb.org/t/p/w500{md['poster_path']}"
                                if md.get("poster_path") else None),
                    backdrop_url=(f"https://image.tmdb.org/t/p/w1280{md['backdrop_path']}"
                                  if md.get("backdrop_path") else None),
                    tmdb_id=int(tmdb_id) if tmdb_id else None,
                    research_status="pending",
                    research_data={"seeded_from_trend_signal": signal.id},
                    fact_bank=[],
                    research_sources=[],
                    status="active",
                )
                session.add(mt)
                try:
                    await session.commit()
                    created_media_id = mt_id
                except SQLAlchemyError as e:
                    logger.warning("media_title_seed_failed", signal_id=signal.id, error=str(e))
                    await session.rollback()
                    mt = None

            if mt is not None and mt.id not in linked_media:
                linked_media.append(mt.id)

            # 4. Persist updates on the signal
            signal.linked_character_ids = linked_chars
            signal.linked_media_title_ids = linked_media
            signal.processed_at = datetime.now(timezone.utc)
            await session.commit()

        return {
            "signal_id": signal_id,
            "linked_character_ids": linked_chars,
            "linked_media_title_ids": linked_media,
            "created_media_title_id": created_media_id,
        }

    async def link_unprocessed(self, limit: int = 50) -> Dict[str, Any]:
        async with get_session() as session:
            res = await session.execute(
                select(TrendingSignalModel)
                .where(TrendingSignalModel.processed_at.is_(None))
                .order_by(TrendingSignalModel.discovered_at.desc())
                .limit(limit)
            )
            ids = [row.id for row in res.scalars().all()]

        linked = 0
        for sid in ids:
            result = await self.link_signal(sid)
            if "error" not in result:
                linked += 1
        return {"processed": linked, "candidates": len(ids)}

    # ------------------------------------------------------------------
    # Maintenance: cleanup expired
    # ------------------------------------------------------------------

    async def cleanup_expired(self) -> Dict[str, Any]:
        now = datetime.now(timezone.utc)
        async with get_session() as session:
            res = await session.execute(
                select(TrendingSignalModel).where(TrendingSignalModel.expires_at < now)
            )
            rows = list(res.scalars().all())
            for row in rows:
                await session.delete(row)
            await session.commit()
        return {"deleted": len(rows)}

    # ------------------------------------------------------------------
    # Orchestration: run all sources
    # ------------------------------------------------------------------

    async def run_all_sources(self) -> Dict[str, Any]:
        """Run all signal sources in parallel."""
        results = await asyncio.gather(
            self.fetch_tmdb_upcoming(),
            self.fetch_tvmaze_schedule(),
            self.fetch_reddit_rising(),
            self.fetch_searxng_pulse(),
            return_exceptions=True,
        )
        clean: List[Dict[str, Any]] = []
        for r in results:
            if isinstance(r, Exception):
                clean.append({"error": str(r)})
            else:
                clean.append(r)
        return {"sources": clean}


@lru_cache()
def get_trend_intelligence_service() -> TrendIntelligenceService:
    return TrendIntelligenceService()
