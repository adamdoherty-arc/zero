"""Character Discovery Service (Phase 024 Character Autopilot).

Four autonomous discovery funnels:
  1. TikTok reference videos (already analyzed by character_reference_video_service)
  2. Wikipedia pageview trending (top characters in "Fictional characters" category)
  3. TMDB trending movies/TV + top-billed character names
  4. Reddit top daily posts (fandom subreddits) with Kimi NER
  5. SearXNG trend scan + Kimi entity extraction

Dedup is central: the same trending name can appear in multiple sources, so every
proposed character is normalized and checked against existing rows before insert.

Global daily cap via settings.character_discovery_daily_cap.
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import datetime, timezone, date
from functools import lru_cache
from typing import Any, Dict, List, Optional

import aiohttp
import structlog
from sqlalchemy import func as sql_func, select
from sqlalchemy.exc import SQLAlchemyError

from app.db.models import CharacterModel, CharacterReferenceVideoModel, TrendingSignalModel
from app.infrastructure.config import get_settings
from app.infrastructure.database import get_session

logger = structlog.get_logger(__name__)


def _normalize_name(name: str) -> str:
    if not name:
        return ""
    n = name.strip().lower()
    # Strip common Wikipedia suffixes like " (character)", " (comics)"
    n = re.sub(r"\s*\([^)]*\)\s*", " ", n).strip()
    # Strip common titles
    for prefix in ("mr. ", "mrs. ", "ms. ", "dr. ", "the "):
        if n.startswith(prefix):
            n = n[len(prefix):]
    return n.strip()


class CharacterDiscoveryService:
    """Autonomous character discovery from 5 free sources."""

    def __init__(self):
        self._semaphore = asyncio.Semaphore(2)
        self._http_timeout = aiohttp.ClientTimeout(total=20)

    # ------------------------------------------------------------------
    # Core: propose + dedup
    # ------------------------------------------------------------------

    async def propose_character(
        self,
        name: str,
        universe: str = "other",
        franchise: Optional[str] = None,
        source: str = "unknown",
        evidence: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Propose a character. Returns {created, character_id, matched_existing}."""
        norm = _normalize_name(name)
        if not norm:
            return {"created": False, "reason": "empty_name"}

        async with get_session() as session:
            # Dedup on lowercased name OR real_name
            result = await session.execute(
                select(CharacterModel).where(
                    sql_func.lower(CharacterModel.name) == norm
                )
            )
            existing = result.scalars().first()
            if existing:
                existing.discovery_hits = (existing.discovery_hits or 0) + 1
                await session.commit()
                return {
                    "created": False,
                    "matched_existing": True,
                    "character_id": existing.id,
                    "name": existing.name,
                }

            # Check daily cap
            settings = get_settings()
            cap = int(getattr(settings, "character_discovery_daily_cap", 10))
            today_start = datetime.combine(date.today(), datetime.min.time(), tzinfo=timezone.utc)
            count_result = await session.execute(
                select(sql_func.count())
                .select_from(CharacterModel)
                .where(
                    CharacterModel.discovery_source.is_not(None),
                    CharacterModel.created_at >= today_start,
                )
            )
            created_today = int(count_result.scalar() or 0)
            if created_today >= cap:
                return {"created": False, "reason": "daily_cap_reached", "cap": cap}

            char_id = f"char-{uuid.uuid4().hex[:12]}"
            char = CharacterModel(
                id=char_id,
                name=name.strip(),
                universe=universe or "other",
                franchise=franchise,
                research_status="pending",
                fact_bank=[],
                status="active",
                discovery_source=source,
                discovery_evidence=evidence or {},
                discovery_hits=1,
            )
            session.add(char)
            await session.commit()

        logger.info(
            "character_discovered",
            character_id=char_id,
            name=name,
            source=source,
        )
        return {"created": True, "character_id": char_id, "name": name.strip()}

    # ------------------------------------------------------------------
    # Source 1: TikTok reference videos
    # ------------------------------------------------------------------

    async def discover_from_reference_videos(self, limit: int = 5) -> Dict[str, Any]:
        """Promote characters proposed by reference video analysis."""
        created = 0
        matched = 0
        async with get_session() as session:
            result = await session.execute(
                select(CharacterReferenceVideoModel)
                .where(
                    CharacterReferenceVideoModel.proposed_character.is_not(None),
                    CharacterReferenceVideoModel.promoted_character_id.is_(None),
                )
                .limit(limit)
            )
            rows = list(result.scalars().all())

        for row in rows:
            proposed = row.proposed_character or {}
            name = proposed.get("name")
            if not name:
                continue
            r = await self.propose_character(
                name=name,
                universe=proposed.get("universe") or "other",
                franchise=proposed.get("franchise"),
                source="tiktok_reference_video",
                evidence={"ref_id": row.id, "tiktok_url": row.tiktok_url},
            )
            if r.get("created"):
                created += 1
                # Link ref video to new character
                async with get_session() as session:
                    fresh = await session.get(CharacterReferenceVideoModel, row.id)
                    if fresh:
                        fresh.character_id = r["character_id"]
                        fresh.promoted_character_id = r["character_id"]
                        await session.commit()
            elif r.get("matched_existing"):
                matched += 1

        return {"source": "tiktok_reference", "created": created, "matched": matched, "scanned": len(rows)}

    # ------------------------------------------------------------------
    # Source 2: Wikipedia pageview trending
    # ------------------------------------------------------------------

    async def discover_from_wikipedia(self, limit: int = 10) -> Dict[str, Any]:
        """Fetch top Wikipedia pageviews and filter to fictional characters."""
        yesterday = (datetime.now(timezone.utc).date()).strftime("%Y/%m/%d")
        url = (
            "https://wikimedia.org/api/rest_v1/metrics/pageviews/top/en.wikipedia.org/all-access/"
            f"{yesterday}"
        )
        created = 0
        matched = 0
        try:
            async with self._semaphore:
                async with aiohttp.ClientSession(timeout=self._http_timeout) as http:
                    async with http.get(url, headers={"User-Agent": "Zero-CharacterDiscovery/1.0"}) as resp:
                        if resp.status != 200:
                            return {"source": "wikipedia", "error": f"http_{resp.status}", "created": 0}
                        data = await resp.json()
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, AttributeError, RuntimeError, TypeError, SQLAlchemyError) as e:
            logger.warning("wikipedia_fetch_failed", error=str(e))
            return {"source": "wikipedia", "error": str(e), "created": 0}

        items = data.get("items", [{}])[0].get("articles", []) if isinstance(data, dict) else []
        # Filter out system pages, dates, meta
        skip_prefixes = ("Main_Page", "Special:", "Wikipedia:", "File:")
        candidates: List[str] = []
        for art in items[:200]:
            title = art.get("article", "")
            if not title or title.startswith(skip_prefixes):
                continue
            # Heuristic: titles with "(character)" or "(comics)" are very likely characters
            if "(character)" in title or "(comics)" in title or "(Marvel" in title or "(DC" in title:
                candidates.append(title)

        for title in candidates[:limit]:
            name = title.replace("_", " ")
            # Guess universe from title suffix
            universe = "other"
            lower = name.lower()
            if "marvel" in lower:
                universe = "marvel"
            elif " (dc" in lower or "dc comics" in lower:
                universe = "dc"
            r = await self.propose_character(
                name=name, universe=universe, source="wikipedia_trending",
                evidence={"title": title, "date": yesterday},
            )
            if r.get("created"):
                created += 1
            elif r.get("matched_existing"):
                matched += 1
            if r.get("reason") == "daily_cap_reached":
                break

        return {"source": "wikipedia", "created": created, "matched": matched, "scanned": len(candidates)}

    # ------------------------------------------------------------------
    # Source 3: TMDB trending
    # ------------------------------------------------------------------

    async def discover_from_tmdb(self, limit: int = 5) -> Dict[str, Any]:
        settings = get_settings()
        api_key = getattr(settings, "tmdp_api_key", None) or getattr(settings, "tmdp_read_access_token", None)
        if not api_key:
            return {"source": "tmdb", "error": "no_api_key", "created": 0}

        created = 0
        matched = 0
        scanned = 0
        endpoints = [
            # Trending (existing)
            ("https://api.themoviedb.org/3/trending/movie/week", "movie"),
            ("https://api.themoviedb.org/3/trending/tv/week", "tv"),
            # Now playing / upcoming / airing (newer content focus)
            ("https://api.themoviedb.org/3/movie/now_playing", "movie"),
            ("https://api.themoviedb.org/3/movie/upcoming", "movie"),
            ("https://api.themoviedb.org/3/tv/airing_today", "tv"),
            ("https://api.themoviedb.org/3/tv/on_the_air", "tv"),
        ]
        try:
            async with self._semaphore:
                async with aiohttp.ClientSession(timeout=self._http_timeout) as http:
                    params = {"api_key": api_key} if not api_key.startswith("eyJ") else {}
                    headers = {"Authorization": f"Bearer {api_key}"} if api_key.startswith("eyJ") else {}
                    for url, kind in endpoints:
                        async with http.get(url, params=params, headers=headers) as resp:
                            if resp.status != 200:
                                continue
                            data = await resp.json()
                        # Derive source label from URL path
                        url_tag = url.rsplit("/", 1)[-1]  # e.g. "week", "now_playing", "upcoming"
                        source_label = f"tmdb_{url_tag}"
                        for item in (data.get("results") or [])[:limit]:
                            scanned += 1
                            item_id = item.get("id")
                            if not item_id:
                                continue
                            cred_url = f"https://api.themoviedb.org/3/{kind}/{item_id}/credits"
                            try:
                                async with http.get(cred_url, params=params, headers=headers) as cresp:
                                    if cresp.status != 200:
                                        continue
                                    credits = await cresp.json()
                            except (ValueError, KeyError, AttributeError, TypeError):
                                continue
                            cast = credits.get("cast", [])[:2]
                            for actor in cast:
                                char_name = actor.get("character")
                                if not char_name or len(char_name) < 2:
                                    continue
                                franchise = item.get("title") or item.get("name")
                                r = await self.propose_character(
                                    name=char_name,
                                    universe="other",
                                    franchise=franchise,
                                    source=source_label,
                                    evidence={"franchise": franchise, "kind": kind, "tmdb_id": item_id},
                                )
                                if r.get("created"):
                                    created += 1
                                elif r.get("matched_existing"):
                                    matched += 1
                                if r.get("reason") == "daily_cap_reached":
                                    return {"source": "tmdb", "created": created, "matched": matched, "scanned": scanned}
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, AttributeError, RuntimeError, TypeError, SQLAlchemyError) as e:
            logger.warning("tmdb_discovery_failed", error=str(e))
            return {"source": "tmdb", "error": str(e), "created": created, "matched": matched}

        return {"source": "tmdb", "created": created, "matched": matched, "scanned": scanned}

    # ------------------------------------------------------------------
    # Source 4: Reddit top posts
    # ------------------------------------------------------------------

    async def discover_from_reddit(self, limit: int = 5) -> Dict[str, Any]:
        subs = ["marvelstudios", "anime", "gaming", "dccomics", "starwars"]
        created = 0
        matched = 0
        scanned = 0
        titles: List[str] = []
        try:
            async with self._semaphore:
                async with aiohttp.ClientSession(timeout=self._http_timeout) as http:
                    for sub in subs:
                        url = f"https://www.reddit.com/r/{sub}/top.json?t=day&limit=15"
                        try:
                            async with http.get(url, headers={"User-Agent": "Zero-CharacterDiscovery/1.0"}) as resp:
                                if resp.status != 200:
                                    continue
                                data = await resp.json()
                        except (ValueError, KeyError, AttributeError, TypeError):
                            continue
                        for post in data.get("data", {}).get("children", []):
                            t = post.get("data", {}).get("title")
                            if t:
                                titles.append(t)
                        scanned += 1
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, AttributeError, RuntimeError, TypeError, SQLAlchemyError) as e:
            logger.warning("reddit_fetch_failed", error=str(e))
            return {"source": "reddit", "error": str(e), "created": 0}

        if not titles:
            return {"source": "reddit", "created": 0, "matched": 0, "scanned": 0}

        # Use Kimi 8k for cheap NER extraction
        names = await self._extract_character_names_via_kimi(titles[:40])
        for name in names[:limit]:
            r = await self.propose_character(
                name=name, source="reddit_trending",
                evidence={"extracted_from": "reddit_top_daily"},
            )
            if r.get("created"):
                created += 1
            elif r.get("matched_existing"):
                matched += 1
            if r.get("reason") == "daily_cap_reached":
                break

        return {"source": "reddit", "created": created, "matched": matched, "scanned": len(titles)}

    # ------------------------------------------------------------------
    # Source 5: SearXNG trend scan
    # ------------------------------------------------------------------

    async def discover_from_searxng(self, limit: int = 5) -> Dict[str, Any]:
        settings = get_settings()
        base = getattr(settings, "searxng_url", "http://zero-searxng:8080")
        url = f"{base}/search"
        params = {"q": "trending fictional character", "format": "json", "categories": "general"}
        created = 0
        matched = 0
        titles: List[str] = []
        try:
            async with self._semaphore:
                async with aiohttp.ClientSession(timeout=self._http_timeout) as http:
                    async with http.get(url, params=params) as resp:
                        if resp.status != 200:
                            return {"source": "searxng", "error": f"http_{resp.status}", "created": 0}
                        data = await resp.json()
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, AttributeError, RuntimeError, TypeError, SQLAlchemyError) as e:
            logger.warning("searxng_fetch_failed", error=str(e))
            return {"source": "searxng", "error": str(e), "created": 0}

        for r in (data.get("results") or [])[:40]:
            t = r.get("title") or r.get("content") or ""
            if t:
                titles.append(t)

        if not titles:
            return {"source": "searxng", "created": 0, "matched": 0, "scanned": 0}

        names = await self._extract_character_names_via_kimi(titles[:40])
        for name in names[:limit]:
            resp = await self.propose_character(
                name=name, source="searxng_trending",
                evidence={"extracted_from": "searxng_general"},
            )
            if resp.get("created"):
                created += 1
            elif resp.get("matched_existing"):
                matched += 1
            if resp.get("reason") == "daily_cap_reached":
                break

        return {"source": "searxng", "created": created, "matched": matched, "scanned": len(titles)}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _extract_character_names_via_kimi(self, texts: List[str]) -> List[str]:
        """Extract fictional character names from a list of titles using Kimi 8k."""
        if not texts:
            return []
        try:
            from app.infrastructure.unified_llm_client import get_unified_llm_client
            client = get_unified_llm_client()
            joined = "\n".join(f"- {t}" for t in texts[:40])
            prompt = (
                "From the following post titles, extract only the names of fictional characters "
                "(superheroes, anime protagonists, movie/TV characters, video game characters). "
                "Return a JSON array of strings. No real people. No places. No franchise names alone.\n\n"
                f"{joined}\n\n"
                'Response format: ["Spider-Man", "Naruto"]. If none, return [].'
            )
            raw = await client.chat(
                prompt=prompt,
                system="You are an entity extractor. Return only a JSON array.",
                task_type="classification",
                temperature=0.0,
                max_tokens=512,
            )
            # Extract first JSON array
            match = re.search(r"\[.*?\]", raw, re.DOTALL)
            if not match:
                return []
            names = json.loads(match.group(0))
            if not isinstance(names, list):
                return []
            # Dedup, keep only strings
            seen = set()
            cleaned: List[str] = []
            for n in names:
                if not isinstance(n, str):
                    continue
                norm = _normalize_name(n)
                if norm and norm not in seen:
                    seen.add(norm)
                    cleaned.append(n.strip())
            return cleaned
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, AttributeError, RuntimeError, TypeError, SQLAlchemyError) as e:
            logger.warning("character_name_extraction_failed", error=str(e))
            return []

    # ------------------------------------------------------------------
    # Orchestration
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Trend-signal-driven discovery (Phase 1 content brain v2)
    # ------------------------------------------------------------------

    async def from_trend_signal(self, signal_id: str) -> Dict[str, Any]:
        """Process a TrendingSignal: elevate linked characters to trending priority,
        or propose new characters when the signal carries a franchise + release date.

        Returns {promoted, created, matched, character_ids}.
        """
        async with get_session() as session:
            res = await session.execute(
                select(TrendingSignalModel).where(TrendingSignalModel.id == signal_id)
            )
            signal = res.scalars().first()
            if signal is None:
                return {"error": "signal_not_found"}

            promoted: List[str] = []
            # Elevate already-linked characters
            for ch_id in (signal.linked_character_ids or []):
                cres = await session.execute(
                    select(CharacterModel).where(CharacterModel.id == ch_id)
                )
                ch = cres.scalars().first()
                if ch is None:
                    continue
                updated = False
                if ch.priority_tier != "trending":
                    ch.priority_tier = "trending"
                    updated = True
                evidence = dict(ch.discovery_evidence or {})
                evidence.setdefault("trend_signals", [])
                if signal.id not in evidence["trend_signals"]:
                    evidence["trend_signals"].append(signal.id)
                    evidence["latest_release_date"] = (
                        signal.release_date.isoformat() if signal.release_date else None
                    )
                    evidence["latest_franchise"] = signal.franchise
                    ch.discovery_evidence = evidence
                    updated = True
                if updated:
                    promoted.append(ch.id)
            await session.commit()

        created = 0
        matched = 0
        character_ids: List[str] = list(signal.linked_character_ids or [])

        # Only propose a new character when nothing was linked and we have a franchise
        # plus a release-bearing signal (avoid flooding from viral/Reddit titles).
        if not character_ids and signal.franchise and signal.signal_type == "release":
            result = await self.propose_character(
                name=signal.franchise,
                universe=signal.universe or "other",
                franchise=signal.franchise,
                source="trend_release",
                evidence={
                    "signal_id": signal.id,
                    "release_date": signal.release_date.isoformat() if signal.release_date else None,
                    "media_type": signal.media_type,
                    "signal_strength": signal.signal_strength,
                },
            )
            if result.get("created"):
                created = 1
                character_ids.append(result["character_id"])
            elif result.get("matched_existing"):
                matched = 1
                character_ids.append(result["character_id"])

        return {
            "signal_id": signal_id,
            "promoted": promoted,
            "created": created,
            "matched": matched,
            "character_ids": character_ids,
        }

    async def run_all_sources(self) -> Dict[str, Any]:
        """Run all 4 bulk discovery sources. Reference videos run on a separate 15-min job."""
        results = await asyncio.gather(
            self.discover_from_wikipedia(limit=10),
            self.discover_from_tmdb(limit=5),
            self.discover_from_reddit(limit=5),
            self.discover_from_searxng(limit=5),
            return_exceptions=True,
        )
        summary: Dict[str, Any] = {"total_created": 0, "total_matched": 0, "sources": {}}
        for r in results:
            if isinstance(r, Exception):
                logger.warning("discovery_source_exception", error=str(r))
                continue
            src = r.get("source", "unknown")
            summary["sources"][src] = r
            summary["total_created"] += r.get("created", 0)
            summary["total_matched"] += r.get("matched", 0)
        return summary


@lru_cache()
def get_character_discovery_service() -> CharacterDiscoveryService:
    return CharacterDiscoveryService()
