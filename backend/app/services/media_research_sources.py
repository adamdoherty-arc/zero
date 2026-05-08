"""
Multi-source TV & Movie research service.

Gathers deep research about TV shows and movies from multiple sources:
- TMDB API (primary structured data: cast, crew, seasons, ratings, images)
- Wikipedia (full production history, reception, legacy sections)
- IMDB Trivia (via SearXNG + Firecrawl)
- Rotten Tomatoes (via SearXNG)
- Fandom Wiki (universe-specific deep lore)
- Reddit (r/television, r/movies, show-specific subreddits)
- Entertainment Articles (Screen Rant, Collider, Variety via SearXNG)
"""

import asyncio
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from urllib.parse import quote

import aiohttp
import structlog

from app.infrastructure.config import get_settings

logger = structlog.get_logger()


@dataclass
class MediaResearchFragment:
    """A piece of research data about a TV show or movie."""
    source: str
    content: str
    url: str = ""
    relevance_score: float = 0.5
    fragment_type: str = "trivia"  # trivia, production, behind_scenes, review, cast, plot, quote
    metadata: Dict[str, Any] = field(default_factory=dict)


# Reddit subreddits for media research
MEDIA_REDDIT_SUBS = {
    "tv_show": ["television", "FanTheories", "TVDetails"],
    "movie": ["movies", "FanTheories", "MovieDetails", "TrueFilm"],
}

# Franchise-specific reddit subs
FRANCHISE_REDDIT_SUBS = {
    "Game of Thrones": ["gameofthrones", "asoiaf"],
    "Breaking Bad": ["breakingbad"],
    "Better Call Saul": ["betterCallSaul"],
    "Stranger Things": ["StrangerThings"],
    "The Office": ["DunderMifflin"],
    "The Sopranos": ["thesopranos"],
    "Succession": ["SuccessionTV"],
    "The Walking Dead": ["thewalkingdead"],
    "Lost": ["lost"],
    "Friends": ["howyoudoin"],
    "Seinfeld": ["seinfeld"],
    "The Wire": ["TheWire"],
    "True Detective": ["TrueDetective"],
    "Westworld": ["westworld"],
    "The Mandalorian": ["TheMandalorianTV"],
    "Yellowstone": ["YellowstonePN"],
    "Ted Lasso": ["TedLasso"],
    "Severance": ["SeveranceAppleTVPlus"],
    "The Bear": ["TheBear"],
    "Shogun": ["ShogunTVShow"],
    # Movies / franchises
    "Star Wars": ["StarWars"],
    "Marvel": ["marvelstudios", "Marvel"],
    "DC": ["DC_Cinematic", "DCcomics"],
    "Lord of the Rings": ["lotr", "tolkienfans"],
    "Harry Potter": ["harrypotter"],
    "The Matrix": ["matrix"],
    "Indiana Jones": ["indianajones"],
    "James Bond": ["JamesBond"],
    "Fast and Furious": ["fastandfurious"],
    "Mission Impossible": ["MissionImpossible"],
    "John Wick": ["JohnWick"],
    "Dune": ["dune"],
    "Oppenheimer": ["oppenheimer"],
    "Barbie": ["barbiemovie"],
}

# Fandom wiki domains for media franchises
FRANCHISE_FANDOM_DOMAINS = {
    "Game of Thrones": "gameofthrones.fandom.com",
    "Breaking Bad": "breakingbad.fandom.com",
    "Stranger Things": "strangerthings.fandom.com",
    "The Walking Dead": "walkingdead.fandom.com",
    "Lost": "lostpedia.fandom.com",
    "The Office": "theoffice.fandom.com",
    "Friends": "friends.fandom.com",
    "Seinfeld": "seinfeld.fandom.com",
    "The Wire": "thewire.fandom.com",
    "Westworld": "westworld.fandom.com",
    "Star Wars": "starwars.fandom.com",
    "Marvel": "marvelcinematicuniverse.fandom.com",
    "DC": "dcextendeduniversedc.fandom.com",
    "Lord of the Rings": "lotr.fandom.com",
    "Harry Potter": "harrypotter.fandom.com",
    "The Matrix": "matrix.fandom.com",
    "Dune": "dune.fandom.com",
    "The Mandalorian": "starwars.fandom.com",
}


class MediaResearchService:
    """Gathers research about TV shows and movies from multiple sources."""

    def __init__(self):
        self._settings = get_settings()

    async def research_title(
        self,
        title: str,
        media_type: str,
        year: Optional[int] = None,
        franchise: Optional[str] = None,
        tmdb_id: Optional[int] = None,
    ) -> List[MediaResearchFragment]:
        """Run the full research pipeline for a media title."""
        fragments: List[MediaResearchFragment] = []

        tasks = [
            self._search_tmdb(title, media_type, year, tmdb_id),
            self._search_wikipedia(title, media_type, year),
            self._search_imdb_trivia(title, media_type, year),
            self._search_rotten_tomatoes(title, media_type, year),
            self._search_reddit(title, media_type, franchise),
            self._search_entertainment_articles(title, media_type, year),
        ]

        if franchise:
            tasks.append(self._search_fandom_wiki(title, media_type, franchise))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                logger.warning("media_research_source_failed", error=str(result))
                continue
            if isinstance(result, list):
                fragments.extend(result)

        # Sort by relevance
        fragments.sort(key=lambda f: f.relevance_score, reverse=True)
        return fragments

    async def _search_tmdb(
        self, title: str, media_type: str, year: Optional[int], tmdb_id: Optional[int]
    ) -> List[MediaResearchFragment]:
        """Fetch structured data from TMDB API."""
        fragments = []
        api_key = getattr(self._settings, "TMDB_API_KEY", None) or getattr(self._settings, "ZERO_TMDB_API_KEY", None)
        if not api_key:
            logger.info("tmdb_api_key_not_set_skipping")
            return fragments

        base_url = "https://api.themoviedb.org/3"
        headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}

        try:
            async with aiohttp.ClientSession() as session:
                # Search or direct lookup
                if tmdb_id:
                    endpoint = "tv" if media_type == "tv_show" else "movie"
                    url = f"{base_url}/{endpoint}/{tmdb_id}"
                    async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            fragments.extend(self._parse_tmdb_details(data, media_type))
                else:
                    endpoint = "search/tv" if media_type == "tv_show" else "search/movie"
                    params = {"query": title, "language": "en-US", "page": 1}
                    if year:
                        params["first_air_date_year" if media_type == "tv_show" else "year"] = year

                    async with session.get(url=f"{base_url}/{endpoint}", headers=headers, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                        if resp.status == 200:
                            search_data = await resp.json()
                            results = search_data.get("results", [])
                            if results:
                                top = results[0]
                                detail_type = "tv" if media_type == "tv_show" else "movie"
                                detail_url = f"{base_url}/{detail_type}/{top['id']}"
                                async with session.get(detail_url, headers=headers, params={"append_to_response": "credits,keywords"}, timeout=aiohttp.ClientTimeout(total=15)) as detail_resp:
                                    if detail_resp.status == 200:
                                        data = await detail_resp.json()
                                        fragments.extend(self._parse_tmdb_details(data, media_type))

                # Fetch credits separately if we have a tmdb_id
                if tmdb_id:
                    endpoint = "tv" if media_type == "tv_show" else "movie"
                    credits_url = f"{base_url}/{endpoint}/{tmdb_id}/credits"
                    async with session.get(credits_url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                        if resp.status == 200:
                            credits = await resp.json()
                            cast_lines = []
                            for member in (credits.get("cast") or [])[:20]:
                                name = member.get("name", "")
                                char = member.get("character", "")
                                if name and char:
                                    cast_lines.append(f"{name} as {char}")
                            if cast_lines:
                                fragments.append(MediaResearchFragment(
                                    source="tmdb",
                                    content=f"Cast: {'; '.join(cast_lines)}",
                                    url=f"https://www.themoviedb.org/{endpoint}/{tmdb_id}",
                                    relevance_score=0.9,
                                    fragment_type="cast",
                                ))

        except Exception as e:
            logger.warning("tmdb_research_error", error=str(e), title=title)

        return fragments

    def _parse_tmdb_details(self, data: dict, media_type: str) -> List[MediaResearchFragment]:
        """Parse TMDB detail response into fragments."""
        fragments = []
        tmdb_id = data.get("id")
        endpoint = "tv" if media_type == "tv_show" else "movie"
        url = f"https://www.themoviedb.org/{endpoint}/{tmdb_id}"

        # Overview
        overview = data.get("overview", "")
        if overview:
            fragments.append(MediaResearchFragment(
                source="tmdb", content=f"Overview: {overview}",
                url=url, relevance_score=0.8, fragment_type="plot",
            ))

        # Tagline
        tagline = data.get("tagline", "")
        if tagline:
            fragments.append(MediaResearchFragment(
                source="tmdb", content=f"Tagline: {tagline}",
                url=url, relevance_score=0.6, fragment_type="trivia",
            ))

        # Genres
        genres = [g.get("name", "") for g in data.get("genres", [])]
        if genres:
            fragments.append(MediaResearchFragment(
                source="tmdb", content=f"Genres: {', '.join(genres)}",
                url=url, relevance_score=0.5, fragment_type="production",
            ))

        # TV-specific: seasons info
        if media_type == "tv_show":
            seasons = data.get("seasons", [])
            if seasons:
                season_info = []
                for s in seasons:
                    name = s.get("name", "")
                    ep_count = s.get("episode_count", 0)
                    air_date = s.get("air_date", "")
                    if name:
                        season_info.append(f"{name}: {ep_count} episodes (aired {air_date})")
                if season_info:
                    fragments.append(MediaResearchFragment(
                        source="tmdb", content=f"Seasons: {'; '.join(season_info)}",
                        url=url, relevance_score=0.7, fragment_type="production",
                    ))

            # Networks
            networks = [n.get("name", "") for n in data.get("networks", [])]
            if networks:
                fragments.append(MediaResearchFragment(
                    source="tmdb", content=f"Networks: {', '.join(networks)}",
                    url=url, relevance_score=0.5, fragment_type="production",
                ))

            # Created by
            creators = [c.get("name", "") for c in data.get("created_by", [])]
            if creators:
                fragments.append(MediaResearchFragment(
                    source="tmdb", content=f"Created by: {', '.join(creators)}",
                    url=url, relevance_score=0.7, fragment_type="production",
                ))

        # Movie-specific: budget, revenue, runtime
        if media_type == "movie":
            budget = data.get("budget", 0)
            revenue = data.get("revenue", 0)
            runtime = data.get("runtime", 0)
            parts = []
            if budget:
                parts.append(f"Budget: ${budget:,}")
            if revenue:
                parts.append(f"Box Office: ${revenue:,}")
            if runtime:
                parts.append(f"Runtime: {runtime} minutes")
            if parts:
                fragments.append(MediaResearchFragment(
                    source="tmdb", content=f"Financials: {'; '.join(parts)}",
                    url=url, relevance_score=0.7, fragment_type="production",
                ))

        # Rating
        vote_avg = data.get("vote_average", 0)
        vote_count = data.get("vote_count", 0)
        if vote_avg and vote_count:
            fragments.append(MediaResearchFragment(
                source="tmdb",
                content=f"TMDB Rating: {vote_avg}/10 ({vote_count:,} votes)",
                url=url, relevance_score=0.6, fragment_type="review",
            ))

        # Production companies
        companies = [c.get("name", "") for c in data.get("production_companies", [])]
        if companies:
            fragments.append(MediaResearchFragment(
                source="tmdb", content=f"Production: {', '.join(companies[:5])}",
                url=url, relevance_score=0.5, fragment_type="production",
            ))

        # Keywords
        keywords_data = data.get("keywords", {})
        kw_list = keywords_data.get("keywords", []) or keywords_data.get("results", [])
        if kw_list:
            kw_names = [k.get("name", "") for k in kw_list[:15]]
            fragments.append(MediaResearchFragment(
                source="tmdb", content=f"Keywords: {', '.join(kw_names)}",
                url=url, relevance_score=0.4, fragment_type="trivia",
            ))

        return fragments

    async def _search_wikipedia(
        self, title: str, media_type: str, year: Optional[int]
    ) -> List[MediaResearchFragment]:
        """Fetch Wikipedia article for the title."""
        fragments = []
        search_term = title
        if media_type == "tv_show":
            search_term = f"{title} TV series"
        elif year:
            search_term = f"{title} {year} film"

        try:
            async with aiohttp.ClientSession() as session:
                # Wikipedia REST API
                encoded = quote(search_term)
                url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{encoded}"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        extract = data.get("extract", "")
                        page_url = data.get("content_urls", {}).get("desktop", {}).get("page", "")
                        if extract and len(extract) > 100:
                            fragments.append(MediaResearchFragment(
                                source="wikipedia",
                                content=extract[:2000],
                                url=page_url,
                                relevance_score=0.8,
                                fragment_type="plot",
                            ))
        except Exception as e:
            logger.warning("wikipedia_media_research_error", error=str(e), title=title)

        return fragments

    async def _search_imdb_trivia(
        self, title: str, media_type: str, year: Optional[int]
    ) -> List[MediaResearchFragment]:
        """Search for IMDB trivia via SearXNG."""
        fragments = []
        searxng_url = getattr(self._settings, "searxng_url", None) or getattr(self._settings, "SEARXNG_URL", None) or getattr(self._settings, "ZERO_SEARXNG_URL", None)
        if not searxng_url:
            return fragments

        query = f"{title} IMDB trivia"
        if year:
            query += f" {year}"

        try:
            async with aiohttp.ClientSession() as session:
                params = {"q": query, "format": "json", "engines": "google", "categories": "general"}
                async with session.get(f"{searxng_url}/search", params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        for result in (data.get("results") or [])[:5]:
                            content = result.get("content", "")
                            result_url = result.get("url", "")
                            if content and len(content) > 50:
                                fragments.append(MediaResearchFragment(
                                    source="imdb_trivia",
                                    content=content[:1000],
                                    url=result_url,
                                    relevance_score=0.7,
                                    fragment_type="trivia",
                                ))
        except Exception as e:
            logger.warning("imdb_trivia_research_error", error=str(e), title=title)

        return fragments

    async def _search_rotten_tomatoes(
        self, title: str, media_type: str, year: Optional[int]
    ) -> List[MediaResearchFragment]:
        """Search for Rotten Tomatoes reviews via SearXNG."""
        fragments = []
        searxng_url = getattr(self._settings, "searxng_url", None) or getattr(self._settings, "SEARXNG_URL", None) or getattr(self._settings, "ZERO_SEARXNG_URL", None)
        if not searxng_url:
            return fragments

        query = f"{title} Rotten Tomatoes"
        if year:
            query += f" {year}"

        try:
            async with aiohttp.ClientSession() as session:
                params = {"q": query, "format": "json", "engines": "google", "categories": "general"}
                async with session.get(f"{searxng_url}/search", params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        for result in (data.get("results") or [])[:3]:
                            content = result.get("content", "")
                            result_url = result.get("url", "")
                            if content and "rotten" in result_url.lower():
                                fragments.append(MediaResearchFragment(
                                    source="rotten_tomatoes",
                                    content=content[:1000],
                                    url=result_url,
                                    relevance_score=0.7,
                                    fragment_type="review",
                                ))
        except Exception as e:
            logger.warning("rotten_tomatoes_research_error", error=str(e), title=title)

        return fragments

    async def _search_reddit(
        self, title: str, media_type: str, franchise: Optional[str]
    ) -> List[MediaResearchFragment]:
        """Search Reddit for discussions about the title."""
        fragments = []

        # Determine subreddits
        subs = []
        if franchise and franchise in FRANCHISE_REDDIT_SUBS:
            subs = FRANCHISE_REDDIT_SUBS[franchise]
        elif title in FRANCHISE_REDDIT_SUBS:
            subs = FRANCHISE_REDDIT_SUBS[title]
        else:
            subs = MEDIA_REDDIT_SUBS.get(media_type, ["movies", "television"])

        for sub in subs[:3]:
            try:
                async with aiohttp.ClientSession() as session:
                    url = f"https://www.reddit.com/r/{sub}/search.json"
                    params = {"q": title, "restrict_sr": "on", "sort": "top", "t": "all", "limit": 5}
                    headers = {"User-Agent": "Zero-Research/1.0"}
                    async with session.get(url, params=params, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            posts = data.get("data", {}).get("children", [])
                            for post in posts[:3]:
                                post_data = post.get("data", {})
                                post_title = post_data.get("title", "")
                                selftext = post_data.get("selftext", "")[:500]
                                score = post_data.get("score", 0)
                                permalink = post_data.get("permalink", "")
                                if post_title and score > 10:
                                    content = f"[r/{sub}] {post_title}"
                                    if selftext:
                                        content += f"\n{selftext}"
                                    fragments.append(MediaResearchFragment(
                                        source="reddit",
                                        content=content,
                                        url=f"https://reddit.com{permalink}",
                                        relevance_score=min(0.3 + (score / 5000), 0.8),
                                        fragment_type="fan_theory" if "theory" in post_title.lower() else "trivia",
                                    ))
                            await asyncio.sleep(0.5)  # Rate limit
            except Exception as e:
                logger.warning("reddit_media_research_error", error=str(e), sub=sub)

        return fragments

    async def _search_entertainment_articles(
        self, title: str, media_type: str, year: Optional[int]
    ) -> List[MediaResearchFragment]:
        """Search for entertainment articles via SearXNG."""
        fragments = []
        searxng_url = getattr(self._settings, "searxng_url", None) or getattr(self._settings, "SEARXNG_URL", None) or getattr(self._settings, "ZERO_SEARXNG_URL", None)
        if not searxng_url:
            return fragments

        queries = [
            f"{title} behind the scenes facts",
            f"{title} making of production",
        ]

        try:
            async with aiohttp.ClientSession() as session:
                for query in queries:
                    params = {"q": query, "format": "json", "engines": "google", "categories": "general"}
                    async with session.get(f"{searxng_url}/search", params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            for result in (data.get("results") or [])[:3]:
                                content = result.get("content", "")
                                result_url = result.get("url", "")
                                if content and len(content) > 80:
                                    fragments.append(MediaResearchFragment(
                                        source="entertainment_article",
                                        content=content[:1000],
                                        url=result_url,
                                        relevance_score=0.6,
                                        fragment_type="behind_scenes",
                                    ))
        except Exception as e:
            logger.warning("entertainment_article_research_error", error=str(e), title=title)

        return fragments

    async def _search_fandom_wiki(
        self, title: str, media_type: str, franchise: Optional[str]
    ) -> List[MediaResearchFragment]:
        """Search Fandom wiki for show/movie lore."""
        fragments = []
        domain = None

        if franchise and franchise in FRANCHISE_FANDOM_DOMAINS:
            domain = FRANCHISE_FANDOM_DOMAINS[franchise]
        elif title in FRANCHISE_FANDOM_DOMAINS:
            domain = FRANCHISE_FANDOM_DOMAINS[title]

        if not domain:
            return fragments

        page_title = title.replace(" ", "_")
        url = f"https://{domain}/api.php"

        try:
            async with aiohttp.ClientSession() as session:
                params = {
                    "action": "query",
                    "titles": page_title,
                    "prop": "extracts",
                    "exintro": "true",
                    "format": "json",
                }
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        pages = data.get("query", {}).get("pages", {})
                        for page_id, page_data in pages.items():
                            if page_id == "-1":
                                continue
                            extract = page_data.get("extract", "")
                            if extract and len(extract) > 100:
                                # Strip HTML tags
                                import re
                                clean = re.sub(r'<[^>]+>', '', extract)[:2000]
                                fragments.append(MediaResearchFragment(
                                    source="fandom_wiki",
                                    content=clean,
                                    url=f"https://{domain}/wiki/{page_title}",
                                    relevance_score=0.7,
                                    fragment_type="plot",
                                ))
        except Exception as e:
            logger.warning("fandom_wiki_media_research_error", error=str(e), title=title)

        return fragments

    async def search_tmdb_titles(
        self, query: str, media_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Search TMDB for titles to import. Returns list of search results."""
        api_key = getattr(self._settings, "TMDB_API_KEY", None) or getattr(self._settings, "ZERO_TMDB_API_KEY", None)
        if not api_key:
            return []

        base_url = "https://api.themoviedb.org/3"
        headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
        results = []

        try:
            async with aiohttp.ClientSession() as session:
                # Search both TV and movies if no type specified
                endpoints = []
                if media_type == "tv_show":
                    endpoints = [("search/tv", "tv_show")]
                elif media_type == "movie":
                    endpoints = [("search/movie", "movie")]
                else:
                    endpoints = [("search/tv", "tv_show"), ("search/movie", "movie")]

                for endpoint, mtype in endpoints:
                    params = {"query": query, "language": "en-US", "page": 1}
                    async with session.get(f"{base_url}/{endpoint}", headers=headers, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            for item in (data.get("results") or [])[:10]:
                                title_key = "name" if mtype == "tv_show" else "title"
                                date_key = "first_air_date" if mtype == "tv_show" else "release_date"
                                poster_path = item.get("poster_path", "")
                                results.append({
                                    "tmdb_id": item.get("id"),
                                    "title": item.get(title_key, ""),
                                    "media_type": mtype,
                                    "year": int(item.get(date_key, "0000")[:4]) if item.get(date_key) else None,
                                    "overview": item.get("overview", "")[:300],
                                    "poster_url": f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else None,
                                    "vote_average": item.get("vote_average"),
                                })

        except Exception as e:
            logger.warning("tmdb_search_error", error=str(e), query=query)

        return results

    async def get_tmdb_images(
        self, tmdb_id: int, media_type: str
    ) -> List[Dict[str, Any]]:
        """Fetch images from TMDB for a title."""
        api_key = getattr(self._settings, "TMDB_API_KEY", None) or getattr(self._settings, "ZERO_TMDB_API_KEY", None)
        if not api_key:
            return []

        base_url = "https://api.themoviedb.org/3"
        headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
        images = []

        try:
            async with aiohttp.ClientSession() as session:
                endpoint = "tv" if media_type == "tv_show" else "movie"
                url = f"{base_url}/{endpoint}/{tmdb_id}/images"
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        # Backdrops (landscape, good for slides)
                        for img in (data.get("backdrops") or [])[:10]:
                            path = img.get("file_path", "")
                            if path:
                                images.append({
                                    "url": f"https://image.tmdb.org/t/p/w1280{path}",
                                    "width": img.get("width"),
                                    "height": img.get("height"),
                                    "type": "backdrop",
                                })
                        # Posters
                        for img in (data.get("posters") or [])[:5]:
                            path = img.get("file_path", "")
                            if path:
                                images.append({
                                    "url": f"https://image.tmdb.org/t/p/w500{path}",
                                    "width": img.get("width"),
                                    "height": img.get("height"),
                                    "type": "poster",
                                })
        except Exception as e:
            logger.warning("tmdb_images_error", error=str(e), tmdb_id=tmdb_id)

        return images
