"""
Multi-source character research service.

Gathers deep character research from 8 sources:
- Fandom Wiki (via Firecrawl for rich markdown, with Fandom API fallback)
- Reddit (public JSON API)
- TV Tropes (via Firecrawl, with SearXNG fallback)
- IMDB Trivia (via SearXNG + Firecrawl)
- Quotes (via SearXNG)
- Entertainment Articles (Screen Rant, CBR, etc. via SearXNG + Firecrawl)
- Wikipedia Deep (full article scrape via Firecrawl with section splitting)
- Power Databases (Comic Vine, SuperHeroDB via SearXNG + Firecrawl)
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
# Multi-franchise universes (anime, gaming, tv, film) fall through to
# FRANCHISE_FANDOM_OVERRIDES, then finally a `{slug}.fandom.com` autoguess.
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

# Franchise-specific fandom domain overrides (used when automatic slug is wrong
# or when multiple characters share a franchise with a non-obvious wiki slug).
FRANCHISE_FANDOM_OVERRIDES = {
    # Prestige TV
    "Game of Thrones": "gameofthrones.fandom.com",
    "Stranger Things": "strangerthings.fandom.com",
    "Breaking Bad": "breakingbad.fandom.com",
    "Better Call Saul": "breakingbad.fandom.com",
    "Mad Men": "madmen.fandom.com",
    "The Sopranos": "sopranos.fandom.com",
    "Succession": "succession.fandom.com",
    "Wednesday": "wednesday.fandom.com",
    "The Office": "theoffice.fandom.com",
    "24": "24.fandom.com",
    # Anime
    "Naruto": "naruto.fandom.com",
    "One Piece": "onepiece.fandom.com",
    "Dragon Ball": "dragonball.fandom.com",
    "Attack on Titan": "attackontitan.fandom.com",
    "Death Note": "deathnote.fandom.com",
    "Jujutsu Kaisen": "jujutsu-kaisen.fandom.com",
    # Gaming
    "Halo": "halo.fandom.com",
    "God of War": "godofwar.fandom.com",
    "The Witcher": "witcher.fandom.com",
    "Witcher": "witcher.fandom.com",
    "The Last of Us": "thelastofus.fandom.com",
    "Red Dead Redemption": "reddead.fandom.com",
    "Cyberpunk 2077": "cyberpunk.fandom.com",
    "Metal Gear": "metalgear.fandom.com",
    "The Legend of Zelda": "zelda.fandom.com",
    "Zelda": "zelda.fandom.com",
    "Super Mario": "mario.fandom.com",
    "Mario": "mario.fandom.com",
    "Mass Effect": "masseffect.fandom.com",
    "Tomb Raider": "tombraider.fandom.com",
    # Film
    "The Godfather": "godfather.fandom.com",
    "Fight Club": "fightclub.fandom.com",
    "Hannibal": "hannibal.fandom.com",
    "The Matrix": "matrix.fandom.com",
    "Indiana Jones": "indianajones.fandom.com",
}

# Reddit subreddits per universe (fallback when franchise isn't known)
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

# Franchise-specific reddit sub overrides (preferred when character has a franchise).
FRANCHISE_REDDIT_SUBS = {
    # Prestige TV
    "Game of Thrones": ["gameofthrones", "asoiaf", "FanTheories"],
    "Stranger Things": ["StrangerThings", "FanTheories"],
    "Breaking Bad": ["breakingbad", "FanTheories"],
    "Better Call Saul": ["betterCallSaul", "breakingbad"],
    "Mad Men": ["madmen"],
    "The Sopranos": ["thesopranos"],
    "Succession": ["SuccessionTV"],
    "Wednesday": ["Wednesday", "AddamsFamily"],
    "The Office": ["DunderMifflin", "TheOffice"],
    "24": ["24"],
    # Anime
    "Naruto": ["Naruto", "Boruto", "anime"],
    "One Piece": ["OnePiece", "anime"],
    "Dragon Ball": ["dbz", "anime"],
    "Attack on Titan": ["ShingekiNoKyojin", "anime"],
    "Death Note": ["deathnote", "anime"],
    "Jujutsu Kaisen": ["JujutsuKaisen", "Jujutsufolk", "anime"],
    # Gaming
    "Halo": ["halo", "HaloStory"],
    "God of War": ["GodofWar"],
    "The Witcher": ["witcher", "wiedzmin"],
    "Witcher": ["witcher", "wiedzmin"],
    "The Last of Us": ["thelastofus"],
    "Red Dead Redemption": ["reddeadredemption"],
    "Cyberpunk 2077": ["cyberpunkgame", "LowSodiumCyberpunk"],
    "Metal Gear": ["metalgearsolid"],
    "The Legend of Zelda": ["zelda", "truezelda"],
    "Zelda": ["zelda", "truezelda"],
    "Super Mario": ["Mario"],
    "Mario": ["Mario"],
    "Mass Effect": ["masseffect"],
    "Tomb Raider": ["TombRaider"],
    # Film
    "The Godfather": ["TheGodfather"],
    "Fight Club": ["fightclub"],
    "Hannibal": ["HannibalTV", "Hannibal"],
    "The Matrix": ["matrix"],
    "Indiana Jones": ["indianajones"],
    # Star Wars & LOTR & HP use universe-level subs, already good
}

# Fandom wiki alternative page titles (used for disambiguation on character lookup).
FANDOM_ALT_TITLES = {
    # Marvel
    "Iron Man": ["Anthony_Stark", "Iron_Man_(Anthony_Stark)"],
    "Spider-Man": ["Peter_Parker", "Spider-Man_(Peter_Parker)"],
    "Black Widow": ["Natasha_Romanoff", "Black_Widow_(Natasha_Romanoff)"],
    "Scarlet Witch": ["Wanda_Maximoff", "Scarlet_Witch"],
    "Doctor Strange": ["Stephen_Strange", "Doctor_Strange"],
    # DC
    "Green Lantern": ["Hal_Jordan", "Green_Lantern_(Hal_Jordan)"],
    "The Flash": ["Barry_Allen", "Flash_(Barry_Allen)"],
    "Harley Quinn": ["Harleen_Quinzel", "Harley_Quinn"],
    # Star Wars
    "Darth Vader": ["Anakin_Skywalker", "Darth_Vader"],
    "Obi-Wan Kenobi": ["Obi-Wan_Kenobi", "Ben_Kenobi"],
    "Luke Skywalker": ["Luke_Skywalker"],
    "Yoda": ["Yoda"],
    "Grogu": ["Grogu", "Baby_Yoda"],
    "Rey": ["Rey_Skywalker", "Rey"],
    # LOTR
    "Gandalf": ["Gandalf", "Gandalf_the_Grey"],
    "Aragorn": ["Aragorn_II_Elessar", "Aragorn"],
    "Legolas": ["Legolas_Greenleaf", "Legolas"],
    "Frodo": ["Frodo_Baggins", "Frodo"],
    # Harry Potter
    "Harry Potter": ["Harry_Potter", "Harry_James_Potter"],
    "Hermione Granger": ["Hermione_Granger", "Hermione_Jean_Granger"],
    "Severus Snape": ["Severus_Snape"],
    "Voldemort": ["Lord_Voldemort", "Tom_Riddle"],
    "Albus Dumbledore": ["Albus_Dumbledore", "Albus_Percival_Wulfric_Brian_Dumbledore"],
    # Anime
    "Naruto Uzumaki": ["Naruto_Uzumaki", "Naruto"],
    "Goku": ["Goku", "Son_Goku"],
    "Monkey D. Luffy": ["Monkey_D._Luffy", "Luffy"],
    "Eren Yeager": ["Eren_Yeager", "Eren_Jaeger"],
    "Light Yagami": ["Light_Yagami"],
    "Levi Ackerman": ["Levi", "Levi_Ackerman"],
    "Sukuna": ["Ryomen_Sukuna", "Sukuna"],
    "Gojo Satoru": ["Satoru_Gojo", "Gojo_Satoru"],
    # Gaming
    "Master Chief": ["Master_Chief", "John-117"],
    "Kratos": ["Kratos"],
    "Geralt of Rivia": ["Geralt_of_Rivia", "Geralt"],
    "Lara Croft": ["Lara_Croft"],
    "Mario": ["Mario"],
    "Link": ["Link"],
    "Solid Snake": ["Solid_Snake"],
    "Arthur Morgan": ["Arthur_Morgan"],
    "Joel Miller": ["Joel", "Joel_Miller"],
    "Ellie Williams": ["Ellie", "Ellie_Williams"],
    # TV
    "Tyrion Lannister": ["Tyrion_Lannister"],
    "Jon Snow": ["Jon_Snow", "Aegon_Targaryen_(son_of_Rhaegar)"],
    "Daenerys Targaryen": ["Daenerys_Targaryen"],
    "Tony Soprano": ["Tony_Soprano", "Anthony_Soprano"],
    "Don Draper": ["Don_Draper", "Donald_Draper"],
    "Logan Roy": ["Logan_Roy"],
    "Saul Goodman": ["Saul_Goodman", "Jimmy_McGill"],
    "Eleven": ["Eleven", "Jane_Hopper"],
    "Wednesday Addams": ["Wednesday_Addams"],
    "Jack Bauer": ["Jack_Bauer"],
    "Walter White": ["Walter_White", "Heisenberg"],
    # Film
    "Vito Corleone": ["Vito_Corleone"],
    "Michael Corleone": ["Michael_Corleone"],
    "Hannibal Lecter": ["Hannibal_Lecter"],
    "Tyler Durden": ["Tyler_Durden"],
    "Neo": ["Neo", "Thomas_Anderson"],
    "Indiana Jones": ["Indiana_Jones", "Henry_Walton_Jones_Jr."],
}

# TV Tropes franchise mappings (universe-level fallback).
TVTROPES_FRANCHISE = {
    "marvel": "MCU",
    "dc": "DCEU",
    "star_wars": "StarWars",
    "lotr": "TheLordOfTheRings",
    "harry_potter": "HarryPotter",
}

# TV Tropes franchise overrides (franchise name -> TV Tropes slug).
FRANCHISE_TVTROPES = {
    "Game of Thrones": "GameOfThrones",
    "Stranger Things": "StrangerThings",
    "Breaking Bad": "BreakingBad",
    "Better Call Saul": "BetterCallSaul",
    "The Sopranos": "TheSopranos",
    "Mad Men": "MadMen",
    "Succession": "Succession",
    "Wednesday": "Wednesday2022",
    "The Office": "TheOfficeUS",
    "24": "TwentyFour",
    "Naruto": "Naruto",
    "One Piece": "OnePiece",
    "Dragon Ball": "DragonBall",
    "Attack on Titan": "AttackOnTitan",
    "Death Note": "DeathNote",
    "Jujutsu Kaisen": "JujutsuKaisen",
    "Halo": "Halo",
    "God of War": "GodOfWarPS4",
    "The Witcher": "TheWitcher",
    "The Last of Us": "TheLastOfUs",
    "Red Dead Redemption": "RedDeadRedemptionII",
    "Cyberpunk 2077": "Cyberpunk2077",
    "Metal Gear": "MetalGear",
    "The Legend of Zelda": "TheLegendOfZelda",
    "Super Mario": "SuperMarioBros",
    "Mass Effect": "MassEffect",
    "Tomb Raider": "TombRaider",
    "The Godfather": "TheGodfather",
    "Fight Club": "FightClub",
    "Hannibal": "Hannibal",
    "The Matrix": "TheMatrix",
    "Indiana Jones": "IndianaJones",
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
            self._safe_research(self.research_entertainment_articles, name, universe, franchise),
            self._safe_research(self.research_wikipedia_deep, name, universe),
            self._safe_research(self.research_power_databases, name, universe),
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
        # Resolution order: universe-specific -> franchise override -> auto-slug.
        domain = FANDOM_DOMAINS.get(universe)
        if not domain and franchise:
            domain = FRANCHISE_FANDOM_OVERRIDES.get(franchise)
            if not domain:
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
        """Search Reddit for character discussions, theories, and facts.

        Prefers franchise-specific subs (e.g. r/StrangerThings) over the
        universe-level fallback (e.g. r/television) when both exist.
        """
        # Franchise-specific first, then universe-level fallback.
        franchise_subs = FRANCHISE_REDDIT_SUBS.get(franchise or "", [])
        universe_subs = REDDIT_SUBS.get(universe, ["FanTheories"])
        # Dedupe while preserving order, franchise first.
        seen = set()
        subs: List[str] = []
        for sub in franchise_subs + universe_subs:
            if sub not in seen:
                seen.add(sub)
                subs.append(sub)
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

        # Try franchise-specific tv tropes slug first (curated override), then
        # universe-level fallback, then auto-constructed, then Main/{name}.
        franchise_slug = FRANCHISE_TVTROPES.get(franchise or "")
        if franchise_slug:
            urls.append(f"https://tvtropes.org/pmwiki/pmwiki.php/Characters/{franchise_slug}")
            urls.append(f"https://tvtropes.org/pmwiki/pmwiki.php/Characters/{franchise_slug}{clean_name}")

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

        # Step 1: Find IMDB trivia + general trivia via SearXNG (multiple queries)
        search_queries = [
            f"site:imdb.com {name} trivia",
            f'"{name}" behind the scenes facts trivia',
        ]
        if franchise:
            search_queries[0] = f"site:imdb.com {name} {franchise} trivia"
            search_queries.append(f'"{name}" {franchise} little known facts')

        imdb_url = None
        try:
            async with aiohttp.ClientSession(timeout=self._timeout) as session:
                for search_query in search_queries[:3]:
                    try:
                        params = {"q": search_query, "format": "json"}
                        async with session.get(f"{self._searxng_url}/search", params=params) as resp:
                            if resp.status != 200:
                                continue
                            data = await resp.json()

                        for r in data.get("results", []):
                            url = r.get("url", "")
                            if "imdb.com" in url and imdb_url is None:
                                if "trivia" in url:
                                    imdb_url = url
                                elif "/title/" in url:
                                    imdb_url = url.rstrip("/") + "/trivia"

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
                                    metadata={"method": "searxng", "query": search_query[:50]},
                                ))
                    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError) as e:
                        logger.debug("imdb_search_error", query=search_query[:50], error=str(e))
                        continue
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError) as e:
            logger.debug("imdb_session_error", error=str(e))

        # Step 2: If Firecrawl available and we found an IMDB URL, scrape it
        if imdb_url and self._firecrawl_available:
            try:
                async with aiohttp.ClientSession(timeout=self._timeout) as session:
                    content = await self._firecrawl_scrape(imdb_url, session)
                    if content and len(content) > 100:
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
            f'"{name}" famous quotes',
            f"{name} memorable lines {universe}",
            f"site:wikiquote.org {name}",
        ]

        fragments = []
        async with aiohttp.ClientSession(timeout=self._timeout) as session:
            # SearXNG search for quotes
            for query in queries[:3]:
                try:
                    params = {"q": query, "format": "json"}
                    async with session.get(f"{self._searxng_url}/search", params=params) as resp:
                        if resp.status != 200:
                            continue
                        data = await resp.json()

                    for r in data.get("results", [])[:5]:
                        snippet = r.get("content", "")
                        title = r.get("title", "")
                        url = r.get("url", "")
                        if snippet and name.lower() in (snippet + title).lower():
                            is_wikiquote = "wikiquote.org" in url
                            fragments.append(ResearchFragment(
                                source="quotes",
                                content=f"{title}\n{snippet}",
                                url=url,
                                relevance_score=0.7 if is_wikiquote else 0.6,
                                fragment_type="quote",
                                metadata={"query": query, "wikiquote": is_wikiquote},
                            ))
                except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError) as e:
                    logger.debug("quotes_search_error", error=str(e))
                    continue

            # Try Wikiquote directly via API
            if not any(f.metadata.get("wikiquote") for f in fragments):
                try:
                    wiki_name = name.replace(" ", "_")
                    api_url = "https://en.wikiquote.org/w/api.php"
                    params = {
                        "action": "query",
                        "titles": name,
                        "prop": "extracts",
                        "explaintext": "1",
                        "format": "json",
                    }
                    async with session.get(api_url, params=params) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            pages = data.get("query", {}).get("pages", {})
                            for page_id, page_data in pages.items():
                                if page_id == "-1":
                                    continue
                                content = page_data.get("extract", "")
                                if content and len(content) > 50:
                                    fragments.append(ResearchFragment(
                                        source="quotes",
                                        content=content[:3000],
                                        url=f"https://en.wikiquote.org/wiki/{wiki_name}",
                                        relevance_score=0.75,
                                        fragment_type="quote",
                                        metadata={"method": "wikiquote_api"},
                                    ))
                except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError) as e:
                    logger.debug("wikiquote_api_error", error=str(e))

        logger.info("quotes_researched", character=name, fragments=len(fragments))
        return fragments

    # -----------------------------------------------------------------------
    # Source 6: Entertainment Articles (Screen Rant, CBR, etc.)
    # -----------------------------------------------------------------------

    ENTERTAINMENT_SITES = {"screenrant.com", "cbr.com", "looper.com", "collider.com", "denofgeek.com"}

    async def research_entertainment_articles(
        self,
        name: str,
        universe: str,
        franchise: Optional[str] = None,
    ) -> List[ResearchFragment]:
        """Search entertainment sites for character analysis, trivia, and behind-the-scenes articles."""
        queries = [
            f'"{name}" screenrant.com OR cbr.com facts you didn\'t know',
            f'"{name}" character analysis behind the scenes',
        ]

        fragments = []
        article_urls: List[str] = []

        async with aiohttp.ClientSession(timeout=self._timeout) as session:
            # Step 1: Search SearXNG for entertainment articles
            for query in queries:
                try:
                    params = {"q": query, "format": "json"}
                    async with session.get(f"{self._searxng_url}/search", params=params) as resp:
                        if resp.status != 200:
                            continue
                        data = await resp.json()

                    for r in data.get("results", [])[:8]:
                        snippet = r.get("content", "")
                        title = r.get("title", "")
                        url = r.get("url", "")
                        if not snippet:
                            continue

                        # Check if from an entertainment site
                        is_entertainment = any(site in url for site in self.ENTERTAINMENT_SITES)
                        name_parts = name.lower().split()
                        name_relevant = any(p in (title + " " + snippet).lower() for p in name_parts)

                        if not name_relevant:
                            continue

                        if is_entertainment and len(article_urls) < 2:
                            article_urls.append(url)

                        fragments.append(ResearchFragment(
                            source="entertainment_article",
                            content=f"{title}\n{snippet}",
                            url=url,
                            relevance_score=0.55,
                            fragment_type="behind_scenes" if "behind" in (title + snippet).lower() else "trivia",
                            metadata={"method": "searxng", "entertainment_site": is_entertainment},
                        ))
                except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError) as e:
                    logger.debug("entertainment_search_error", error=str(e))
                    continue

            # Step 2: If Firecrawl available, scrape top 2 entertainment article URLs
            if self._firecrawl_available and article_urls:
                for url in article_urls[:2]:
                    try:
                        content = await self._firecrawl_scrape(url, session)
                        if content and len(content) > 200:
                            # Extract paragraphs mentioning the character
                            relevant_parts = []
                            for paragraph in content.split("\n\n"):
                                if name.lower() in paragraph.lower() and len(paragraph.strip()) > 50:
                                    relevant_parts.append(paragraph.strip())

                            if relevant_parts:
                                fragments.append(ResearchFragment(
                                    source="entertainment_article",
                                    content="\n\n".join(relevant_parts[:10])[:3000],
                                    url=url,
                                    relevance_score=0.7,
                                    fragment_type="behind_scenes",
                                    metadata={"method": "firecrawl", "paragraphs": len(relevant_parts)},
                                ))
                    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError) as e:
                        logger.debug("entertainment_firecrawl_error", url=url, error=str(e))
                        continue

        logger.info("entertainment_articles_researched", character=name, fragments=len(fragments))
        return fragments

    # -----------------------------------------------------------------------
    # Source 7: Wikipedia Deep (full article via Firecrawl)
    # -----------------------------------------------------------------------

    async def research_wikipedia_deep(
        self,
        name: str,
        universe: str,
    ) -> List[ResearchFragment]:
        """Scrape the full Wikipedia article for deep character research."""
        # Build URL variants to try
        wiki_name = name.replace(" ", "_")
        url_variants = [
            f"https://en.wikipedia.org/wiki/{wiki_name}_(character)",
            f"https://en.wikipedia.org/wiki/{wiki_name}_(comics)",
        ]
        if universe == "marvel":
            url_variants.append(f"https://en.wikipedia.org/wiki/{wiki_name}_(Marvel_Comics)")
        elif universe == "dc":
            url_variants.append(f"https://en.wikipedia.org/wiki/{wiki_name}_(DC_Comics)")
        url_variants.append(f"https://en.wikipedia.org/wiki/{wiki_name}")

        # Target sections for extraction
        target_sections = {"biography", "powers", "other media", "reception", "cultural impact"}

        fragments = []

        # Try Firecrawl first for rich content
        if self._firecrawl_available:
            async with aiohttp.ClientSession(timeout=self._timeout) as session:
                for url in url_variants:
                    try:
                        content = await self._firecrawl_scrape(url, session)
                        if not content or len(content) < 200:
                            continue

                        sections = self._split_markdown_sections(content)
                        for section_name, section_text in sections.items():
                            if len(section_text.strip()) < 50:
                                continue
                            section_lower = section_name.lower()
                            is_target = any(t in section_lower for t in target_sections)
                            if not is_target and section_lower != "intro":
                                continue
                            ftype = self._classify_section(section_name)
                            fragments.append(ResearchFragment(
                                source="wikipedia",
                                content=section_text[:3000],
                                url=url,
                                relevance_score=0.8,
                                fragment_type=ftype,
                                metadata={
                                    "section": section_name,
                                    "method": "firecrawl",
                                    "wikipedia_variant": url.split("/wiki/")[-1],
                                },
                            ))
                        if fragments:
                            break
                    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError) as e:
                        logger.debug("wikipedia_deep_error", url=url, error=str(e))
                        continue

        # Fallback: Wikipedia REST API (works without Firecrawl)
        if not fragments:
            fragments = await self._wikipedia_via_api(name, wiki_name, url_variants, target_sections)

        logger.info("wikipedia_deep_researched", character=name, fragments=len(fragments))
        return fragments

    async def _wikipedia_via_api(
        self,
        name: str,
        wiki_name: str,
        url_variants: List[str],
        target_sections: set,
    ) -> List[ResearchFragment]:
        """Fallback: fetch Wikipedia article via REST API."""
        fragments = []
        # Try title variants via Wikipedia API
        title_variants = [v.split("/wiki/")[-1] for v in url_variants]

        async with aiohttp.ClientSession(timeout=self._timeout) as session:
            for title in title_variants:
                try:
                    api_url = "https://en.wikipedia.org/api/rest_v1/page/html/" + quote(title)
                    async with session.get(api_url) as resp:
                        if resp.status != 200:
                            continue
                    # Use the extract API instead for plaintext
                    api_url = "https://en.wikipedia.org/w/api.php"
                    params = {
                        "action": "query",
                        "titles": title.replace("_", " "),
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
                        if not content or len(content) < 200:
                            continue

                        page_url = f"https://en.wikipedia.org/wiki/{title}"
                        sections = self._split_plaintext_sections(content)
                        for section_name, section_text in sections.items():
                            if len(section_text.strip()) < 50:
                                continue
                            section_lower = section_name.lower()
                            is_target = any(t in section_lower for t in target_sections)
                            if not is_target and section_lower != "intro":
                                continue
                            ftype = self._classify_section(section_name)
                            fragments.append(ResearchFragment(
                                source="wikipedia",
                                content=section_text[:3000],
                                url=page_url,
                                relevance_score=0.7,
                                fragment_type=ftype,
                                metadata={
                                    "section": section_name,
                                    "method": "api",
                                    "wikipedia_variant": title,
                                },
                            ))
                        if fragments:
                            break
                except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError) as e:
                    logger.debug("wikipedia_api_error", title=title, error=str(e))
                    continue
        return fragments

    # -----------------------------------------------------------------------
    # Source 8: Power Databases (Comic Vine, SuperHeroDB)
    # -----------------------------------------------------------------------

    async def research_power_databases(
        self,
        name: str,
        universe: str,
    ) -> List[ResearchFragment]:
        """Search power/stats databases for structured character data."""
        queries = [
            f"site:comicvine.gamespot.com {name}",
            f"site:superherodb.com {name}",
        ]

        fragments = []
        scrape_url = None

        async with aiohttp.ClientSession(timeout=self._timeout) as session:
            # Step 1: Search SearXNG for power database entries
            for query in queries:
                try:
                    params = {"q": query, "format": "json"}
                    async with session.get(f"{self._searxng_url}/search", params=params) as resp:
                        if resp.status != 200:
                            continue
                        data = await resp.json()

                    for r in data.get("results", [])[:5]:
                        snippet = r.get("content", "")
                        title = r.get("title", "")
                        url = r.get("url", "")
                        if not snippet:
                            continue

                        is_power_db = "comicvine.gamespot.com" in url or "superherodb.com" in url
                        name_parts = name.lower().split()
                        name_relevant = any(p in (title + " " + snippet).lower() for p in name_parts)

                        if not name_relevant:
                            continue

                        # Save first power DB URL for Firecrawl scraping
                        if is_power_db and scrape_url is None:
                            scrape_url = url

                        fragments.append(ResearchFragment(
                            source="power_database",
                            content=f"{title}\n{snippet}",
                            url=url,
                            relevance_score=0.65,
                            fragment_type="power_stats",
                            metadata={"method": "searxng", "power_db": is_power_db},
                        ))
                except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError) as e:
                    logger.debug("power_db_search_error", error=str(e))
                    continue

            # Step 2: If Firecrawl available and we found a power DB URL, scrape it
            if self._firecrawl_available and scrape_url:
                try:
                    content = await self._firecrawl_scrape(scrape_url, session)
                    if content and len(content) > 200:
                        # Extract character-relevant content
                        relevant_parts = []
                        for paragraph in content.split("\n\n"):
                            stripped = paragraph.strip()
                            if len(stripped) > 30:
                                relevant_parts.append(stripped)

                        if relevant_parts:
                            fragments.append(ResearchFragment(
                                source="power_database",
                                content="\n\n".join(relevant_parts[:15])[:3000],
                                url=scrape_url,
                                relevance_score=0.65,
                                fragment_type="power_stats",
                                metadata={
                                    "method": "firecrawl",
                                    "sections": len(relevant_parts),
                                },
                            ))
                except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError) as e:
                    logger.debug("power_db_firecrawl_error", url=scrape_url, error=str(e))

        logger.info("power_databases_researched", character=name, fragments=len(fragments))
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
