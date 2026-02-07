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

logger = structlog.get_logger()


@dataclass
class SearchResult:
    """A single search result."""
    title: str
    url: str
    snippet: str
    engine: Optional[str] = None


class SearXNGService:
    """
    Service for web search via self-hosted SearXNG.

    SearXNG is a free, self-hosted meta search engine that aggregates
    results from Google, Bing, DuckDuckGo, and other search engines.
    """

    def __init__(self):
        self.settings = get_settings()
        self.base_url = self.settings.searxng_url
        self.timeout = 30.0

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

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.base_url}/search",
                    params=params
                )

                if response.status_code == 200:
                    data = response.json()
                    results = []

                    for r in data.get("results", [])[:num_results]:
                        results.append(SearchResult(
                            title=r.get("title", ""),
                            url=r.get("url", ""),
                            snippet=r.get("content", ""),
                            engine=r.get("engine", None)
                        ))

                    logger.debug(
                        "searxng_search_complete",
                        query=query,
                        results=len(results)
                    )
                    return results
                else:
                    logger.warning(
                        "searxng_search_failed",
                        status=response.status_code,
                        query=query
                    )
                    return []

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
        Deep research a topic by searching multiple angles.

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

        research = {
            "topic": topic,
            "aspects": {},
            "all_results": []
        }

        for aspect in aspects:
            query = f"{topic} {aspect}"
            results = await self.search(query, num_results=5)

            research["aspects"][aspect] = [
                {
                    "title": r.title,
                    "url": r.url,
                    "snippet": r.snippet
                }
                for r in results
            ]
            research["all_results"].extend(results)

            # Small delay to be nice to the search engine
            await asyncio.sleep(0.5)

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
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/healthz")
                return response.status_code == 200
        except Exception:
            # Try a simple search as fallback
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    response = await client.get(
                        f"{self.base_url}/search",
                        params={"q": "test", "format": "json"}
                    )
                    return response.status_code == 200
            except Exception:
                return False


@lru_cache()
def get_searxng_service() -> SearXNGService:
    """Get cached SearXNG service instance."""
    return SearXNGService()
