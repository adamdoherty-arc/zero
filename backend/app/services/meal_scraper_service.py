"""
Tiered web scraper for the meal manager.

Three providers, tried in order (cheapest first):

1. httpx direct — static pages, JSON APIs
2. Jina Reader (r.jina.ai) — free, handles some JS, returns clean markdown
3. Firecrawl — configurable (ZERO_FIRECRAWL_URL), used only when the first two
   return thin content. Falls through silently when unreachable.

No API keys required for the default stack. A Firecrawl instance becomes a
drop-in upgrade when it's wired up.
"""

from __future__ import annotations

import asyncio
import os
from functools import lru_cache
from typing import Optional
from urllib.parse import quote_plus

import aiohttp
import structlog

logger = structlog.get_logger(__name__)


JINA_READER_BASE = "https://r.jina.ai/"
THIN_CONTENT_THRESHOLD = 400  # chars below this means "not useful, try next tier"


class MealScraperService:
    """Tiered scraper: httpx → Jina → optional Firecrawl."""

    def __init__(self):
        self._firecrawl_url = os.getenv("ZERO_FIRECRAWL_URL", "").rstrip("/")
        self._jina_api_key = os.getenv("JINA_API_KEY", "").strip()  # optional, lifts free-tier quota
        self._timeout = aiohttp.ClientTimeout(total=30)

    async def scrape(self, url: str, *, prefer: str = "auto") -> dict:
        """Scrape a URL and return {'markdown': str, 'provider': str, 'status': 'ok'|'empty'|'error'}."""
        if prefer == "firecrawl" and self._firecrawl_url:
            return await self._via_firecrawl(url)

        # Tier 1: direct httpx
        direct = await self._via_httpx(url)
        if direct["status"] == "ok" and len(direct["markdown"]) >= THIN_CONTENT_THRESHOLD:
            return direct

        # Tier 2: Jina Reader (good JS handling, free tier)
        jina = await self._via_jina(url)
        if jina["status"] == "ok" and len(jina["markdown"]) >= THIN_CONTENT_THRESHOLD:
            return jina

        # Tier 3: Firecrawl if configured
        if self._firecrawl_url:
            firecrawl = await self._via_firecrawl(url)
            if firecrawl["status"] == "ok":
                return firecrawl

        # Return the best of what we got
        candidates = [direct, jina]
        best = max(candidates, key=lambda c: len(c.get("markdown", "")))
        return best

    async def search(self, query: str, *, max_results: int = 10) -> list[dict]:
        """Search via SearXNG (already running in the Zero stack)."""
        searxng_url = os.getenv("SEARXNG_URL", "http://zero-searxng:8080").rstrip("/")
        params = {"q": query, "format": "json", "categories": "general"}
        try:
            async with aiohttp.ClientSession(timeout=self._timeout) as session:
                async with session.get(f"{searxng_url}/search", params=params) as resp:
                    if resp.status != 200:
                        return []
                    data = await resp.json()
                    return [
                        {
                            "title": r.get("title", ""),
                            "url": r.get("url", ""),
                            "snippet": r.get("content", ""),
                            "engine": r.get("engine", ""),
                        }
                        for r in (data.get("results") or [])[:max_results]
                    ]
        except Exception as e:
            logger.warning("meal_scraper_search_failed", query=query, error=str(e))
            return []

    # ------------------------------------------------------------------
    # Providers
    # ------------------------------------------------------------------

    async def _via_httpx(self, url: str) -> dict:
        try:
            async with aiohttp.ClientSession(timeout=self._timeout) as session:
                headers = {
                    "User-Agent": "Mozilla/5.0 (Zero/meal-manager) AppleWebKit/537.36"
                }
                async with session.get(url, headers=headers, allow_redirects=True) as resp:
                    if resp.status >= 400:
                        return {"markdown": "", "provider": "httpx", "status": "error"}
                    content_type = resp.headers.get("content-type", "")
                    body = await resp.text(errors="ignore")
                    # Quick HTML-to-text: strip tags. Jina handles the rich case.
                    if "html" in content_type:
                        body = self._crude_html_to_text(body)
                    return {"markdown": body, "provider": "httpx", "status": "ok"}
        except Exception as e:
            logger.debug("scraper_httpx_error", url=url, error=str(e))
            return {"markdown": "", "provider": "httpx", "status": "error"}

    async def _via_jina(self, url: str) -> dict:
        headers = {"Accept": "text/markdown"}
        if self._jina_api_key:
            headers["Authorization"] = f"Bearer {self._jina_api_key}"
        try:
            async with aiohttp.ClientSession(timeout=self._timeout) as session:
                target = f"{JINA_READER_BASE}{url}"
                async with session.get(target, headers=headers) as resp:
                    if resp.status >= 400:
                        return {"markdown": "", "provider": "jina", "status": "error"}
                    body = await resp.text(errors="ignore")
                    return {"markdown": body, "provider": "jina", "status": "ok"}
        except Exception as e:
            logger.debug("scraper_jina_error", url=url, error=str(e))
            return {"markdown": "", "provider": "jina", "status": "error"}

    async def _via_firecrawl(self, url: str) -> dict:
        if not self._firecrawl_url:
            return {"markdown": "", "provider": "firecrawl", "status": "error"}
        try:
            async with aiohttp.ClientSession(timeout=self._timeout) as session:
                payload = {"url": url, "formats": ["markdown"]}
                async with session.post(
                    f"{self._firecrawl_url}/v1/scrape", json=payload
                ) as resp:
                    if resp.status >= 400:
                        return {"markdown": "", "provider": "firecrawl", "status": "error"}
                    data = await resp.json()
                    md = (data.get("data") or {}).get("markdown") or data.get("markdown") or ""
                    return {"markdown": md, "provider": "firecrawl", "status": "ok"}
        except Exception as e:
            logger.debug("scraper_firecrawl_error", url=url, error=str(e))
            return {"markdown": "", "provider": "firecrawl", "status": "error"}

    @staticmethod
    def _crude_html_to_text(html: str) -> str:
        """Cheap HTML strip — keeps roughly readable text. Jina is preferred for rich pages."""
        import re
        txt = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.IGNORECASE | re.DOTALL)
        txt = re.sub(r"<style[^>]*>.*?</style>", " ", txt, flags=re.IGNORECASE | re.DOTALL)
        txt = re.sub(r"<[^>]+>", " ", txt)
        txt = re.sub(r"\s+", " ", txt)
        return txt.strip()


_singleton: Optional[MealScraperService] = None


def get_meal_scraper() -> MealScraperService:
    global _singleton
    if _singleton is None:
        _singleton = MealScraperService()
    return _singleton
