"""
Multi-source character research service.

Gathers deep character research from 5+ sources:
- Fandom Wiki (via Firecrawl for rich markdown, with Fandom API fallback)
- Reddit (public JSON API)
- TV Tropes (via Firecrawl, with SearXNG fallback)
- IMDB Trivia (via SearXNG + Firecrawl)
- Quotes (via SearXNG)
"""

import asyncio
from dataclasses import dataclass, field
from functools import lru_cache
from typing import List, Optional, Dict, Any
from urllib.parse import quote

import aiohttp
import structlog

from app.infrastructure.config import get_settings

logger = structlog.get_logger()


@dataclass
class ResearchFragment:
    """A piece of research data from an external source."""
    source: str
    content: str
    url: str = ""
    relevance_score: float = 0.5
    fragment_type: str = "lore"
    metadata: Dict[str, Any] = field(default_factory=dict)


# Universe-to-fandom-domain mapping (Marvel + DC prioritized)
FANDOM_DOMAINS = {
    "marvel": "marvel.fandom.com",
    "dc": "dc.fandom.com",
    "star_wars": "starwars.fandom.com",
    "lotr": "lotr.fandom.com",
    "harry_potter": "harrypotter.fandom.com",
    "anime": None,
    "gaming": None,
    "tv": None,
    "film": None,
    "other": None,
}

# Reddit subreddits per universe (Marvel + DC prioritized)
REDDIT_SUBS = {
    "marvel": ["marvelstudios", "Marvel", "FanTheories", "MovieDetails"],
    "dc": ["DCcomics", "DC_Cinematic", "FanTheories", "MovieDetails"],
    "star_wars": ["StarWars", "FanTheories", "MovieDetails"],
    "lotr": ["lotr", "tolkienfans", "FanTheories"],
    "harry_potter": ["harrypotter", "FanTheories"],
    "anime": ["anime", "FanTheories"],
    "gaming": ["gaming", "FanTheories"],
    "tv": ["television", "FanTheories"],
    "film": ["movies", "FanTheories", "MovieDetails"],
    "other": ["FanTheories"],
}

# Fandom wiki alternative page titles
FANDOM_ALT_TITLES = {
    "Iron Man": ["Anthony_Stark", "Iron_Man_(Anthony_Stark)"],
    "Spider-Man": ["Peter_Parker", "Spider-Man_(Peter_Parker)"],
    "Black Widow": ["Natasha_Romanoff", "Black_Widow_(Natasha_Romanoff)"],
    "Scarlet Witch": ["Wanda_Maximoff", "Scarlet_Witch"],
    "Doctor Strange": ["Stephen_Strange", "Doctor_Strange"],
    "Green Lantern": ["Hal_Jordan", "Green_Lantern_(Hal_Jordan)"],
    "The Flash": ["Barry_Allen", "Flash_(Barry_Allen)"],
    "Harley Quinn": ["Harleen_Quinzel", "Harley_Quinn"],
    "Darth Vader": ["Anakin_Skywalker", "Darth_Vader"],
}

# TV Tropes franchise mappings
TVTROPES_FRANCHISE = {
    "marvel": "MCU",
    "dc": "DCEU",
    "star_wars": "StarWars",
    "lotr": "TheLordOfTheRings",
    "harry_potter": "HarryPotter",
}


class CharacterResearchSources:
    """Gathers character research from multiple online sources."""

    def __init__(self):
        settings = get_settings()
        self._firecrawl_url = getattr(settings, "firecrawl_url", "")
        self._searxng_url = settings.searxng_url
        self._timeout = aiohttp.ClientTimeout(total=25)
        self._firecrawl_available = None  # Lazy-checked

    async def _check_firecrawl(self) -> bool:
        """Check if Firecrawl is reachable (cached per instance)."""
        if self._firecrawl_available is not None:
            return self._firecrawl_available
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
                async with session.get(f"{self._firecrawl_url}/") as resp:
                    self._firecrawl_available = resp.status == 200
        except (aiohttp.ClientError, asyncio.TimeoutError, ConnectionError, OSError):
            self._firecrawl_available = False
        logger.info("firecrawl_check", available=self._firecrawl_available, url=self._firecrawl_url)
        return self._firecrawl_available

    async def research_from_all_sources(
        self,
        name: str,
        universe: str,
        franchise: Optional[str] = None,
    ) -> List[ResearchFragment]:
        """Run all research sources in parallel, return consolidated fragments."""
        # Check Firecrawl availability once upfront
        await self._check_firecrawl()

        tasks = [
            self._safe_research(self.research_fandom_wiki, name, universe, franchise),
            self._safe_research(self.research_reddit, name, universe, franchise),
            self._safe_research(self.research_tvtropes, name, universe, franchise),
            self._safe_research(self.research_imdb_trivia, name, franchise),
            self._safe_research(self.research_quotes, name, universe),
        ]

        results = await asyncio.gather(*tasks)
        fragments = []
        source_counts = {}
        for result in results:
            fragments.extend(result)
            for f in result:
                source_counts[f.source] = source_counts.get(f.source, 0) + 1

        logger.info(
            "multi_source_research_complete",
            character=name,
            universe=universe,
            total_fragments=len(fragments),
            sources=source_counts,
        )
        return fragments

    async def _safe_research(self, func, *args) -> List[ResearchFragment]:
        """Wrap a research function with timeout and error handling."""
        try:
            return await asyncio.wait_for(func(*args), timeout=25.0)
        except asyncio.TimeoutError:
            logger.warning("research_source_timeout", source=func.__name__)
            return []
        except (aiohttp.ClientError, ValueError, KeyError, ConnectionError, OSError) as e:
            logger.warning("research_source_error", source=func.__name__, error=str(e))
            return []

    async def _firecrawl_scrape(self, url: str, session: aiohttp.ClientSession) -> str:
        """Scrape a URL using Firecrawl, returns markdown content or empty string."""
        payload = {
            "url": url,
            "formats": ["markdown"],
            "onlyMainContent": True,
        }
        async with session.post(
            f"{self._firecrawl_url}/v1/scrape",
            json=payload,
            timeout=aiohttp.ClientTimeout(total=45),
        ) as resp:
            if resp.status != 200:
                return ""
            data = await resp.json()
        return data.get("data", {}).get("markdown", "")

    # -----------------------------------------------------------------------
    # Source 1: Fandom Wiki (Firecrawl primary, REST API fallback)
    # -----------------------------------------------------------------------

    async def research_fandom_wiki(
        self,
        name: str,
        universe: str,
        franchise: Optional[str] = None,
    ) -> List[ResearchFragment]:
        """Fetch character data from Fandom wiki."""
        domain = FANDOM_DOMAINS.get(universe)
        if not domain and franchise:
            slug = franchise.lower().replace(" ", "").replace("'", "")
            domain = f"{slug}.fandom.com"
        if not domain:
            return []

        # Build title candidates
        wiki_names = list(FANDOM_ALT_TITLES.get(name, []))
        wiki_names.append(name.replace(" ", "_"))
        seen = set()
        unique_names = []
        for wn in wiki_names:
            if wn not in seen:
                seen.add(wn)
                unique_names.append(wn)

        # Try Firecrawl first (richer content), then REST API fallback
        if self._firecrawl_available:
            fragments = await self._fandom_via_firecrawl(name, domain, unique_names)
            if fragments:
                return fragments

        return await self._fandom_via_api(name, domain, unique_names)

    async def _fandom_via_firecrawl(
        self, name: str, domain: str, wiki_names: List[str]
    ) -> List[ResearchFragment]:
        """Scrape Fandom wiki via Firecrawl for rich markdown."""
        fragments = []
        async with aiohttp.ClientSession(timeout=self._timeout) as session:
            for wiki_name in wiki_names:
                url = f"https://{domain}/wiki/{wiki_name}"
                try:
                    content = await self._firecrawl_scrape(url, session)
                    if not content or len(content) < 200:
                        continue

                    sections = self._split_markdown_sections(content)
                    for section_name, section_text in sections.items():
                        if len(section_text.strip()) < 50:
                            continue
                        ftype = self._classify_section(section_name)
                        fragments.append(ResearchFragment(
                            source="fandom_wiki",
                            content=section_text[:3000],
                            url=url,
                            relevance_score=0.85,
                            fragment_type=ftype,
                            metadata={"section": section_name, "domain": domain, "method": "firecrawl"},
                        ))
                    if fragments:
                        break
                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    logger.debug("fandom_firecrawl_error", wiki_name=wiki_name, error=str(e))
                    continue
        logger.info("fandom_wiki_firecrawl", character=name, fragments=len(fragments))
        return fragments

    async def _fandom_via_api(
        self, name: str, domain: str, wiki_names: List[str]
    ) -> List[ResearchFragment]:
        """Fetch Fandom wiki via REST API (fallback — less rich but reliable)."""
        fragments = []
        async with aiohttp.ClientSession(timeout=self._timeout) as session:
            for wiki_name in wiki_names:
                try:
                    api_url = f"https://{domain}/api.php"
                    params = {
                        "action": "query",
                        "titles": wiki_name,
                        "prop": "extracts|categories",
                        "explaintext": "1",
                        "exsectionformat": "plain",
                        "format": "json",
                    }
                    async with session.get(api_url, params=params) as resp:
                        if resp.status != 200:
                            continue
                        data = await resp.json()

                    pages = data.get("query", {}).get("pages", {})
                    for page_id, page_data in pages.items():
                        if page_id == "-1":
                            continue
                        content = page_data.get("extract", "")
                        if not content or len(content) < 100:
                            continue

                        page_url = f"https://{domain}/wiki/{wiki_name}"
                        sections = self._split_plaintext_sections(content)
                        for section_name, section_text in sections.items():
                            if len(section_text.strip()) < 50:
                                continue
                            ftype = self._classify_section(section_name)
                            fragments.append(ResearchFragment(
                                source="fandom_wiki",
                                content=section_text[:3000],
                                url=page_url,
                                relevance_score=0.75,
                                fragment_type=ftype,
                                metadata={"section": section_name, "domain": domain, "method": "api"},
                            ))
                        if fragments:
                            break
                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    logger.debug("fandom_api_error", wiki_name=wiki_name, error=str(e))
                    continue
        logger.info("fandom_wiki_api", character=name, fragments=len(fragments))
        return fragments

    # -----------------------------------------------------------------------
    # Source 2: Reddit (Public JSON API)
    # -----------------------------------------------------------------------

    async def research_reddit(
        self,
        name: str,
        universe: str,
        franchise: Optional[str] = None,
    ) -> List[ResearchFragment]:
        """Search Reddit for character discussions, theories, and facts."""
        subs = REDDIT_SUBS.get(universe, ["FanTheories"])
        fragments = []

        async with aiohttp.ClientSession(timeout=self._timeout) as session:
            for sub in subs[:3]:
                try:
                    search_url = (
                        f"https://www.reddit.com/r/{sub}/search.json"
                        f"?q={quote(name)}&sort=top&t=all&limit=5"
                    )
                    headers = {"User-Agent": "ZeroResearch/1.0"}
                    async with session.get(search_url, headers=headers) as resp:
                        if resp.status != 200:
                            continue
                        data = await resp.json()

                    posts = data.get("data", {}).get("children", [])
                    for post in posts:
                        pdata = post.get("data", {})
                        title = pdata.get("title", "")
                        selftext = pdata.get("selftext", "")
                        score = pdata.get("score", 0)
                        permalink = pdata.get("permalink", "")
                        num_comments = pdata.get("num_comments", 0)

                        if score < 10:
                            continue

                        content = f"**{title}**\n\n{selftext[:2000]}" if selftext else title
                        ftype = "fan_theory" if sub == "FanTheories" else "trivia"
                        if "detail" in sub.lower():
                            ftype = "hidden_detail"

                        fragments.append(ResearchFragment(
                            source="reddit",
                            content=content,
                            url=f"https://reddit.com{permalink}",
                            relevance_score=min(1.0, score / 500),
                            fragment_type=ftype,
                            metadata={
                                "subreddit": sub,
                                "score": score,
                                "num_comments": num_comments,
                            },
                        ))
                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    logger.debug("reddit_request_error", sub=sub, error=str(e))
                    continue
                except (ValueError, KeyError) as e:
                    logger.debug("reddit_parse_error", sub=sub, error=str(e))
                    continue

        logger.info("reddit_researched", character=name, fragments=len(fragments))
        return fragments

    # -----------------------------------------------------------------------
    # Source 3: TV Tropes (Firecrawl primary, SearXNG fallback)
    # -----------------------------------------------------------------------

    async def research_tvtropes(
        self,
        name: str,
        universe: str,
        franchise: Optional[str] = None,
    ) -> List[ResearchFragment]:
        """Research character tropes from TV Tropes."""
        if self._firecrawl_available:
            fragments = await self._tvtropes_via_firecrawl(name, universe, franchise)
            if fragments:
                return fragments

        return await self._tvtropes_via_searxng(name, universe, franchise)

    async def _tvtropes_via_firecrawl(
        self, name: str, universe: str, franchise: Optional[str] = None,
    ) -> List[ResearchFragment]:
        """Scrape TV Tropes character page via Firecrawl."""
        clean_name = name.replace(" ", "")
        urls = []

        # Try franchise-specific character page first
        tv_franchise = TVTROPES_FRANCHISE.get(universe)
        if tv_franchise:
            urls.append(f"https://tvtropes.org/pmwiki/pmwiki.php/Characters/{tv_franchise}{clean_name}")
        if franchise:
            clean_franchise = franchise.replace(" ", "")
            urls.append(f"https://tvtropes.org/pmwiki/pmwiki.php/Characters/{clean_franchise}")
        urls.append(f"https://tvtropes.org/pmwiki/pmwiki.php/Main/{clean_name}")

        fragments = []
        async with aiohttp.ClientSession(timeout=self._timeout) as session:
            for url in urls[:3]:
                try:
                    content = await self._firecrawl_scrape(url, session)
                    if not content or len(content) < 200:
                        continue

                    # Extract lines mentioning this character
                    relevant = []
                    for line in content.split("\n"):
                        if name.lower() in line.lower() and len(line) > 30:
                            relevant.append(line.strip())

                    if relevant:
                        fragments.append(ResearchFragment(
                            source="tvtropes",
                            content="\n".join(relevant[:25]),
                            url=url,
                            relevance_score=0.75,
                            fragment_type="trope",
                            metadata={"trope_count": len(relevant), "method": "firecrawl"},
                        ))
                    elif len(content) > 500:
                        # Still useful as general page content
                        fragments.append(ResearchFragment(
                            source="tvtropes",
                            content=content[:3000],
                            url=url,
                            relevance_score=0.6,
                            fragment_type="trope",
                            metadata={"method": "firecrawl", "full_page": True},
                        ))
                    if fragments:
                        break
                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    logger.debug("tvtropes_firecrawl_error", url=url, error=str(e))
                    continue

        logger.info("tvtropes_firecrawl", character=name, fragments=len(fragments))
        return fragments

    async def _tvtropes_via_searxng(
        self, name: str, universe: str, franchise: Optional[str] = None,
    ) -> List[ResearchFragment]:
        """Search for TV Tropes entries via SearXNG (fallback)."""
        fragments = []
        queries = [f"site:tvtropes.org {name} character tropes"]
        if franchise:
            queries.append(f"site:tvtropes.org {franchise} {name}")

        async with aiohttp.ClientSession(timeout=self._timeout) as session:
            for query in queries[:2]:
                try:
                    params = {"q": query, "format": "json"}
                    async with session.get(f"{self._searxng_url}/search", params=params) as resp:
                        if resp.status != 200:
                            continue
                        data = await resp.json()

                    for r in data.get("results", [])[:5]:
                        title = r.get("title", "")
                        snippet = r.get("content", "")
                        url = r.get("url", "")
                        if not snippet or "tvtropes.org" not in url:
                            continue
                        name_parts = name.lower().split()
                        if not any(p in (title + " " + snippet).lower() for p in name_parts):
                            continue
                        fragments.append(ResearchFragment(
                            source="tvtropes",
                            content=f"{title}\n{snippet}",
                            url=url,
                            relevance_score=0.65,
                            fragment_type="trope",
                            metadata={"method": "searxng"},
                        ))
                except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError) as e:
                    logger.debug("tvtropes_searxng_error", error=str(e))
                    continue

        logger.info("tvtropes_searxng", character=name, fragments=len(fragments))
        return fragments

    # -----------------------------------------------------------------------
    # Source 4: IMDB Trivia (SearXNG finds page, Firecrawl scrapes it)
    # -----------------------------------------------------------------------

    async def research_imdb_trivia(
        self,
        name: str,
        franchise: Optional[str] = None,
    ) -> List[ResearchFragment]:
        """Find IMDB trivia about the character."""
        fragments = []

        # Step 1: Find IMDB trivia page via SearXNG
        search_query = f"site:imdb.com {name} trivia"
        if franchise:
            search_query = f"site:imdb.com {name} {franchise} trivia"

        imdb_url = None
        try:
            async with aiohttp.ClientSession(timeout=self._timeout) as session:
                params = {"q": search_query, "format": "json"}
                async with session.get(f"{self._searxng_url}/search", params=params) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        for r in data.get("results", []):
                            url = r.get("url", "")
                            if "imdb.com" in url and "trivia" in url:
                                imdb_url = url
                                break
                            elif "imdb.com" in url and "/title/" in url:
                                imdb_url = url.rstrip("/") + "/trivia"
                                break

                        # Also grab search snippets as trivia fragments
                        for r in data.get("results", [])[:5]:
                            snippet = r.get("content", "")
                            title = r.get("title", "")
                            rurl = r.get("url", "")
                            if snippet and name.lower() in (title + " " + snippet).lower():
                                is_imdb = "imdb.com" in rurl
                                fragments.append(ResearchFragment(
                                    source="imdb" if is_imdb else "trivia_web",
                                    content=f"{title}\n{snippet}",
                                    url=rurl,
                                    relevance_score=0.7 if is_imdb else 0.55,
                                    fragment_type="behind_scenes",
                                    metadata={"method": "searxng"},
                                ))
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError) as e:
            logger.debug("imdb_search_error", error=str(e))

        # Step 2: If Firecrawl available and we found an IMDB URL, scrape it
        if imdb_url and self._firecrawl_available:
            try:
                async with aiohttp.ClientSession(timeout=self._timeout) as session:
                    content = await self._firecrawl_scrape(imdb_url, session)
                    if content and len(content) > 100:
                        # Filter trivia items mentioning the character
                        trivia_items = []
                        for item in content.split("\n"):
                            item = item.strip()
                            if len(item) > 40 and name.lower() in item.lower():
                                trivia_items.append(item)

                        if trivia_items:
                            fragments.append(ResearchFragment(
                                source="imdb",
                                content="\n\n".join(trivia_items[:15]),
                                url=imdb_url,
                                relevance_score=0.8,
                                fragment_type="behind_scenes",
                                metadata={"trivia_count": len(trivia_items), "method": "firecrawl"},
                            ))
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                logger.debug("imdb_firecrawl_error", error=str(e))

        logger.info("imdb_researched", character=name, fragments=len(fragments))
        return fragments

    # -----------------------------------------------------------------------
    # Source 5: Quotes (via SearXNG)
    # -----------------------------------------------------------------------

    async def research_quotes(
        self,
        name: str,
        universe: str,
    ) -> List[ResearchFragment]:
        """Search for famous character quotes and memorable lines."""
        queries = [
            f"{name} famous quotes",
            f"{name} memorable lines {universe}",
        ]

        fragments = []
        async with aiohttp.ClientSession(timeout=self._timeout) as session:
            for query in queries[:2]:
                try:
                    params = {"q": query, "format": "json"}
                    async with session.get(f"{self._searxng_url}/search", params=params) as resp:
                        if resp.status != 200:
                            continue
                        data = await resp.json()

                    for r in data.get("results", [])[:3]:
                        snippet = r.get("content", "")
                        title = r.get("title", "")
                        url = r.get("url", "")
                        if snippet and name.lower() in (snippet + title).lower():
                            fragments.append(ResearchFragment(
                                source="quotes",
                                content=f"{title}\n{snippet}",
                                url=url,
                                relevance_score=0.6,
                                fragment_type="quote",
                                metadata={"query": query},
                            ))
                except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError) as e:
                    logger.debug("quotes_search_error", error=str(e))
                    continue

        logger.info("quotes_researched", character=name, fragments=len(fragments))
        return fragments

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def _split_plaintext_sections(self, text: str) -> Dict[str, str]:
        """Split plaintext content into sections by header-like lines."""
        sections = {}
        current_section = "intro"
        current_content = []

        for line in text.split("\n"):
            stripped = line.strip()
            if (stripped and len(stripped) < 80
                    and not stripped.endswith(".")
                    and stripped == stripped.title()
                    and len(stripped.split()) <= 6):
                if current_content:
                    sections[current_section] = "\n".join(current_content)
                current_section = stripped
                current_content = []
            else:
                current_content.append(line)

        if current_content:
            sections[current_section] = "\n".join(current_content)

        return sections

    def _split_markdown_sections(self, markdown: str) -> Dict[str, str]:
        """Split markdown content into sections by headers."""
        sections = {}
        current_section = "intro"
        current_content = []

        for line in markdown.split("\n"):
            if line.startswith("#"):
                if current_content:
                    sections[current_section] = "\n".join(current_content)
                current_section = line.lstrip("#").strip()
                current_content = []
            else:
                current_content.append(line)

        if current_content:
            sections[current_section] = "\n".join(current_content)

        return sections

    def _classify_section(self, section_name: str) -> str:
        """Classify a wiki section into a fragment type."""
        name_lower = section_name.lower()
        if any(k in name_lower for k in ["biograph", "history", "origin", "early life"]):
            return "lore"
        if any(k in name_lower for k in ["power", "abilit", "skill", "equipment"]):
            return "lore"
        if any(k in name_lower for k in ["relationship", "allies", "enemies", "family"]):
            return "relationship"
        if any(k in name_lower for k in ["trivia", "behind", "production", "note"]):
            return "behind_scenes"
        if any(k in name_lower for k in ["appear", "filmograph", "version"]):
            return "trivia"
        if any(k in name_lower for k in ["quote", "line", "dialogue"]):
            return "quote"
        return "lore"


@lru_cache()
def get_research_sources() -> CharacterResearchSources:
    """Get cached research sources service instance."""
    return CharacterResearchSources()
