"""
Content Inspiration Service.

Discovers viral carousel creators, analyzes their content patterns,
and extracts winning formulas for character content creation.
"""

import asyncio
import json
import secrets
from datetime import datetime, timezone
from functools import lru_cache
from typing import List, Optional, Dict, Any

import aiohttp
import structlog
from sqlalchemy import select, func as sa_func

from app.db.models import ContentInspirationModel
from app.infrastructure.config import get_settings
from app.infrastructure.database import get_session
from app.infrastructure.ollama_client import OllamaClient
from app.models.character_content import ContentInspiration, ContentInspirationCreate

logger = structlog.get_logger()

ANALYSIS_PROMPT = """Analyze this carousel/video content and extract the engagement patterns.

Content from: {platform}
Creator: {creator}
Hook/Title: {hook}
Content: {content}

Provide a JSON analysis:
{{
    "hook_technique": "question|statement|number|shock|curiosity_gap",
    "storytelling_arc": "escalation|comparison|revelation|chronological|mystery",
    "slide_structure": ["hook", "buildup", "fact1", "fact2", "reveal", "cta"],
    "text_overlay_style": "bold_center|bottom_caption|numbered_list|question_answer",
    "engagement_formula": "one sentence describing why this content works",
    "estimated_slide_count": 6,
    "content_category": "character_facts|comparison|hidden_story|behind_scenes|fan_theory",
    "reusable_patterns": [
        "pattern 1 we can copy",
        "pattern 2 we can copy",
        "pattern 3 we can copy"
    ]
}}

Return ONLY valid JSON, no markdown."""


class ContentInspirationService:
    """Discovers and analyzes viral content for inspiration."""

    def __init__(self):
        settings = get_settings()
        self._searxng_url = settings.searxng_url
        self._firecrawl_url = settings.firecrawl_url
        self._ollama = OllamaClient()
        self._timeout = aiohttp.ClientTimeout(total=20)

    async def get_trending_topics(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get trending topics relevant to character content from SearXNG."""
        topics: List[Dict[str, Any]] = []
        queries = [
            "trending movies 2026",
            "new Marvel news",
            "upcoming DC movies",
            "anime trending",
            "viral character facts TikTok",
        ]
        async with aiohttp.ClientSession(timeout=self._timeout) as session:
            for q in queries:
                try:
                    params = {
                        "q": q,
                        "format": "json",
                        "engines": "google",
                        "categories": "general",
                    }
                    async with session.get(
                        f"{self._searxng_url}/search", params=params
                    ) as resp:
                        if resp.status != 200:
                            continue
                        data = await resp.json()

                    for r in data.get("results", [])[:3]:
                        topics.append({
                            "title": r.get("title", ""),
                            "url": r.get("url", ""),
                            "query": q,
                            "snippet": r.get("content", "")[:200],
                        })
                except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, ConnectionError) as e:
                    logger.debug("trending_topic_search_failed", query=q, error=str(e))

        logger.info("trending_topics_fetched", count=len(topics))
        return topics[:limit]

    async def discover_carousel_creators(
        self, niche: str = "character facts"
    ) -> List[ContentInspiration]:
        """Search for top carousel creators on TikTok/Instagram."""
        queries = [
            f"tiktok {niche} carousel viral creator",
            f"instagram {niche} slide post top account",
            f"tiktok superhero facts dark secrets carousel",
            f"tiktok character facts hidden truths viral",
        ]

        discovered = []
        async with aiohttp.ClientSession(timeout=self._timeout) as session:
            for query in queries[:3]:
                try:
                    params = {
                        "q": query,
                        "format": "json",
                        "engines": "google",
                        "categories": "general",
                    }
                    async with session.get(
                        f"{self._searxng_url}/search", params=params
                    ) as resp:
                        if resp.status != 200:
                            continue
                        data = await resp.json()

                    for result in data.get("results", [])[:5]:
                        url = result.get("url", "")
                        title = result.get("title", "")
                        snippet = result.get("content", "")

                        platform = "tiktok" if "tiktok" in url else "instagram" if "instagram" in url else None
                        if not platform:
                            continue

                        # Extract creator handle from URL
                        handle = self._extract_handle(url, platform)

                        insp = await self._save_inspiration(
                            platform=platform,
                            source_url=url,
                            creator_handle=handle,
                            hook_text=title,
                            status="discovered",
                        )
                        if insp:
                            discovered.append(insp)

                except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, ConnectionError) as e:
                    logger.debug("discovery_error", query=query, error=str(e))

        logger.info("creators_discovered", count=len(discovered))
        return discovered

    async def analyze_carousel_reference(
        self, url: str
    ) -> Optional[ContentInspiration]:
        """Analyze a specific carousel URL for patterns."""
        platform = "tiktok" if "tiktok" in url else "instagram" if "instagram" in url else "other"
        handle = self._extract_handle(url, platform)

        # Step 1: Try TikTok oEmbed for metadata
        content_data = {}
        if "tiktok.com" in url:
            content_data = await self._fetch_tiktok_oembed(url)

        # Step 2: Try Firecrawl for full page content
        if not content_data.get("content"):
            scraped = await self._firecrawl_scrape(url)
            if scraped:
                content_data["content"] = scraped
                if not content_data.get("title"):
                    content_data["title"] = scraped[:200]

        if not content_data.get("content") and not content_data.get("title"):
            return None

        # Step 3: LLM analysis of the content
        analysis = await self._analyze_content(
            platform=platform,
            creator=handle or "unknown",
            hook=content_data.get("title", ""),
            content=content_data.get("content", "")[:3000],
        )

        # Step 4: Save
        insp = await self._save_inspiration(
            platform=platform,
            source_url=url,
            creator_handle=handle,
            hook_text=content_data.get("title"),
            slide_count=analysis.get("estimated_slide_count"),
            structure_analysis=analysis,
            patterns_extracted=analysis.get("reusable_patterns", []),
            engagement_metrics=content_data.get("metrics", {}),
            status="analyzed",
        )

        return insp

    async def auto_discover_character_carousels(
        self, character_name: str, limit: int = 10
    ) -> List[ContentInspiration]:
        """Find existing carousels about a specific character."""
        queries = [
            f"tiktok {character_name} facts secrets carousel",
            f"tiktok {character_name} hidden truths dark facts",
            f"instagram {character_name} character facts post",
        ]

        discovered = []
        async with aiohttp.ClientSession(timeout=self._timeout) as session:
            for query in queries:
                try:
                    params = {
                        "q": query,
                        "format": "json",
                        "engines": "google",
                    }
                    async with session.get(
                        f"{self._searxng_url}/search", params=params
                    ) as resp:
                        if resp.status != 200:
                            continue
                        data = await resp.json()

                    for result in data.get("results", [])[:5]:
                        url = result.get("url", "")
                        if "tiktok.com" in url or "instagram.com" in url:
                            insp = await self._save_inspiration(
                                platform="tiktok" if "tiktok" in url else "instagram",
                                source_url=url,
                                creator_handle=self._extract_handle(url, "tiktok"),
                                hook_text=result.get("title"),
                                tags=[character_name.lower()],
                                status="discovered",
                            )
                            if insp:
                                discovered.append(insp)

                    if len(discovered) >= limit:
                        break
                except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, ConnectionError) as e:
                    logger.debug("character_discovery_error", error=str(e))

        return discovered[:limit]

    async def extract_winning_patterns(self) -> Dict[str, Any]:
        """Aggregate all analyzed inspirations into pattern summary."""
        async with get_session() as session:
            result = await session.execute(
                select(ContentInspirationModel).where(
                    ContentInspirationModel.status == "analyzed"
                )
            )
            rows = result.scalars().all()

        if not rows:
            return {"patterns": [], "hook_types": {}, "structures": {}, "total_analyzed": 0}

        hook_types = {}
        structures = {}
        all_patterns = []

        for row in rows:
            analysis = row.structure_analysis or {}
            hook_type = analysis.get("hook_technique", "unknown")
            hook_types[hook_type] = hook_types.get(hook_type, 0) + 1

            arc = analysis.get("storytelling_arc", "unknown")
            structures[arc] = structures.get(arc, 0) + 1

            patterns = row.patterns_extracted or []
            all_patterns.extend([{"pattern": p, "source": row.creator_handle} for p in patterns])

        return {
            "total_analyzed": len(rows),
            "hook_types": dict(sorted(hook_types.items(), key=lambda x: x[1], reverse=True)),
            "storytelling_arcs": dict(sorted(structures.items(), key=lambda x: x[1], reverse=True)),
            "patterns": all_patterns[:30],
            "avg_slide_count": sum(
                (r.slide_count or 0) for r in rows if r.slide_count
            ) / max(1, sum(1 for r in rows if r.slide_count)),
        }

    async def get_pattern_recommendations(
        self, character_name: str, angle: str
    ) -> Dict[str, Any]:
        """Get best patterns for a character + angle combo."""
        patterns = await self.extract_winning_patterns()
        top_hook = list(patterns.get("hook_types", {}).keys())[:1]
        top_arc = list(patterns.get("storytelling_arcs", {}).keys())[:1]

        return {
            "recommended_hook_type": top_hook[0] if top_hook else "curiosity_gap",
            "recommended_arc": top_arc[0] if top_arc else "escalation",
            "patterns_to_use": [p["pattern"] for p in patterns.get("patterns", [])[:5]],
            "optimal_slide_count": int(patterns.get("avg_slide_count", 6)),
        }

    async def list_inspirations(
        self, status: Optional[str] = None, limit: int = 50
    ) -> List[ContentInspiration]:
        """List stored inspirations."""
        async with get_session() as session:
            q = select(ContentInspirationModel).order_by(
                ContentInspirationModel.created_at.desc()
            ).limit(limit)
            if status:
                q = q.where(ContentInspirationModel.status == status)
            result = await session.execute(q)
            rows = result.scalars().all()

        return [self._row_to_model(r) for r in rows]

    # -----------------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------------

    async def _fetch_tiktok_oembed(self, url: str) -> Dict[str, Any]:
        """Fetch TikTok video metadata via oEmbed."""
        try:
            async with aiohttp.ClientSession(timeout=self._timeout) as session:
                oembed_url = f"https://www.tiktok.com/oembed?url={url}"
                async with session.get(oembed_url) as resp:
                    if resp.status != 200:
                        return {}
                    data = await resp.json()
                    return {
                        "title": data.get("title", ""),
                        "content": data.get("title", ""),
                        "metrics": {
                            "author": data.get("author_name", ""),
                            "author_url": data.get("author_url", ""),
                        },
                    }
        except (aiohttp.ClientError, asyncio.TimeoutError, json.JSONDecodeError, ConnectionError):
            return {}

    async def _firecrawl_scrape(self, url: str) -> Optional[str]:
        """Scrape a URL with Firecrawl."""
        try:
            async with aiohttp.ClientSession(timeout=self._timeout) as session:
                payload = {"url": url, "formats": ["markdown"], "onlyMainContent": True}
                async with session.post(
                    f"{self._firecrawl_url}/v1/scrape", json=payload
                ) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json()
                    return data.get("data", {}).get("markdown", "")
        except (aiohttp.ClientError, asyncio.TimeoutError, json.JSONDecodeError, ConnectionError):
            return None

    async def _analyze_content(
        self, platform: str, creator: str, hook: str, content: str
    ) -> Dict[str, Any]:
        """Use Ollama to analyze content patterns."""
        prompt = ANALYSIS_PROMPT.format(
            platform=platform, creator=creator, hook=hook, content=content
        )
        try:
            response = await self._ollama.chat(
                prompt=prompt,
                system="You are a viral content analyst. Return only valid JSON.",
                task_type="analysis",
            )
            text = response.get("content", "") if isinstance(response, dict) else str(response)
            return self._parse_json(text)
        except (ValueError, json.JSONDecodeError, TimeoutError, ConnectionError) as e:
            logger.warning("analysis_error", error=str(e))
            return {}

    async def _save_inspiration(self, **kwargs) -> Optional[ContentInspiration]:
        """Save an inspiration to the database."""
        try:
            insp_id = f"ci-{secrets.token_hex(12)}"
            row = ContentInspirationModel(
                id=insp_id,
                platform=kwargs.get("platform", "tiktok"),
                source_url=kwargs.get("source_url"),
                creator_handle=kwargs.get("creator_handle"),
                hook_text=kwargs.get("hook_text"),
                slide_count=kwargs.get("slide_count"),
                structure_analysis=kwargs.get("structure_analysis"),
                patterns_extracted=kwargs.get("patterns_extracted", []),
                engagement_metrics=kwargs.get("engagement_metrics", {}),
                tags=kwargs.get("tags", []),
                status=kwargs.get("status", "pending"),
                analyzed_at=datetime.now(timezone.utc) if kwargs.get("status") == "analyzed" else None,
            )
            async with get_session() as session:
                session.add(row)
                await session.flush()
            return self._row_to_model(row)
        except (OSError, ValueError, RuntimeError) as e:
            logger.warning("save_inspiration_error", error=str(e))
            return None

    def _extract_handle(self, url: str, platform: str) -> Optional[str]:
        """Extract creator handle from URL."""
        import re
        if platform == "tiktok":
            match = re.search(r"tiktok\.com/@([^/?\s]+)", url)
            return match.group(1) if match else None
        if platform == "instagram":
            match = re.search(r"instagram\.com/([^/?\s]+)", url)
            return match.group(1) if match else None
        return None

    def _parse_json(self, text: str) -> Dict[str, Any]:
        """Extract JSON from LLM response."""
        # Try to find JSON block
        for start, end in [("{", "}"), ("[", "]")]:
            idx_start = text.find(start)
            idx_end = text.rfind(end)
            if idx_start >= 0 and idx_end > idx_start:
                try:
                    return json.loads(text[idx_start:idx_end + 1])
                except json.JSONDecodeError:
                    continue
        return {}

    def _row_to_model(self, row: ContentInspirationModel) -> ContentInspiration:
        """Convert ORM row to Pydantic model."""
        return ContentInspiration(
            id=row.id,
            platform=row.platform,
            source_url=row.source_url,
            creator_handle=row.creator_handle,
            content_type=row.content_type,
            hook_text=row.hook_text,
            slide_count=row.slide_count,
            structure_analysis=row.structure_analysis,
            engagement_metrics=row.engagement_metrics or {},
            tags=row.tags or [],
            patterns_extracted=row.patterns_extracted or [],
            status=row.status,
            created_at=row.created_at,
            analyzed_at=row.analyzed_at,
        )


@lru_cache()
def get_content_inspiration_service() -> ContentInspirationService:
    """Get cached inspiration service instance."""
    return ContentInspirationService()
