"""
SearXNG Service for free web search.
Uses self-hosted SearXNG meta search engine.
"""

import asyncio
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from functools import lru_cache
import structlog
import httpx

from app.infrastructure.config import get_settings
from app.infrastructure.circuit_breaker import get_circuit_breaker

logger = structlog.get_logger()


@dataclass
class SearchResult:
    """A single search result."""
    title: str
    url: str
    snippet: str
    engine: Optional[str] = None
    img_src: Optional[str] = None


class SearXNGService:
    """
    Service for web search via self-hosted SearXNG.

    SearXNG is a free, self-hosted meta search engine that aggregates
    results from Google, Bing, Brave, and other search engines.
    """

    def __init__(self):
        self.settings = get_settings()
        self.base_url = self.settings.searxng_url
        self.timeout = 30.0
        self._client: Optional[httpx.AsyncClient] = None
        self._breaker = get_circuit_breaker(
            "searxng",
            failure_threshold=5,
            recovery_timeout=60.0,
        )

    @property
    def client(self) -> httpx.AsyncClient:
        """Get or create a persistent HTTP client for connection reuse."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def search(
        self,
        query: str,
        num_results: int = 10,
        categories: Optional[List[str]] = None
    ) -> List[SearchResult]:
        """
        Search the web via SearXNG.

        Args:
            query: Search query string
            num_results: Maximum number of results to return
            categories: Optional list of categories (general, images, news, etc.)

        Returns:
            List of SearchResult objects
        """
        if not query.strip():
            return []

        params = {
            "q": query,
            "format": "json",
            "pageno": 1
        }

        if categories:
            params["categories"] = ",".join(categories)

        async def _do_search() -> List[SearchResult]:
            response = await self.client.get(
                f"{self.base_url}/search",
                params=params
            )

            if response.status_code != 200:
                raise httpx.HTTPStatusError(
                    f"SearXNG returned {response.status_code}",
                    request=response.request,
                    response=response,
                )

            data = response.json()
            results = []

            for r in data.get("results", [])[:num_results]:
                results.append(SearchResult(
                    title=r.get("title", ""),
                    url=r.get("url", ""),
                    snippet=r.get("content", ""),
                    engine=r.get("engine", None),
                    img_src=r.get("img_src", None),
                ))

            logger.debug(
                "searxng_search_complete",
                query=query,
                results=len(results)
            )
            return results

        try:
            return await self._breaker.call(_do_search)
        except httpx.TimeoutException:
            logger.warning("searxng_timeout", query=query)
            return []
        except httpx.ConnectError:
            logger.warning("searxng_connection_error", url=self.base_url)
            return []
        except Exception as e:
            logger.error("searxng_search_error", error=str(e), query=query)
            return []

    async def research_topic(
        self,
        topic: str,
        aspects: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Deep research a topic by searching multiple angles concurrently.

        Args:
            topic: The topic to research
            aspects: Optional list of aspects to research.
                    Defaults to market size, competitors, how to start, revenue.

        Returns:
            Dict with research results organized by aspect
        """
        if aspects is None:
            aspects = [
                "market size 2024",
                "competitors",
                "how to start",
                "revenue potential",
                "pros and cons"
            ]

        research: Dict[str, Any] = {
            "topic": topic,
            "aspects": {},
            "all_results": []
        }

        sem = asyncio.Semaphore(3)

        async def _search_aspect(aspect: str):
            async with sem:
                query = f"{topic} {aspect}"
                return aspect, await self.search(query, num_results=5)

        tasks = [_search_aspect(a) for a in aspects]
        results = await asyncio.gather(*tasks)

        for aspect, aspect_results in results:
            research["aspects"][aspect] = [
                {
                    "title": r.title,
                    "url": r.url,
                    "snippet": r.snippet
                }
                for r in aspect_results
            ]
            research["all_results"].extend(aspect_results)

        logger.info(
            "research_complete",
            topic=topic,
            total_results=len(research["all_results"])
        )

        return research

    def format_research_for_llm(self, research: Dict[str, Any]) -> str:
        """
        Format research results into a string for LLM analysis.

        Args:
            research: Research dict from research_topic()

        Returns:
            Formatted string with research findings
        """
        lines = [f"# Research on: {research['topic']}\n"]

        for aspect, results in research.get("aspects", {}).items():
            lines.append(f"\n## {aspect.title()}\n")

            if not results:
                lines.append("No results found.\n")
                continue

            for r in results[:3]:  # Top 3 per aspect
                lines.append(f"**{r['title']}**")
                if r['snippet']:
                    lines.append(f"{r['snippet'][:300]}...")
                lines.append(f"Source: {r['url']}\n")

        return "\n".join(lines)

    async def health_check(self) -> bool:
        """Check if SearXNG is reachable."""
        try:
            async def _health():
                response = await self.client.get(f"{self.base_url}/healthz")
                return response.status_code == 200

            return await self._breaker.call(_health)
        except Exception:
            try:
                async def _health_fallback():
                    response = await self.client.get(
                        f"{self.base_url}/search",
                        params={"q": "test", "format": "json"}
                    )
                    return response.status_code == 200

                return await self._breaker.call(_health_fallback)
            except Exception:
                return False


@lru_cache()
def get_searxng_service() -> SearXNGService:
    """Get cached SearXNG service instance."""
    return SearXNGService()
