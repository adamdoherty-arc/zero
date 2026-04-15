"""
Character Content Service.

Manages character profiles, research pipelines, carousel generation,
AI review, and publishing for TikTok character development posts.
Uses SearXNG for web/image search, Firecrawl for deep wiki scraping,
and LLM for content generation and review.
"""

import asyncio
import json
import re
import time
import uuid
import aiohttp
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from functools import lru_cache

import structlog
from sqlalchemy import select, update, delete, func as sql_func

from app.infrastructure.database import get_session
from app.infrastructure.config import get_settings
from app.infrastructure.ollama_client import OllamaClient
from app.db.models import CharacterModel, CharacterCarouselModel, CharacterImageModel, CharacterResearchFragmentModel
from app.models.character_content import (
    Character, CharacterCreate, CharacterUpdate,
    CharacterCarousel, CarouselCreate, CarouselUpdate,
    CharacterImage, CharacterImageCreate,
    CarouselApproval, CarouselRejection,
    BatchGenerateRequest, CharacterStats,
    ContentAngle,
    ResearchJob, ResearchJobStep, ResearchQueueStatus, ResearchJobStatus,
)
from app.services.searxng_service import get_searxng_service
from app.services.character_research_sources import get_research_sources
from app.services.story_template_service import get_story_template_service
from app.services.music_library_service import get_music_library_service

logger = structlog.get_logger()

# In-memory research progress tracking (survives within process lifetime)
_research_queue: Dict[str, Any] = {
    "jobs": {},          # job_id -> ResearchJob dict
    "order": [],         # ordered list of job_ids
    "running": False,
    "started_at": None,
    "cancel_requested": False,
}

# Local LLM model for research (free, runs on Ollama)
RESEARCH_LLM_MODEL = "qwen3-coder-next"

# ---------------------------------------------------------------------------
# Prompt Templates
# ---------------------------------------------------------------------------

RESEARCH_SYSTEM_PROMPT = """You are a character research expert specializing in pop culture, comics, movies, and TV shows.
Analyze the provided search results and compile a comprehensive character profile.
Return ONLY valid JSON."""

FACT_EXTRACTION_PROMPT = """Based on the research data below, compile a fact bank of 20-30 interesting facts about {name}.

Focus on facts that are:
- Surprising or lesser-known (not common knowledge)
- Debate-sparking or controversial
- Related to hidden details, behind-the-scenes, or deep lore
- About their powers, abilities, or character development arcs

Research data:
{research_text}

Return JSON array. Each fact:
{{
  "text": "The actual fact written in engaging, direct language",
  "category": "origin|powers|relationships|hidden_details|fan_theories|behind_scenes|character_evolution|dark_facts",
  "surprise_score": 1-10 (how surprising/unknown this fact is),
  "source": "brief source reference",
  "verified": true/false
}}

Sort by surprise_score descending. Write facts in the style of TikTok carousel text: direct, punchy, with dramatic pauses using "..." and bold claims.

FORMATTING RULES (strict):
- NEVER use em dashes. Use periods, commas, or colons instead.
- NEVER use markdown asterisks (*text* or **text**). Write plain text only.
- NEVER use parenthetical asides with dashes. Use separate sentences."""

CAROUSEL_SYSTEM_PROMPT = """You are a viral TikTok content creator specializing in character development carousels.
Your posts get 100K+ likes using this formula:
- Slide 1: Provocative hook that stops the scroll (e.g., "The Hammer Lie:", "Nobody talks about this...")
- Slides 2-6: Numbered facts with bold, engaging text
- Final slide: Engagement CTA
- Caption: Emotional, debate-sparking, with emojis
- Hashtags: character + franchise + niche tags

CRITICAL: Never use em dashes, markdown asterisks, or any formatting markup. Plain text only.

Return ONLY valid JSON."""

CAROUSEL_GENERATION_PROMPT = """Create a TikTok photo carousel about {name} ({universe}) with angle: {angle}.

Character facts available:
{facts_text}

Generate a {slide_count}-slide carousel. Return JSON:
{{
  "title": "Internal reference title",
  "hook_text": "Provocative hook for slide 1 (e.g., 'The Hammer Lie:', 'Nobody talks about...')",
  "slides": [
    {{
      "slide_num": 1,
      "text": "Hook text displayed on the image - provocative, scroll-stopping",
      "image_query": "search query to find a fitting cinematic image for this slide"
    }},
    {{
      "slide_num": 2,
      "text": "1. First numbered fact - engaging, dramatic text with '...' pauses",
      "image_query": "search query for relevant character image"
    }}
  ],
  "caption": "TikTok caption with emojis, debate-sparking question, 2-3 sentences max",
  "hashtags": ["character", "franchise", "niche", "facts", "development"],
  "music_mood": "epic|dark|emotional|mysterious|dramatic"
}}

Style rules:
- Text overlays: Bold white text on dark images, short punchy lines
- Use numbered facts (1. 2. 3. etc.)
- Include dramatic pauses with "..."
- End text with impact words or emojis (🤯 ⚡ 💀)
- Caption should provoke comments ("Comment which fact surprised you most 👇")

Hashtag strategy (include exactly 9 hashtags in this mix):
- 3 broad hashtags (e.g., #marvel, #dc, #anime, #moviefacts, #characterfacts)
- 3 niche hashtags specific to the character (e.g., #lokilore, #marveltheory, #batmanfacts)
- 3 trending/topical hashtags (e.g., #fyp, #viral, #didyouknow, #mindblown)

FORMATTING RULES (strict):
- NEVER use em dashes. Use periods, commas, or colons instead.
- NEVER use markdown asterisks (*text* or **text**). Write plain text only.
- NEVER use parenthetical asides with dashes. Use separate sentences."""

AI_REVIEW_SYSTEM_PROMPT = """You are a TikTok content strategist reviewing carousel posts for viral potential.
Score each dimension 1-10 and provide actionable feedback.
Return ONLY valid JSON."""

AI_REVIEW_PROMPT = """Review this TikTok character carousel for viral potential:

Character: {name} ({universe})
Angle: {angle}
Hook: {hook_text}

Slides:
{slides_text}

Caption: {caption}
Hashtags: {hashtags}

Score each dimension 1-10:
{{
  "hook_strength": score (Is slide 1 a scroll-stopper? Does it create curiosity?),
  "fact_quality": score (Are facts surprising and not common knowledge?),
  "engagement_potential": score (Will this spark comments/shares/saves?),
  "caption_quality": score (Does the caption encourage interaction?),
  "overall_score": score (composite weighted average),
  "suggestions": ["actionable improvement 1", "improvement 2", ...],
  "fact_check_flags": ["any facts that seem inaccurate or need verification"],
  "rewrite_hook": "optional: a better hook if score < 7",
  "rewrite_caption": "optional: a better caption if score < 7"
}}"""


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class CharacterContentService:
    """Manages character content creation pipeline."""

    def __init__(self):
        self._ollama = OllamaClient()  # All generation uses Ollama (free)

    def _generate_id(self, prefix: str = "ch") -> str:
        return f"{prefix}-{uuid.uuid4().hex[:12]}"

    @staticmethod
    def _sanitize_text(text: str) -> str:
        """Strip AI-generated formatting: em dashes, markdown asterisks, en dashes."""
        if not text:
            return text
        # Replace em dashes with period + space or comma
        text = text.replace("\u2014", ". ")  # em dash
        text = text.replace("\u2013", "-")   # en dash -> hyphen
        # Strip markdown bold/italic asterisks but keep the text
        text = re.sub(r'\*{1,3}([^*]+)\*{1,3}', r'\1', text)
        # Clean up double spaces and ". ." from replacements
        text = re.sub(r'\.\s*\.', '.', text)
        text = re.sub(r'\s{2,}', ' ', text)
        return text.strip()

    def _sanitize_carousel(self, result: dict) -> dict:
        """Sanitize all text fields in a carousel result."""
        if result.get("hook_text"):
            result["hook_text"] = self._sanitize_text(result["hook_text"])
        if result.get("caption"):
            result["caption"] = self._sanitize_text(result["caption"])
        for slide in result.get("slides", []):
            if slide.get("text"):
                slide["text"] = self._sanitize_text(slide["text"])
        return result

    # ------------------------------------------------------------------
    # ORM → Pydantic helpers
    # ------------------------------------------------------------------

    def _character_to_pydantic(self, row: CharacterModel) -> Character:
        return Character(
            id=row.id,
            name=row.name,
            universe=row.universe or "other",
            franchise=row.franchise,
            real_name=row.real_name,
            description=row.description,
            image_url=row.image_url,
            image_urls=row.image_urls or [],
            research_data=row.research_data or {},
            research_status=row.research_status or "pending",
            fact_bank=row.fact_bank or [],
            tags=row.tags or [],
            posts_created=row.posts_created or 0,
            total_views=row.total_views or 0,
            total_likes=row.total_likes or 0,
            avg_engagement=row.avg_engagement or 0.0,
            status=row.status or "active",
            created_at=row.created_at,
            updated_at=row.updated_at,
            last_researched=row.last_researched,
            research_sources=row.research_sources or [],
            relationship_map=row.relationship_map or {},
            research_depth_score=row.research_depth_score or 0.0,
            content_themes=row.content_themes or [],
        )

    def _carousel_to_pydantic(self, row: CharacterCarouselModel, character_name: str = None) -> CharacterCarousel:
        return CharacterCarousel(
            id=row.id,
            character_id=row.character_id,
            character_name=character_name,
            angle=row.angle,
            title=row.title,
            hook_text=row.hook_text,
            slides=row.slides or [],
            caption=row.caption,
            hashtags=row.hashtags or [],
            music_mood=row.music_mood,
            ai_review=row.ai_review,
            ai_review_score=(row.ai_review or {}).get("overall_score"),
            human_notes=row.human_notes,
            status=row.status or "draft",
            content_queue_id=row.content_queue_id,
            publish_url=row.publish_url,
            views=row.views,
            likes=row.likes,
            comments=row.comments,
            shares=row.shares,
            saves=row.saves,
            engagement_rate=row.engagement_rate,
            created_at=row.created_at,
            published_at=row.published_at,
            story_template=row.story_template,
            series_id=row.series_id,
            series_part=row.series_part,
            multi_character_ids=row.multi_character_ids or [],
            music_track=row.music_track,
            text_overlay_specs=row.text_overlay_specs or [],
            brain_context_used=row.brain_context_used,
            generation_metadata=row.generation_metadata or {},
            publish_status=row.publish_status,
            publish_platform=row.publish_platform,
            download_urls=row.download_urls,
            watermark_applied=row.watermark_applied if row.watermark_applied is not None else False,
        )

    def _image_to_pydantic(self, row: CharacterImageModel) -> CharacterImage:
        return CharacterImage(
            id=row.id,
            character_id=row.character_id,
            url=row.url,
            source=row.source or "manual",
            query_used=row.query_used,
            width=row.width,
            height=row.height,
            is_valid=row.is_valid if row.is_valid is not None else True,
            is_primary=row.is_primary or False,
            usage_count=row.usage_count or 0,
            created_at=row.created_at,
        )

    # ==================================================================
    # CHARACTER CRUD
    # ==================================================================

    async def create_character(self, data: CharacterCreate) -> Character:
        char_id = self._generate_id("ch")
        async with get_session() as session:
            row = CharacterModel(
                id=char_id,
                name=data.name,
                universe=data.universe.value if hasattr(data.universe, "value") else data.universe,
                franchise=data.franchise,
                real_name=data.real_name,
                description=data.description,
                tags=data.tags or [],
                status="active",
                research_status="pending",
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return self._character_to_pydantic(row)

    async def list_characters(
        self,
        universe: Optional[str] = None,
        status: Optional[str] = None,
        research_status: Optional[str] = None,
        limit: int = 100,
    ) -> List[Character]:
        async with get_session() as session:
            query = select(CharacterModel).order_by(CharacterModel.name)
            if universe:
                query = query.where(CharacterModel.universe == universe)
            if status:
                query = query.where(CharacterModel.status == status)
            if research_status:
                query = query.where(CharacterModel.research_status == research_status)
            query = query.limit(limit)
            result = await session.execute(query)
            return [self._character_to_pydantic(r) for r in result.scalars().all()]

    async def get_character(self, character_id: str) -> Optional[Character]:
        async with get_session() as session:
            row = await session.get(CharacterModel, character_id)
            return self._character_to_pydantic(row) if row else None

    async def update_character(self, character_id: str, data: CharacterUpdate) -> Optional[Character]:
        async with get_session() as session:
            row = await session.get(CharacterModel, character_id)
            if not row:
                return None
            updates = data.model_dump(exclude_unset=True)
            if "universe" in updates and hasattr(updates["universe"], "value"):
                updates["universe"] = updates["universe"].value
            for key, val in updates.items():
                setattr(row, key, val)
            await session.commit()
            await session.refresh(row)
            return self._character_to_pydantic(row)

    async def delete_character(self, character_id: str) -> bool:
        async with get_session() as session:
            row = await session.get(CharacterModel, character_id)
            if not row:
                return False
            await session.delete(row)
            await session.commit()
            return True

    # ==================================================================
    # CHARACTER RESEARCH PIPELINE
    # ==================================================================

    async def research_character(self, character_id: str) -> Character:
        """Start background research pipeline for a character."""
        async with get_session() as session:
            row = await session.get(CharacterModel, character_id)
            if not row:
                raise ValueError(f"Character {character_id} not found")
            row.research_status = "researching"
            await session.commit()
            await session.refresh(row)
            char = self._character_to_pydantic(row)

        asyncio.create_task(self._research_pipeline(character_id))
        return char

    async def _research_pipeline(self, character_id: str):
        """Full research pipeline: search -> scrape -> deep sources -> synthesize -> relationships -> images."""
        try:
            async with get_session() as session:
                row = await session.get(CharacterModel, character_id)
                if not row:
                    return
                name = row.name
                universe = row.universe
                franchise = row.franchise or ""

            logger.info("character_research_started", character_id=character_id, name=name)

            # Step 1: SearXNG web searches (existing)
            search_results = await self._search_character(name, universe, franchise)

            # Step 2: Wikipedia scrape (existing)
            wiki_data = await self._scrape_wikis(name, universe)

            # Step 3: Multi-source deep research (NEW - Firecrawl, Reddit, TV Tropes, IMDB, Quotes)
            deep_fragments = []
            try:
                sources_svc = get_research_sources()
                deep_fragments = await sources_svc.research_from_all_sources(name, universe, franchise)
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, ConnectionError) as e:
                logger.warning("deep_research_failed", name=name, error=str(e))

            # Store raw fragments for provenance
            if deep_fragments:
                async with get_session() as session:
                    for frag in deep_fragments[:50]:  # Cap at 50 fragments
                        session.add(CharacterResearchFragmentModel(
                            id=self._generate_id("rf"),
                            character_id=character_id,
                            source=frag.source,
                            content=frag.content[:5000],
                            url=frag.url,
                            relevance_score=frag.relevance_score,
                            fragment_type=frag.fragment_type,
                            metadata_=frag.metadata,
                        ))
                    await session.commit()

            # Step 4: Enhanced LLM synthesis with deep fragments
            deep_text = "\n\n".join(
                f"[{f.source}/{f.fragment_type}] {f.content[:1000]}"
                for f in deep_fragments[:20]
            )
            research_data = await self._synthesize_research(name, universe, search_results, wiki_data, deep_text)

            # Step 5: Extract fact bank with deep fragments
            fact_bank = await self._extract_facts(name, research_data, search_results, deep_fragments)

            # Step 6: Source images
            images = await self._source_images(character_id, name, universe, franchise)

            # Step 7: Compute research depth score
            source_types = set(f.source for f in deep_fragments)
            depth_score = min(100.0, (
                len(search_results) * 1.5 +
                len(wiki_data) * 10 +
                len(deep_fragments) * 3 +
                len(source_types) * 15 +
                len(fact_bank) * 1.5
            ))

            # Extract relationship map from research data
            rel_map = self._extract_relationship_map(research_data)

            # Save everything
            async with get_session() as session:
                row = await session.get(CharacterModel, character_id)
                if row:
                    row.research_data = research_data
                    row.fact_bank = fact_bank
                    row.research_status = "completed"
                    row.last_researched = datetime.now(timezone.utc)
                    row.research_sources = list(source_types)
                    row.research_depth_score = depth_score
                    if rel_map:
                        row.relationship_map = rel_map
                    if images:
                        row.image_url = images[0].get("url")
                        row.image_urls = [img.get("url") for img in images[:10]]
                    await session.commit()

            logger.info("character_research_completed",
                        character_id=character_id, facts=len(fact_bank),
                        images=len(images), sources=list(source_types),
                        depth_score=depth_score, relationships=len(rel_map))

        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, ConnectionError, json.JSONDecodeError, OSError, RuntimeError) as e:
            logger.error("character_research_failed", character_id=character_id, error=str(e))
            async with get_session() as session:
                row = await session.get(CharacterModel, character_id)
                if row:
                    row.research_status = "failed"
                    row.research_data = {"error": str(e)}
                    await session.commit()

    async def _search_character(self, name: str, universe: str, franchise: str) -> List[Dict]:
        """Run multiple SearXNG searches for character info."""
        searxng = get_searxng_service()
        queries = [
            f"{name} character facts hidden details lesser known",
            f"{name} {universe} powers abilities explained",
            f"{name} fan theories interesting facts trivia",
            f"{name} character development arc evolution",
            f"{name} behind the scenes movie trivia",
        ]
        if franchise:
            queries.append(f"{name} {franchise} facts")

        all_results = []
        for query in queries:
            try:
                results = await searxng.search(query, num_results=8)
                for r in results:
                    all_results.append({
                        "title": getattr(r, "title", "") if not isinstance(r, dict) else r.get("title", ""),
                        "url": getattr(r, "url", "") if not isinstance(r, dict) else r.get("url", ""),
                        "snippet": (getattr(r, "content", "") or getattr(r, "snippet", "")
                                    if not isinstance(r, dict)
                                    else r.get("content", r.get("snippet", "")))[:500],
                        "query": query,
                    })
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, ConnectionError) as e:
                logger.warning("character_search_failed", query=query, error=str(e))

        logger.info("character_search_done", name=name, results=len(all_results))
        return all_results

    async def _scrape_wikis(self, name: str, universe: str) -> Dict[str, Any]:
        """Scrape character wiki pages directly via HTTP (no Firecrawl needed)."""
        wiki_urls = []

        if universe == "marvel":
            wiki_urls.append(f"https://en.wikipedia.org/wiki/{name.replace(' ', '_')}_(Marvel_Comics)")
            wiki_urls.append(f"https://en.wikipedia.org/wiki/{name.replace(' ', '_')}")
        elif universe == "dc":
            wiki_urls.append(f"https://en.wikipedia.org/wiki/{name.replace(' ', '_')}_(DC_Comics)")
            wiki_urls.append(f"https://en.wikipedia.org/wiki/{name.replace(' ', '_')}")
        elif universe == "star_wars":
            wiki_urls.append(f"https://en.wikipedia.org/wiki/{name.replace(' ', '_')}")
        elif universe == "lotr":
            wiki_urls.append(f"https://en.wikipedia.org/wiki/{name.replace(' ', '_')}")
        else:
            wiki_urls.append(f"https://en.wikipedia.org/wiki/{name.replace(' ', '_')}")

        wiki_data = {}
        headers = {"User-Agent": "ZeroBot/1.0 (character-research)"}

        for url in wiki_urls[:2]:
            try:
                # Use Wikipedia REST API for clean text extraction
                wiki_name = url.split("/wiki/")[-1]
                api_url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{wiki_name}"
                async with aiohttp.ClientSession() as session:
                    # First get the summary
                    async with session.get(api_url, headers=headers,
                                           timeout=aiohttp.ClientTimeout(total=15)) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            summary = data.get("extract", "")
                            if summary:
                                wiki_data[url] = summary

                    # Then get the full HTML content and extract text
                    html_api = f"https://en.wikipedia.org/api/rest_v1/page/html/{wiki_name}"
                    async with session.get(html_api, headers=headers,
                                           timeout=aiohttp.ClientTimeout(total=20)) as resp:
                        if resp.status == 200:
                            html = await resp.text()
                            # Extract text from HTML by stripping tags
                            text = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL)
                            text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL)
                            text = re.sub(r'<[^>]+>', ' ', text)
                            text = re.sub(r'\s+', ' ', text).strip()
                            if len(text) > 500:
                                wiki_data[url + "#full"] = text[:8000]
                                logger.info("wiki_scrape_success", url=url, chars=len(text))
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, ConnectionError) as e:
                logger.warning("wiki_scrape_failed", url=url, error=str(e))

        return wiki_data

    async def _synthesize_research(self, name: str, universe: str,
                                    search_results: List[Dict], wiki_data: Dict,
                                    deep_text: str = "") -> Dict:
        """Local LLM (Ollama) synthesizes search results + wiki data + deep sources into structured research."""
        source_text = "\n".join(
            f"- [{r['title']}]({r['url']}): {r['snippet']}" for r in search_results[:20]
        )
        wiki_text = "\n\n---\n\n".join(
            f"## {url}\n{content[:3000]}" for url, content in wiki_data.items()
        )

        prompt = (
            f"Compile a comprehensive character profile for {name} ({universe}).\n\n"
            f"Web search results:\n{source_text}\n\n"
            f"Wiki content:\n{wiki_text[:5000]}\n\n"
            f"Deep research (Fandom/Reddit/TV Tropes/IMDB):\n{deep_text[:4000]}\n\n"
            "Return ONLY a valid JSON object with ALL of these fields (no markdown, no explanation):\n"
            '{"bio": "2-3 paragraph biography covering origin, major events, current status", '
            '"powers": ["power1", "power2"], '
            '"abilities_detail": {"ability_name": "detailed description of how it works"}, '
            '"key_relationships": [{"name": "character", "relation": "ally/enemy/mentor/love_interest", "details": "brief context"}], '
            '"first_appearance": "comic/movie/show and year", '
            '"first_comic_appearance": "issue # and year if applicable", '
            '"created_by": "creator name(s)", '
            '"aliases": ["alias1", "alias2"], '
            '"notable_arcs": [{"name": "arc name", "description": "what happened", "year": "when"}], '
            '"filmography": [{"title": "movie/show name", "year": 2012, "role": "lead/supporting/cameo", "type": "movie/tv_series/animated/comic"}], '
            '"quotes": [{"text": "memorable quote", "source": "movie/comic/show"}], '
            '"alternate_versions": ["variant1 - brief description"], '
            '"fun_facts": ["fact1", "fact2"], '
            '"controversies": ["controversial thing 1"], '
            '"behind_the_scenes": ["production detail 1"]}'
            "\n\n/no_think"
        )
        try:
            raw = await self._ollama.chat(
                prompt=prompt,
                system=RESEARCH_SYSTEM_PROMPT,
                model=RESEARCH_LLM_MODEL,
                temperature=0.3,
                num_predict=8192,
                timeout=600,
                max_retries=1,
            )
            return self._parse_json_response(raw, name)
        except (ValueError, json.JSONDecodeError, TimeoutError, ConnectionError) as e:
            logger.warning("research_synthesis_failed", name=name, error=str(e))
            return {"bio": f"Research data for {name}", "powers": [], "key_relationships": []}

    def _parse_json_response(self, raw: str, context: str = "") -> Any:
        """Extract and parse JSON from LLM response text, handling truncation."""
        raw = raw.strip()

        # Strip <think>...</think> tags (qwen3-coder-next reasoning output)
        raw = re.sub(r'<think>[\s\S]*?</think>', '', raw).strip()

        # Try direct parse first
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

        # Try to find JSON block in markdown code fence
        json_match = re.search(r'```(?:json)?\s*\n?([\s\S]*?)\n?```', raw)
        if json_match:
            try:
                return json.loads(json_match.group(1).strip())
            except json.JSONDecodeError:
                pass

        # Try to find JSON object or array
        for pattern in [r'\{[\s\S]*\}', r'\[[\s\S]*\]']:
            match = re.search(pattern, raw)
            if match:
                candidate = match.group(0)
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    pass
                # Fix common LLM JSON quirks: trailing commas before } or ]
                cleaned = re.sub(r',\s*([}\]])', r'\1', candidate)
                try:
                    return json.loads(cleaned)
                except json.JSONDecodeError:
                    pass

        # Handle truncated JSON (common with large LLM outputs)
        # Find the start of JSON and try to repair it
        json_start = -1
        for i, ch in enumerate(raw):
            if ch in ('{', '['):
                json_start = i
                break

        if json_start >= 0:
            json_str = raw[json_start:]
            result = self._repair_truncated_json(json_str)
            if result is not None:
                logger.info("json_repair_success", context=context)
                return result

        logger.warning("json_parse_failed", context=context, raw_length=len(raw), raw_preview=raw[:200])
        return {}

    def _repair_truncated_json(self, json_str: str) -> Any:
        """Attempt to repair truncated JSON by closing open brackets/braces."""
        # Track nesting to find where to truncate and close
        in_string = False
        escape_next = False
        stack = []

        last_valid_pos = 0
        for i, ch in enumerate(json_str):
            if escape_next:
                escape_next = False
                continue
            if ch == '\\' and in_string:
                escape_next = True
                continue
            if ch == '"' and not escape_next:
                in_string = not in_string
                continue
            if in_string:
                continue

            if ch in ('{', '['):
                stack.append(ch)
            elif ch == '}':
                if stack and stack[-1] == '{':
                    stack.pop()
                    last_valid_pos = i
            elif ch == ']':
                if stack and stack[-1] == '[':
                    stack.pop()
                    last_valid_pos = i

        # If stack is empty, JSON was complete — try parsing as-is
        if not stack:
            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                pass

        # Try to close truncated JSON by removing incomplete trailing content
        # and adding closing brackets
        # First, trim to last complete value boundary (after a comma, colon, or value end)
        trimmed = json_str.rstrip()

        # Remove trailing incomplete string or value
        # Find the last complete JSON element
        if in_string:
            # We're in an unclosed string — close it
            trimmed = trimmed + '"'
            in_string = False

        # Remove trailing comma if any
        trimmed = trimmed.rstrip(',').rstrip()

        # Close remaining open brackets
        closers = ""
        for bracket in reversed(stack):
            closers += '}' if bracket == '{' else ']'

        repair_attempt = trimmed + closers
        try:
            return json.loads(repair_attempt)
        except json.JSONDecodeError:
            pass

        return None

    def _extract_relationship_map(self, research_data: Dict) -> Dict[str, Any]:
        """Extract relationship map from synthesized research data."""
        rel_map = {}
        key_rels = research_data.get("key_relationships", [])
        if isinstance(key_rels, list):
            for rel in key_rels:
                if isinstance(rel, dict):
                    char_name = rel.get("name", "")
                    if char_name:
                        rel_map[char_name] = {
                            "relation": rel.get("relation", "unknown"),
                            "details": rel.get("details", ""),
                        }
                elif isinstance(rel, str):
                    rel_map[rel] = {"relation": "associated", "details": ""}
        return rel_map

    async def backfill_depth_scores(self) -> Dict[str, Any]:
        """Recalculate depth_score and relationship_map for all researched characters."""
        updated = 0
        async with get_session() as session:
            result = await session.execute(
                select(CharacterModel).where(
                    CharacterModel.research_status == "completed"
                )
            )
            rows = result.scalars().all()

            for row in rows:
                changed = False
                # Backfill depth_score if it's 0 but research exists
                if (row.research_depth_score or 0.0) < 1.0 and row.fact_bank:
                    source_types = set(row.research_sources or [])
                    depth_score = min(100.0, (
                        len(source_types) * 15 +
                        len(row.fact_bank) * 1.5
                    ))
                    row.research_depth_score = depth_score
                    changed = True

                # Backfill relationship_map from research_data
                if not row.relationship_map and row.research_data:
                    rel_map = self._extract_relationship_map(row.research_data)
                    if rel_map:
                        row.relationship_map = rel_map
                        changed = True

                if changed:
                    updated += 1

            if updated > 0:
                await session.commit()

        logger.info("depth_scores_backfilled", updated=updated, total=len(rows))
        return {"updated": updated, "total": len(rows)}

    async def _extract_facts(self, name: str, research_data: Dict,
                              search_results: List[Dict],
                              deep_fragments: List = None) -> List[Dict]:
        """Extract and rank facts from research data using local LLM."""
        research_text = json.dumps(research_data, indent=2)[:4000]
        source_snippets = "\n".join(r.get("snippet", "")[:200] for r in search_results[:10])

        deep_snippets = ""
        if deep_fragments:
            deep_snippets = "\n".join(
                f"[{f.source}] {f.content[:300]}" for f in deep_fragments[:15]
            )

        prompt = FACT_EXTRACTION_PROMPT.format(
            name=name,
            research_text=f"{research_text}\n\nSnippets:\n{source_snippets[:2000]}\n\nDeep sources:\n{deep_snippets[:2000]}",
        ) + "\n\n/no_think"

        try:
            raw = await self._ollama.chat(
                prompt=prompt,
                system="You are a pop culture fact compiler. Return ONLY a JSON array of facts. No explanation.",
                model=RESEARCH_LLM_MODEL,
                temperature=0.4,
                num_predict=8192,
                timeout=600,
                max_retries=1,
            )
            facts = self._parse_json_response(raw, f"facts_{name}")
            if isinstance(facts, list):
                return sorted(facts, key=lambda f: f.get("surprise_score", 0), reverse=True)
            return facts.get("facts", []) if isinstance(facts, dict) else []
        except (ValueError, json.JSONDecodeError, TimeoutError, ConnectionError) as e:
            logger.warning("fact_extraction_failed", name=name, error=str(e))
            # Fallback: build basic facts from research_data
            fallback = []
            for fact_text in research_data.get("fun_facts", []):
                fallback.append({"text": fact_text, "category": "hidden_details", "surprise_score": 5, "source": "research", "verified": False})
            for fact_text in research_data.get("behind_the_scenes", []):
                fallback.append({"text": fact_text, "category": "behind_scenes", "surprise_score": 6, "source": "research", "verified": False})
            for fact_text in research_data.get("controversies", []):
                fallback.append({"text": fact_text, "category": "dark_facts", "surprise_score": 7, "source": "research", "verified": False})
            return fallback

    async def _source_images(self, character_id: str, name: str,
                              universe: str, franchise: str) -> List[Dict]:
        """Search for character images via SearXNG image search."""
        searxng = get_searxng_service()
        queries = [
            f"{name} {universe} cinematic movie poster",
            f"{name} {franchise or universe} official promotional",
            f"{name} dark cinematic wallpaper",
            f"{name} {franchise or universe} movie still high quality",
            f"{name} {universe} character portrait",
            f"{name} comic book cover art",
            f"{name} {franchise or universe} behind the scenes photo",
        ]

        images = []
        for query in queries:
            try:
                results = await searxng.search(query, num_results=5, categories=["images"])
                for r in results:
                    img_url = (getattr(r, "img_src", None) or getattr(r, "url", None) or
                               (r.get("img_src") if isinstance(r, dict) else None) or
                               (r.get("url") if isinstance(r, dict) else ""))
                    if not img_url or not img_url.startswith("http"):
                        continue

                    img_id = self._generate_id("ci")
                    images.append({
                        "id": img_id,
                        "url": img_url,
                        "source": "searxng",
                        "query_used": query,
                    })

                    # Store in DB
                    try:
                        async with get_session() as session:
                            session.add(CharacterImageModel(
                                id=img_id,
                                character_id=character_id,
                                url=img_url,
                                source="searxng",
                                query_used=query,
                            ))
                            await session.commit()
                    except (ValueError, OSError) as _dup_err:  # DB duplicate skip
                        pass
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, ConnectionError) as e:
                logger.warning("image_search_failed", query=query, error=str(e))

        logger.info("image_sourcing_done", name=name, images_found=len(images))
        return images

    # ==================================================================
    # IMAGE MANAGEMENT
    # ==================================================================

    async def list_images(self, character_id: str) -> List[CharacterImage]:
        async with get_session() as session:
            result = await session.execute(
                select(CharacterImageModel)
                .where(CharacterImageModel.character_id == character_id)
                .order_by(CharacterImageModel.is_primary.desc(), CharacterImageModel.created_at.desc())
            )
            return [self._image_to_pydantic(r) for r in result.scalars().all()]

    async def add_image(self, data: CharacterImageCreate) -> CharacterImage:
        img_id = self._generate_id("ci")
        async with get_session() as session:
            row = CharacterImageModel(
                id=img_id,
                character_id=data.character_id,
                url=data.url,
                source=data.source,
                is_primary=data.is_primary,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return self._image_to_pydantic(row)

    # ==================================================================
    # CAROUSEL GENERATION
    # ==================================================================

    async def generate_carousel(self, data: CarouselCreate) -> CharacterCarousel:
        """Generate a carousel post for a character."""
        async with get_session() as session:
            char = await session.get(CharacterModel, data.character_id)
            if not char:
                raise ValueError(f"Character {data.character_id} not found")
            if not char.fact_bank:
                raise ValueError(f"Character {char.name} has no research data. Run research first.")

            name = char.name
            universe = char.universe
            fact_bank = char.fact_bank or []

        gen_start = time.monotonic()

        angle = data.angle.value if hasattr(data.angle, "value") else data.angle

        # Filter facts by angle category mapping
        angle_categories = {
            "hidden_truths": ["hidden_details", "behind_scenes", "dark_facts"],
            "power_secrets": ["powers", "hidden_details"],
            "underrated_moments": ["character_evolution", "hidden_details"],
            "origin_story": ["origin", "behind_scenes"],
            "character_evolution": ["character_evolution", "relationships"],
            "controversial_takes": ["fan_theories", "dark_facts"],
            "vs_comparison": ["powers", "origin"],
            "behind_scenes": ["behind_scenes"],
            "fan_theories": ["fan_theories"],
            "dark_facts": ["dark_facts", "hidden_details"],
        }
        target_categories = angle_categories.get(angle, [])
        filtered_facts = [
            f for f in fact_bank
            if f.get("category") in target_categories
        ]
        # If not enough filtered facts, use top facts by surprise score
        if len(filtered_facts) < 5:
            filtered_facts = sorted(fact_bank, key=lambda f: f.get("surprise_score", 0), reverse=True)

        # Get story template if specified
        template = None
        template_prompt = None
        if data.story_template:
            template_svc = get_story_template_service()
            template = await template_svc.get_template(data.story_template)
            if template:
                template_prompt = template.prompt_template

        # Get multi-character facts
        secondary_facts_text = ""
        if data.multi_character_ids:
            for sec_id in (data.multi_character_ids or [])[:3]:
                async with get_session() as session:
                    sec_char = await session.get(CharacterModel, sec_id)
                    if sec_char and sec_char.fact_bank:
                        sec_facts = [f.get("text", "") for f in sec_char.fact_bank[:8]]
                        secondary_facts_text += f"\n\n{sec_char.name} facts:\n" + "\n".join(f"- {f}" for f in sec_facts)

        # Get brain context for enriched generation
        brain_context = await self._get_brain_context(name, angle)

        # Build prompt
        facts_text = "\n".join(
            f"- [{f.get('category', 'general')}] (surprise: {f.get('surprise_score', 5)}/10) {f.get('text', '')}"
            for f in filtered_facts[:15]
        )

        slide_count = getattr(data, 'slide_count', 6) or 6

        if template_prompt:
            # Use template prompt with variable substitution
            research_summary = json.dumps(char.research_data, indent=1)[:2000] if hasattr(char, 'research_data') else ""
            prompt = template_prompt.format(
                name=name,
                universe=universe,
                facts=facts_text,
                research_summary=research_summary,
                secondary_names=", ".join([sid for sid in (data.multi_character_ids or [])]),
                secondary_facts=secondary_facts_text,
                relationships=json.dumps(char.relationship_map or {})[:1000] if hasattr(char, 'relationship_map') else "{}",
                fan_theories="\n".join(f.get("text", "") for f in fact_bank if f.get("category") == "fan_theories")[:1000],
                behind_scenes="\n".join(f.get("text", "") for f in fact_bank if f.get("category") == "behind_scenes")[:1000],
                slide_count=slide_count,
            )
        else:
            prompt = CAROUSEL_GENERATION_PROMPT.format(
                name=name,
                universe=universe,
                angle=angle.replace("_", " ").title(),
                facts_text=facts_text,
                slide_count=slide_count,
            )

        # Add brain context to prompt if available
        if brain_context:
            brain_hint = ""
            if brain_context.get("learnings"):
                brain_hint += "\nLearnings from past carousels:\n" + "\n".join(f"- {l}" for l in brain_context["learnings"][:3])
            if brain_context.get("past_experience"):
                brain_hint += "\nPast successful patterns:\n" + "\n".join(f"- {p}" for p in brain_context["past_experience"][:2])
            if brain_hint:
                prompt += f"\n\nOptimization hints:{brain_hint}"

        try:
            result = await self._ollama.chat(
                prompt=prompt,
                system=CAROUSEL_SYSTEM_PROMPT,
                model=RESEARCH_LLM_MODEL,
                temperature=0.8,
                num_predict=4096,
                timeout=600,
                max_retries=1,
            )
            result = self._parse_json_response(result, f"carousel_{name}")
            result = self._sanitize_carousel(result)
            if not isinstance(result, dict) or "slides" not in result:
                raise ValueError("Invalid carousel JSON structure")
        except (ValueError, json.JSONDecodeError, TimeoutError, ConnectionError) as e:
            logger.debug("carousel_generation_fallback", name=name, error=str(e))
            result = {
                "title": f"{name} - {angle.replace('_', ' ').title()}",
                "hook_text": f"What they don't tell you about {name}...",
                "slides": [
                    {"slide_num": i + 1, "text": f.get("text", ""), "image_query": f"{name} cinematic"}
                    for i, f in enumerate(filtered_facts[:slide_count])
                ],
                "caption": f"Which fact surprised you most? 👇 #{name.replace(' ', '')}",
                "hashtags": [name.lower().replace(" ", ""), universe, "characterfacts", "fyp"],
                "music_mood": "epic",
            }

        # Source images for each slide
        slides = result.get("slides", [])
        await self._assign_slide_images(data.character_id, slides)

        # Generate text overlay specs
        text_overlay_specs = [
            {
                "slide_num": s.get("slide_num", i + 1),
                "text_position": "center" if i == 0 else "bottom",
                "font_weight": "bold",
                "max_chars_per_line": 30,
                "background_overlay": 0.5,
                "text_color": "#FFFFFF",
                "text_shadow": True,
            }
            for i, s in enumerate(slides)
        ]

        # Auto-assign music
        music_track_data = None
        try:
            music_svc = get_music_library_service()
            carousel_text = " ".join(s.get("text", "") for s in slides)
            recommended = await music_svc.recommend_music(carousel_text, angle=angle)
            if recommended:
                track = recommended[0]
                music_track_data = {
                    "id": track.id,
                    "name": track.name,
                    "artist": track.artist,
                    "mood": track.mood,
                }
                await music_svc.increment_usage(track.id)
        except (ValueError, KeyError, TypeError) as e:
            logger.debug("music_recommendation_failed", error=str(e))

        # Increment template usage
        if data.story_template:
            try:
                template_svc = get_story_template_service()
                await template_svc.increment_usage(data.story_template)
            except (ValueError, KeyError) as e:
                logger.debug("template_usage_increment_failed", error=str(e))

        # Save carousel with all new fields
        duration_ms = int((time.monotonic() - gen_start) * 1000)
        carousel_id = self._generate_id("cc")
        async with get_session() as session:
            row = CharacterCarouselModel(
                id=carousel_id,
                character_id=data.character_id,
                angle=angle,
                title=result.get("title", ""),
                hook_text=result.get("hook_text", ""),
                slides=slides,
                caption=result.get("caption", ""),
                hashtags=result.get("hashtags", []),
                music_mood=result.get("music_mood", "epic"),
                status="draft",
                story_template=data.story_template,
                series_id=data.series_id,
                series_part=data.series_part,
                multi_character_ids=data.multi_character_ids or [],
                music_track=music_track_data,
                text_overlay_specs=text_overlay_specs,
                brain_context_used=brain_context,
                generation_metadata={
                    "template": data.story_template,
                    "template_name": template.name if template else None,
                    "slide_count": slide_count,
                    "brain_enriched": bool(brain_context),
                    "multi_character": bool(data.multi_character_ids),
                    "facts_used": len(filtered_facts[:15]),
                    "facts_selected": [
                        {"text": f.get("text", "")[:100], "category": f.get("category", ""), "surprise_score": f.get("surprise_score", 0)}
                        for f in filtered_facts[:15]
                    ],
                    "model": RESEARCH_LLM_MODEL,
                    "duration_ms": duration_ms,
                    "angle": angle,
                    "prompt_preview": prompt[:500] if prompt else None,
                },
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)

            char_row = await session.get(CharacterModel, data.character_id)
            char_name = char_row.name if char_row else None

            return self._carousel_to_pydantic(row, char_name)

    async def _assign_slide_images(self, character_id: str, slides: List[Dict]):
        """Try to find or search images for each slide."""
        # First check existing images
        async with get_session() as session:
            result = await session.execute(
                select(CharacterImageModel)
                .where(CharacterImageModel.character_id == character_id)
                .where(CharacterImageModel.is_valid == True)
                .order_by(CharacterImageModel.usage_count.asc())
            )
            existing = result.scalars().all()

        # Assign existing images to slides
        for i, slide in enumerate(slides):
            if i < len(existing):
                slide["image_url"] = existing[i].url

    # ==================================================================
    # AI REVIEW
    # ==================================================================

    async def ai_review_carousel(self, carousel_id: str) -> CharacterCarousel:
        """AI reviews a carousel for viral potential."""
        async with get_session() as session:
            row = await session.get(CharacterCarouselModel, carousel_id)
            if not row:
                raise ValueError(f"Carousel {carousel_id} not found")

            char = await session.get(CharacterModel, row.character_id)
            char_name = char.name if char else "Unknown"
            char_universe = char.universe if char else "unknown"

        slides_text = "\n".join(
            f"Slide {s.get('slide_num', i+1)}: {s.get('text', '')}"
            for i, s in enumerate(row.slides or [])
        )

        prompt = AI_REVIEW_PROMPT.format(
            name=char_name,
            universe=char_universe,
            angle=row.angle,
            hook_text=row.hook_text or "",
            slides_text=slides_text,
            caption=row.caption or "",
            hashtags=", ".join(row.hashtags or []),
        )

        try:
            raw = await self._ollama.chat(
                prompt=prompt,
                system=AI_REVIEW_SYSTEM_PROMPT,
                model=RESEARCH_LLM_MODEL,
                temperature=0.3,
                num_predict=2048,
                timeout=300,
                max_retries=1,
            )
            review = self._parse_json_response(raw, f"review_{carousel_id}")
            if not isinstance(review, dict) or "overall_score" not in review:
                raise ValueError("Invalid review JSON")
        except (ValueError, json.JSONDecodeError, TimeoutError, ConnectionError) as e:
            logger.debug("ai_review_fallback", carousel_id=carousel_id, error=str(e))
            review = {
                "hook_strength": 5,
                "fact_quality": 5,
                "engagement_potential": 5,
                "caption_quality": 5,
                "overall_score": 5,
                "suggestions": ["Could not complete AI review"],
                "fact_check_flags": [],
            }

        overall = review.get("overall_score", 5)

        # If score >= 7, ready for human review. Otherwise try one rewrite.
        new_status = "pending_review" if overall >= 7 else "ai_reviewed"

        # Record outcome for learning
        try:
            from app.services.content_learning_engine import get_content_learning_engine
            engine = get_content_learning_engine()
            await engine.register_prompt_evolution(
                carousel_id, str(row.slides)[:500], overall
            )
        except (ValueError, KeyError, TypeError, ImportError):
            pass  # Learning failure should not block review

        # Apply rewrites if provided and score is low
        if overall < 7:
            rewrite_hook = review.get("rewrite_hook")
            rewrite_caption = review.get("rewrite_caption")
            if rewrite_hook or rewrite_caption:
                async with get_session() as session:
                    row = await session.get(CharacterCarouselModel, carousel_id)
                    if rewrite_hook:
                        row.hook_text = rewrite_hook
                    if rewrite_caption:
                        row.caption = rewrite_caption
                    row.ai_review = review
                    row.status = "pending_review"  # Still send to human after rewrite
                    await session.commit()
                    await session.refresh(row)
                    return self._carousel_to_pydantic(row, char_name)

        async with get_session() as session:
            row = await session.get(CharacterCarouselModel, carousel_id)
            row.ai_review = review
            row.status = new_status
            await session.commit()
            await session.refresh(row)
            return self._carousel_to_pydantic(row, char_name)

    # ==================================================================
    # HUMAN REVIEW
    # ==================================================================

    async def list_review_queue(self, limit: int = 50) -> List[CharacterCarousel]:
        """Get carousels pending human review."""
        async with get_session() as session:
            result = await session.execute(
                select(CharacterCarouselModel)
                .where(CharacterCarouselModel.status.in_(["pending_review", "ai_reviewed"]))
                .order_by(CharacterCarouselModel.created_at.desc())
                .limit(limit)
            )
            carousels = []
            for row in result.scalars().all():
                char = await session.get(CharacterModel, row.character_id)
                char_name = char.name if char else None
                carousels.append(self._carousel_to_pydantic(row, char_name))
            return carousels

    async def approve_carousel(self, carousel_id: str, approval: CarouselApproval) -> CharacterCarousel:
        async with get_session() as session:
            row = await session.get(CharacterCarouselModel, carousel_id)
            if not row:
                raise ValueError(f"Carousel {carousel_id} not found")

            row.status = "approved"
            if approval.caption:
                row.caption = approval.caption
            if approval.hashtags:
                row.hashtags = approval.hashtags
            if approval.human_notes:
                row.human_notes = approval.human_notes

            char = await session.get(CharacterModel, row.character_id)
            if char:
                char.posts_created = (char.posts_created or 0) + 1

            await session.commit()
            await session.refresh(row)
            char_name = char.name if char else None
            return self._carousel_to_pydantic(row, char_name)

    async def reject_carousel(self, carousel_id: str, rejection: CarouselRejection) -> CharacterCarousel:
        async with get_session() as session:
            row = await session.get(CharacterCarouselModel, carousel_id)
            if not row:
                raise ValueError(f"Carousel {carousel_id} not found")

            row.status = "rejected"
            row.human_notes = rejection.reason
            if rejection.human_notes:
                row.human_notes = f"{rejection.reason}\n{rejection.human_notes}"

            await session.commit()
            await session.refresh(row)
            char = await session.get(CharacterModel, row.character_id)
            char_name = char.name if char else None
            return self._carousel_to_pydantic(row, char_name)

    # ==================================================================
    # CAROUSEL CRUD
    # ==================================================================

    async def list_carousels(
        self,
        character_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[CharacterCarousel]:
        async with get_session() as session:
            query = select(CharacterCarouselModel).order_by(CharacterCarouselModel.created_at.desc())
            if character_id:
                query = query.where(CharacterCarouselModel.character_id == character_id)
            if status:
                query = query.where(CharacterCarouselModel.status == status)
            query = query.limit(limit)
            result = await session.execute(query)
            carousels = []
            for row in result.scalars().all():
                char = await session.get(CharacterModel, row.character_id)
                char_name = char.name if char else None
                carousels.append(self._carousel_to_pydantic(row, char_name))
            return carousels

    async def get_carousel(self, carousel_id: str) -> Optional[CharacterCarousel]:
        async with get_session() as session:
            row = await session.get(CharacterCarouselModel, carousel_id)
            if not row:
                return None
            char = await session.get(CharacterModel, row.character_id)
            char_name = char.name if char else None
            return self._carousel_to_pydantic(row, char_name)

    async def update_carousel(self, carousel_id: str, data: CarouselUpdate) -> Optional[CharacterCarousel]:
        async with get_session() as session:
            row = await session.get(CharacterCarouselModel, carousel_id)
            if not row:
                return None
            updates = data.model_dump(exclude_unset=True)
            for key, val in updates.items():
                setattr(row, key, val)
            await session.commit()
            await session.refresh(row)
            char = await session.get(CharacterModel, row.character_id)
            char_name = char.name if char else None
            return self._carousel_to_pydantic(row, char_name)

    # ==================================================================
    # ON-DEMAND IMAGE SOURCING
    # ==================================================================

    async def source_images_on_demand(self, character_id: str) -> List[CharacterImage]:
        """Re-run image search for a character with fresh queries."""
        async with get_session() as session:
            row = await session.get(CharacterModel, character_id)
            if not row:
                raise ValueError(f"Character {character_id} not found")
            name = row.name
            universe = row.universe
            franchise = row.franchise or ""

        images = await self._source_images(character_id, name, universe, franchise)

        # Update character image_urls
        async with get_session() as session:
            row = await session.get(CharacterModel, character_id)
            if row and images:
                existing_urls = set(row.image_urls or [])
                new_urls = [img["url"] for img in images if img["url"] not in existing_urls]
                row.image_urls = list(existing_urls) + new_urls
                if not row.image_url and new_urls:
                    row.image_url = new_urls[0]
                await session.commit()

        return await self.list_images(character_id)

    # ==================================================================
    # FACT MANAGEMENT
    # ==================================================================

    async def add_fact(self, character_id: str, fact: Dict[str, Any]) -> Character:
        """Add a single fact to a character's fact bank."""
        async with get_session() as session:
            row = await session.get(CharacterModel, character_id)
            if not row:
                raise ValueError(f"Character {character_id} not found")
            bank = list(row.fact_bank or [])
            bank.append(fact)
            row.fact_bank = bank
            await session.commit()
            await session.refresh(row)
            return self._character_to_pydantic(row)

    async def update_fact(self, character_id: str, fact_index: int, fact: Dict[str, Any]) -> Character:
        """Update a fact in a character's fact bank by index."""
        async with get_session() as session:
            row = await session.get(CharacterModel, character_id)
            if not row:
                raise ValueError(f"Character {character_id} not found")
            bank = list(row.fact_bank or [])
            if fact_index < 0 or fact_index >= len(bank):
                raise ValueError(f"Fact index {fact_index} out of range (0-{len(bank)-1})")
            bank[fact_index] = fact
            row.fact_bank = bank
            await session.commit()
            await session.refresh(row)
            return self._character_to_pydantic(row)

    # ==================================================================
    # RESEARCH QUEUE (async with progress tracking)
    # ==================================================================

    async def get_research_queue_status(self) -> ResearchQueueStatus:
        """Return research queue status. Merges in-memory live jobs with DB state."""
        global _research_queue

        # If a live queue is running, merge in-memory jobs with DB-sourced jobs
        if _research_queue["running"] and _research_queue["order"]:
            live_jobs = []
            live_char_ids = set()
            for job_id in _research_queue["order"]:
                job_data = _research_queue["jobs"].get(job_id)
                if job_data:
                    live_jobs.append(ResearchJob(**job_data))
                    live_char_ids.add(job_data.get("character_id"))

            # Also pull DB jobs not in the live queue (previously completed/failed)
            db_jobs = await self._get_db_jobs(exclude_char_ids=live_char_ids)

            # Live jobs first (active/queued), then DB jobs (completed/failed/pending)
            jobs_list = live_jobs + db_jobs

            queued = sum(1 for j in jobs_list if j.status == ResearchJobStatus.QUEUED)
            researching = sum(1 for j in jobs_list if j.status == ResearchJobStatus.RESEARCHING)
            completed = sum(1 for j in jobs_list if j.status == ResearchJobStatus.COMPLETED)
            failed = sum(1 for j in jobs_list if j.status == ResearchJobStatus.FAILED)

            current_character = None
            current_step = None
            for j in live_jobs:
                if j.status == ResearchJobStatus.RESEARCHING:
                    current_character = j.character_name
                    for step in j.steps:
                        if step.status == "running":
                            current_step = step.name
                            break
                    break

            return ResearchQueueStatus(
                total_jobs=len(jobs_list),
                queued=queued,
                researching=researching,
                completed=completed,
                failed=failed,
                current_character=current_character,
                current_step=current_step,
                jobs=jobs_list,
                started_at=_research_queue.get("started_at"),
                estimated_completion=None,
            )

        # No live queue — rebuild status from database
        jobs_list = await self._get_db_jobs()

        queued = sum(1 for j in jobs_list if j.status == ResearchJobStatus.QUEUED)
        researching = sum(1 for j in jobs_list if j.status == ResearchJobStatus.RESEARCHING)
        completed = sum(1 for j in jobs_list if j.status == ResearchJobStatus.COMPLETED)
        failed = sum(1 for j in jobs_list if j.status == ResearchJobStatus.FAILED)

        current_character = None
        for j in jobs_list:
            if j.status == ResearchJobStatus.RESEARCHING:
                current_character = j.character_name
                break

        return ResearchQueueStatus(
            total_jobs=len(jobs_list),
            queued=queued,
            researching=researching,
            completed=completed,
            failed=failed,
            current_character=current_character,
            current_step=None,
            jobs=jobs_list,
            started_at=None,
            estimated_completion=None,
        )

    async def _get_db_jobs(self, exclude_char_ids: set = None) -> list:
        """Build ResearchJob list from DB. Optionally exclude characters already in live queue."""
        exclude_char_ids = exclude_char_ids or set()
        jobs_list = []

        async with get_session() as session:
            from sqlalchemy import text as sql_text
            rows = await session.execute(
                select(CharacterModel)
                .order_by(
                    sql_text("CASE research_status "
                             "WHEN 'researching' THEN 0 "
                             "WHEN 'failed' THEN 1 "
                             "WHEN 'completed' THEN 2 "
                             "ELSE 3 END"),
                    CharacterModel.last_researched.desc().nulls_last(),
                    CharacterModel.name,
                )
            )
            characters = rows.scalars().all()

            img_counts = {}
            img_rows = await session.execute(
                select(
                    CharacterImageModel.character_id,
                    sql_func.count().label("cnt"),
                ).group_by(CharacterImageModel.character_id)
            )
            for row in img_rows.all():
                img_counts[row[0]] = row[1]

        step_names = [
            "searxng_search", "wiki_scrape", "deep_research",
            "synthesis", "fact_extraction", "image_sourcing", "save_results",
        ]

        for char in characters:
            if char.id in exclude_char_ids:
                continue

            status = char.research_status or "pending"
            if status == "completed":
                job_status = "completed"
                steps = [
                    ResearchJobStep(
                        name=s, status="completed",
                        completed_at=char.last_researched,
                    ).model_dump() for s in step_names
                ]
            elif status == "failed":
                job_status = "failed"
                err = ""
                if isinstance(char.research_data, dict):
                    err = char.research_data.get("error", "Unknown error")
                steps = [
                    ResearchJobStep(name=s, status="failed", error=err if s == "save_results" else None).model_dump()
                    for s in step_names
                ]
            elif status == "researching":
                job_status = "researching"
                steps = [
                    ResearchJobStep(name=s, status="pending").model_dump()
                    for s in step_names
                ]
            else:
                job_status = "queued"
                steps = [
                    ResearchJobStep(name=s, status="pending").model_dump()
                    for s in step_names
                ]

            fact_count = len(char.fact_bank) if char.fact_bank else 0
            image_count = img_counts.get(char.id, 0)

            jobs_list.append(ResearchJob(
                id=f"db-{char.id}",
                character_id=char.id,
                character_name=char.name,
                universe=char.universe or "unknown",
                status=job_status,
                steps=steps,
                started_at=char.last_researched if status in ("completed", "researching") else None,
                completed_at=char.last_researched if status == "completed" else None,
                facts_found=fact_count,
                images_found=image_count,
                sources_used=char.research_sources or [],
                depth_score=char.research_depth_score or 0.0,
            ))

        return jobs_list

    async def start_batch_research_async(
        self, universe: Optional[str] = None, limit: int = 24
    ) -> ResearchQueueStatus:
        """Start batch research with progress tracking. Returns immediately."""
        global _research_queue

        if _research_queue["running"]:
            return await self.get_research_queue_status()

        # Reset any stuck "researching" characters (from crashed runs)
        async with get_session() as session:
            stuck = await session.execute(
                select(CharacterModel).where(CharacterModel.research_status == "researching")
            )
            for row in stuck.scalars().all():
                row.research_status = "pending"
                logger.info("reset_stuck_character", name=row.name, id=row.id)
            await session.commit()

        # Get candidates: pending + failed
        chars = await self.list_characters(
            universe=universe, research_status="pending", limit=limit,
        )
        failed = await self.list_characters(
            universe=universe, research_status="failed", limit=limit,
        )
        chars.extend(failed)
        chars = chars[:limit]

        if not chars:
            return ResearchQueueStatus(total_jobs=0, jobs=[])

        # Reset queue
        _research_queue["jobs"] = {}
        _research_queue["order"] = []
        _research_queue["running"] = True
        _research_queue["cancel_requested"] = False
        _research_queue["started_at"] = datetime.now(timezone.utc)

        # Build step template
        step_names = [
            "searxng_search", "wiki_scrape", "deep_research",
            "synthesis", "fact_extraction", "image_sourcing", "save_results",
        ]

        for char in chars:
            job_id = f"rj-{uuid.uuid4().hex[:12]}"
            steps = [
                ResearchJobStep(name=s).model_dump() for s in step_names
            ]
            job_data = ResearchJob(
                id=job_id,
                character_id=char.id,
                character_name=char.name,
                universe=char.universe,
                status=ResearchJobStatus.QUEUED,
                steps=steps,
            ).model_dump()
            # Ensure enum values are plain strings for JSON serialization
            job_data["status"] = "queued"
            _research_queue["jobs"][job_id] = job_data
            _research_queue["order"].append(job_id)

        # Launch the queue processor as a background task
        asyncio.create_task(self._run_research_queue())

        return await self.get_research_queue_status()

    async def cancel_research_queue(self) -> Dict[str, Any]:
        """Cancel the running research queue."""
        global _research_queue
        if not _research_queue["running"]:
            return {"status": "not_running", "message": "No research queue is currently running."}

        _research_queue["cancel_requested"] = True
        return {
            "status": "cancelling",
            "message": "Cancel requested. Current character will finish, then queue stops.",
        }

    async def retry_research_job(self, character_id: str) -> ResearchQueueStatus:
        """Retry a failed or stuck research job for a specific character."""
        global _research_queue

        # Verify the character exists in the database
        async with get_session() as session:
            row = await session.get(CharacterModel, character_id)
            if not row:
                raise ValueError(f"Character {character_id} not found")
            char_name = row.name
            char_universe = row.universe or ""
            # Reset the character's research status in DB
            row.research_status = "pending"
            await session.commit()

        step_names = [
            "searxng_search", "wiki_scrape", "deep_research",
            "synthesis", "fact_extraction", "image_sourcing", "save_results",
        ]
        fresh_steps = [
            {"name": s, "status": "pending", "started_at": None,
             "completed_at": None, "result_summary": None, "error": None}
            for s in step_names
        ]

        # Check if a job for this character already exists in the queue
        existing_job_id = None
        for job_id, job_data in _research_queue["jobs"].items():
            if job_data["character_id"] == character_id:
                existing_job_id = job_id
                break

        if existing_job_id:
            # Reset the existing job
            job = _research_queue["jobs"][existing_job_id]
            job["status"] = "queued"
            job["steps"] = fresh_steps
            job["error"] = None
            job["started_at"] = None
            job["completed_at"] = None
            job["facts_found"] = 0
            job["images_found"] = 0
            job["sources_used"] = []
            job["depth_score"] = 0.0
            job_id = existing_job_id
        else:
            # Create a new job entry
            job_id = f"rj-{uuid.uuid4().hex[:12]}"
            job_data = ResearchJob(
                id=job_id,
                character_id=character_id,
                character_name=char_name,
                universe=char_universe,
                status=ResearchJobStatus.QUEUED,
                steps=fresh_steps,
            ).model_dump()
            job_data["status"] = "queued"
            _research_queue["jobs"][job_id] = job_data

        if _research_queue["running"]:
            # Queue is already running — insert at front of remaining order
            if job_id in _research_queue["order"]:
                _research_queue["order"].remove(job_id)
            # Find the first queued job and insert before it
            insert_idx = 0
            for i, oid in enumerate(_research_queue["order"]):
                j = _research_queue["jobs"].get(oid, {})
                if j.get("status") == "queued":
                    insert_idx = i
                    break
            else:
                insert_idx = len(_research_queue["order"])
            _research_queue["order"].insert(insert_idx, job_id)
        else:
            # Queue is not running — set up and start it
            if job_id not in _research_queue["order"]:
                _research_queue["order"].append(job_id)
            _research_queue["running"] = True
            _research_queue["cancel_requested"] = False
            _research_queue["started_at"] = datetime.now(timezone.utc)
            asyncio.create_task(self._run_research_queue())

        logger.info("retry_research_job", character_id=character_id, name=char_name, job_id=job_id)
        return await self.get_research_queue_status()

    async def _run_research_queue(self):
        """Process the research queue with concurrent batch processing (3 at a time)."""
        global _research_queue
        BATCH_SIZE = 3
        try:
            order = list(_research_queue["order"])
            idx = 0
            while idx < len(order):
                if _research_queue["cancel_requested"]:
                    logger.info("research_queue_cancelled")
                    break

                # Collect next batch of queued jobs
                batch_ids = []
                while idx < len(order) and len(batch_ids) < BATCH_SIZE:
                    jid = order[idx]
                    job = _research_queue["jobs"].get(jid)
                    if job and job["status"] == "queued":
                        batch_ids.append(jid)
                    idx += 1

                if not batch_ids:
                    continue

                # Start all jobs in the batch concurrently
                async def _process_one(job_id: str):
                    job = _research_queue["jobs"][job_id]
                    job["status"] = "researching"
                    job["started_at"] = datetime.now(timezone.utc).isoformat()
                    try:
                        async with get_session() as session:
                            row = await session.get(CharacterModel, job["character_id"])
                            if row:
                                row.research_status = "researching"
                                await session.commit()
                    except (OSError, ValueError, RuntimeError):
                        pass

                    try:
                        await self._research_pipeline_tracked(job_id)
                        job["status"] = "completed"
                        job["completed_at"] = datetime.now(timezone.utc).isoformat()
                        logger.info("research_queue_job_done",
                                    character=job["character_name"],
                                    facts=job["facts_found"],
                                    images=job["images_found"])
                    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, ConnectionError, json.JSONDecodeError, OSError, RuntimeError) as e:
                        job["status"] = "failed"
                        job["error"] = str(e)
                        job["completed_at"] = datetime.now(timezone.utc).isoformat()
                        logger.warning("research_queue_job_failed",
                                       character=job["character_name"], error=str(e))
                        try:
                            async with get_session() as session:
                                row = await session.get(CharacterModel, job["character_id"])
                                if row:
                                    row.research_status = "failed"
                                    row.research_data = {"error": str(e)}
                                    await session.commit()
                        except (OSError, ValueError, RuntimeError):
                            pass

                logger.info("research_queue_batch_start",
                            batch=[_research_queue["jobs"][jid]["character_name"] for jid in batch_ids],
                            size=len(batch_ids))
                await asyncio.gather(*[_process_one(jid) for jid in batch_ids])

        finally:
            _research_queue["running"] = False
            _research_queue["cancel_requested"] = False
            logger.info("research_queue_finished")

    async def _research_pipeline_tracked(self, job_id: str):
        """Research pipeline with per-step progress tracking in _research_queue."""
        global _research_queue
        job = _research_queue["jobs"][job_id]
        character_id = job["character_id"]
        steps = job["steps"]

        # Helper to update a step's status
        def _update_step(step_name: str, status: str, result_summary: str = None, error: str = None):
            for step in steps:
                if step["name"] == step_name:
                    step["status"] = status
                    if status == "running":
                        step["started_at"] = datetime.now(timezone.utc).isoformat()
                    if status in ("completed", "failed"):
                        step["completed_at"] = datetime.now(timezone.utc).isoformat()
                    if result_summary:
                        step["result_summary"] = result_summary
                    if error:
                        step["error"] = error
                    break

        # Load character info
        async with get_session() as session:
            row = await session.get(CharacterModel, character_id)
            if not row:
                raise ValueError(f"Character {character_id} not found")
            name = row.name
            universe = row.universe
            franchise = row.franchise or ""

        logger.info("tracked_research_started", character_id=character_id, name=name)

        # Step 1: SearXNG web searches
        _update_step("searxng_search", "running")
        try:
            search_results = await self._search_character(name, universe, franchise)
            _update_step("searxng_search", "completed",
                         result_summary=f"{len(search_results)} results from web search")
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, ConnectionError) as e:
            _update_step("searxng_search", "failed", error=str(e))
            search_results = []

        # Step 2: Wikipedia scrape
        _update_step("wiki_scrape", "running")
        try:
            wiki_data = await self._scrape_wikis(name, universe)
            _update_step("wiki_scrape", "completed",
                         result_summary=f"{len(wiki_data)} wiki pages scraped")
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, ConnectionError) as e:
            _update_step("wiki_scrape", "failed", error=str(e))
            wiki_data = {}

        # Step 3: Deep research (Firecrawl, Reddit, TV Tropes, IMDB, Quotes)
        _update_step("deep_research", "running")
        deep_fragments = []
        try:
            sources_svc = get_research_sources()
            deep_fragments = await sources_svc.research_from_all_sources(name, universe, franchise)
            _update_step("deep_research", "completed",
                         result_summary=f"{len(deep_fragments)} fragments from deep sources")
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, ConnectionError) as e:
            _update_step("deep_research", "failed", error=str(e))

        # Store fragments in DB
        if deep_fragments:
            try:
                async with get_session() as session:
                    for frag in deep_fragments[:50]:
                        session.add(CharacterResearchFragmentModel(
                            id=self._generate_id("rf"),
                            character_id=character_id,
                            source=frag.source,
                            content=frag.content[:5000],
                            url=frag.url,
                            relevance_score=frag.relevance_score,
                            fragment_type=frag.fragment_type,
                            metadata_=frag.metadata,
                        ))
                    await session.commit()
            except (OSError, ValueError, RuntimeError) as e:
                logger.warning("tracked_research_fragment_save_failed", error=str(e))

        # Step 4: LLM synthesis
        _update_step("synthesis", "running")
        try:
            deep_text = "\n\n".join(
                f"[{f.source}/{f.fragment_type}] {f.content[:1000]}"
                for f in deep_fragments[:20]
            )
            research_data = await self._synthesize_research(name, universe, search_results, wiki_data, deep_text)
            _update_step("synthesis", "completed",
                         result_summary=f"Synthesized into {len(research_data)} fields")
        except (ValueError, json.JSONDecodeError, TimeoutError, ConnectionError) as e:
            _update_step("synthesis", "failed", error=str(e))
            research_data = {"bio": f"Research data for {name}", "powers": [], "key_relationships": []}

        # Step 5: Fact extraction
        _update_step("fact_extraction", "running")
        try:
            fact_bank = await self._extract_facts(name, research_data, search_results, deep_fragments)
            job["facts_found"] = len(fact_bank)
            _update_step("fact_extraction", "completed",
                         result_summary=f"{len(fact_bank)} facts extracted")
        except (ValueError, json.JSONDecodeError, TimeoutError, ConnectionError) as e:
            _update_step("fact_extraction", "failed", error=str(e))
            fact_bank = []

        # Step 6: Image sourcing
        _update_step("image_sourcing", "running")
        try:
            images = await self._source_images(character_id, name, universe, franchise)
            job["images_found"] = len(images)
            _update_step("image_sourcing", "completed",
                         result_summary=f"{len(images)} images sourced")
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, ConnectionError) as e:
            _update_step("image_sourcing", "failed", error=str(e))
            images = []

        # Step 7: Save results to database
        _update_step("save_results", "running")
        try:
            source_types = set(f.source for f in deep_fragments)
            depth_score = min(100.0, (
                len(search_results) * 1.5 +
                len(wiki_data) * 10 +
                len(deep_fragments) * 3 +
                len(source_types) * 15 +
                len(fact_bank) * 1.5
            ))

            # Extract relationship map from research data
            rel_map = self._extract_relationship_map(research_data)

            async with get_session() as session:
                row = await session.get(CharacterModel, character_id)
                if row:
                    row.research_data = research_data
                    row.fact_bank = fact_bank
                    row.research_status = "completed"
                    row.last_researched = datetime.now(timezone.utc)
                    row.research_sources = list(source_types)
                    row.research_depth_score = depth_score
                    if rel_map:
                        row.relationship_map = rel_map
                    if images:
                        row.image_url = images[0].get("url")
                        row.image_urls = [img.get("url") for img in images[:10]]
                    await session.commit()

            job["sources_used"] = list(source_types)
            job["depth_score"] = depth_score
            _update_step("save_results", "completed",
                         result_summary=f"Saved with depth score {depth_score:.1f}, {len(rel_map)} relationships")
        except (OSError, ValueError, RuntimeError) as e:
            _update_step("save_results", "failed", error=str(e))
            raise  # Re-raise so the job is marked as failed

        logger.info("tracked_research_completed",
                     character_id=character_id, name=name,
                     facts=len(fact_bank), images=len(images),
                     depth_score=depth_score)

    # ==================================================================
    # BATCH RESEARCH
    # ==================================================================

    async def batch_research(self, universe: Optional[str] = None, limit: int = 24) -> Dict[str, Any]:
        """Research multiple unresearched characters sequentially (inline, not background tasks)."""
        chars = await self.list_characters(
            universe=universe,
            research_status="pending",
            limit=limit,
        )
        # Also include failed ones for retry
        failed = await self.list_characters(
            universe=universe,
            research_status="failed",
            limit=limit,
        )
        chars.extend(failed)

        researched = 0
        skipped = 0
        errors = []

        # Run research inline (sequentially) to avoid overloading LLM
        for char in chars[:limit]:
            try:
                logger.info("batch_research_starting", character=char.name)
                # Mark as researching
                async with get_session() as session:
                    row = await session.get(CharacterModel, char.id)
                    if row:
                        row.research_status = "researching"
                        await session.commit()

                # Run pipeline inline (not via create_task)
                await self._research_pipeline(char.id)
                researched += 1
                logger.info("batch_research_character_done", character=char.name, progress=f"{researched}/{len(chars[:limit])}")
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, json.JSONDecodeError, ConnectionError) as e:
                errors.append({"character": char.name, "error": str(e)})
                logger.warning("batch_research_error", character=char.name, error=str(e))

        logger.info("batch_research_done", researched=researched, skipped=skipped, errors=len(errors))
        return {
            "researched": researched,
            "skipped": skipped,
            "errors": errors,
            "total_candidates": len(chars),
        }

    # ==================================================================
    # SERIES & MULTI-CHARACTER GENERATION
    # ==================================================================

    async def generate_series(
        self,
        character_id: str,
        angle: str = "hidden_truths",
        parts: int = 3,
        story_template: Optional[str] = None,
    ) -> List[CharacterCarousel]:
        """Generate a multi-part carousel series for one character."""
        series_id = f"series-{uuid.uuid4().hex[:8]}"
        carousels = []

        for part in range(1, parts + 1):
            try:
                carousel = await self.generate_carousel(CarouselCreate(
                    character_id=character_id,
                    angle=ContentAngle(angle) if angle in [a.value for a in ContentAngle] else ContentAngle.hidden_truths,
                    story_template=story_template,
                    slide_count=6,
                    series_id=series_id,
                    series_part=part,
                ))
                carousels.append(carousel)
            except (ValueError, json.JSONDecodeError, TimeoutError, ConnectionError) as e:
                logger.warning("series_generate_failed", part=part, error=str(e))

        logger.info("series_generated", series_id=series_id, parts=len(carousels))
        return carousels

    async def generate_multi_character_carousel(
        self,
        primary_character_id: str,
        secondary_character_ids: List[str],
        angle: str = "vs_comparison",
        story_template: Optional[str] = None,
    ) -> CharacterCarousel:
        """Generate a carousel featuring multiple characters (vs, hidden_connection)."""
        # Default to multi-character templates
        if not story_template:
            template_svc = get_story_template_service()
            templates = await template_svc.list_templates()
            multi_templates = [t for t in templates if t.template_type in ("versus_breakdown", "hidden_connection")]
            if multi_templates:
                story_template = multi_templates[0].template_type

        carousel = await self.generate_carousel(CarouselCreate(
            character_id=primary_character_id,
            angle=ContentAngle(angle) if angle in [a.value for a in ContentAngle] else ContentAngle.vs_comparison,
            story_template=story_template,
            slide_count=8,
            multi_character_ids=secondary_character_ids[:3],
        ))
        return carousel

    # ==================================================================
    # BATCH OPERATIONS
    # ==================================================================

    async def batch_generate(self, req: BatchGenerateRequest) -> List[CharacterCarousel]:
        """Generate carousels for multiple characters."""
        # Get characters to generate for
        if req.character_ids:
            characters = []
            for cid in req.character_ids[:req.count]:
                char = await self.get_character(cid)
                if char:
                    characters.append(char)
        else:
            characters = await self.list_characters(
                universe=req.universe.value if req.universe else None,
                research_status="completed",
                limit=req.count,
            )

        results = []
        for char in characters:
            try:
                angle = req.angle or ContentAngle.HIDDEN_TRUTHS
                carousel = await self.generate_carousel(
                    CarouselCreate(character_id=char.id, angle=angle)
                )
                results.append(carousel)
            except (ValueError, json.JSONDecodeError, TimeoutError, ConnectionError) as e:
                logger.warning("batch_generate_failed", character=char.name, error=str(e))

        return results

    # ==================================================================
    # SEED DATA
    # ==================================================================

    async def seed_characters(self) -> List[Character]:
        """Pre-populate with iconic characters."""
        seed_data = [
            # Marvel
            {"name": "Iron Man", "universe": "marvel", "franchise": "Avengers", "real_name": "Tony Stark", "tags": ["mcu", "avengers", "genius"]},
            {"name": "Thor", "universe": "marvel", "franchise": "Avengers", "real_name": "Thor Odinson", "tags": ["mcu", "avengers", "asgard"]},
            {"name": "Loki", "universe": "marvel", "franchise": "Avengers", "real_name": "Loki Laufeyson", "tags": ["mcu", "villain", "asgard"]},
            {"name": "Spider-Man", "universe": "marvel", "franchise": "Avengers", "real_name": "Peter Parker", "tags": ["mcu", "avengers", "teen"]},
            {"name": "Black Widow", "universe": "marvel", "franchise": "Avengers", "real_name": "Natasha Romanoff", "tags": ["mcu", "avengers", "spy"]},
            {"name": "Thanos", "universe": "marvel", "franchise": "Avengers", "real_name": "Thanos", "tags": ["mcu", "villain", "titan"]},
            {"name": "Doctor Strange", "universe": "marvel", "franchise": "Avengers", "real_name": "Stephen Strange", "tags": ["mcu", "magic", "sorcerer"]},
            {"name": "Wolverine", "universe": "marvel", "franchise": "X-Men", "real_name": "Logan / James Howlett", "tags": ["xmen", "mutant", "adamantium"]},
            {"name": "Deadpool", "universe": "marvel", "franchise": "X-Men", "real_name": "Wade Wilson", "tags": ["mcu", "antihero", "comedy"]},
            {"name": "Scarlet Witch", "universe": "marvel", "franchise": "Avengers", "real_name": "Wanda Maximoff", "tags": ["mcu", "magic", "mutant"]},
            # DC
            {"name": "Batman", "universe": "dc", "franchise": "Justice League", "real_name": "Bruce Wayne", "tags": ["dc", "detective", "gotham"]},
            {"name": "Superman", "universe": "dc", "franchise": "Justice League", "real_name": "Clark Kent / Kal-El", "tags": ["dc", "krypton", "godlike"]},
            {"name": "Joker", "universe": "dc", "franchise": "Batman", "real_name": "Unknown", "tags": ["dc", "villain", "gotham"]},
            {"name": "Wonder Woman", "universe": "dc", "franchise": "Justice League", "real_name": "Diana Prince", "tags": ["dc", "amazon", "warrior"]},
            {"name": "Aquaman", "universe": "dc", "franchise": "Justice League", "real_name": "Arthur Curry", "tags": ["dc", "atlantis", "ocean"]},
            {"name": "The Flash", "universe": "dc", "franchise": "Justice League", "real_name": "Barry Allen", "tags": ["dc", "speedforce", "speedster"]},
            {"name": "Harley Quinn", "universe": "dc", "franchise": "Batman", "real_name": "Harleen Quinzel", "tags": ["dc", "villain", "antihero"]},
            {"name": "Green Lantern", "universe": "dc", "franchise": "Justice League", "real_name": "Hal Jordan", "tags": ["dc", "cosmic", "willpower"]},
            # TV / Film
            {"name": "Walter White", "universe": "tv", "franchise": "Breaking Bad", "real_name": "Walter Hartwell White", "tags": ["breakingbad", "antihero", "drama"]},
            {"name": "Darth Vader", "universe": "star_wars", "franchise": "Star Wars", "real_name": "Anakin Skywalker", "tags": ["starwars", "sith", "villain"]},
            {"name": "John Wick", "universe": "film", "franchise": "John Wick", "real_name": "Jardani Jovonovich", "tags": ["action", "assassin", "revenge"]},
            {"name": "Gandalf", "universe": "lotr", "franchise": "Lord of the Rings", "real_name": "Olórin", "tags": ["lotr", "wizard", "tolkien"]},
            {"name": "Tyrion Lannister", "universe": "tv", "franchise": "Game of Thrones", "real_name": "Tyrion Lannister", "tags": ["got", "lannister", "clever"]},
            {"name": "Michael Scott", "universe": "tv", "franchise": "The Office", "real_name": "Michael Gary Scott", "tags": ["comedy", "theoffice", "boss"]},
        ]

        created = []
        for char_data in seed_data:
            # Check if already exists
            async with get_session() as session:
                existing = await session.execute(
                    select(CharacterModel).where(CharacterModel.name == char_data["name"])
                )
                if existing.scalar_one_or_none():
                    continue

            char = await self.create_character(CharacterCreate(**char_data))
            created.append(char)

        logger.info("characters_seeded", count=len(created))
        return created

    # ==================================================================
    # STATS
    # ==================================================================

    async def get_stats(self) -> CharacterStats:
        async with get_session() as session:
            # Character counts
            total_chars = await session.scalar(
                select(sql_func.count()).select_from(CharacterModel)
            )
            researched = await session.scalar(
                select(sql_func.count()).select_from(CharacterModel)
                .where(CharacterModel.research_status == "completed")
            )

            # Carousel counts
            total_carousels = await session.scalar(
                select(sql_func.count()).select_from(CharacterCarouselModel)
            )
            status_counts = {}
            for status in ["draft", "ai_reviewed", "pending_review", "approved", "rejected", "published"]:
                count = await session.scalar(
                    select(sql_func.count()).select_from(CharacterCarouselModel)
                    .where(CharacterCarouselModel.status == status)
                )
                if count:
                    status_counts[status] = count

            # Published stats
            published = await session.scalar(
                select(sql_func.count()).select_from(CharacterCarouselModel)
                .where(CharacterCarouselModel.status == "published")
            )
            total_views = await session.scalar(
                select(sql_func.coalesce(sql_func.sum(CharacterCarouselModel.views), 0))
                .where(CharacterCarouselModel.status == "published")
            )
            total_likes = await session.scalar(
                select(sql_func.coalesce(sql_func.sum(CharacterCarouselModel.likes), 0))
                .where(CharacterCarouselModel.status == "published")
            )

            # Top characters by posts
            top_chars_q = await session.execute(
                select(CharacterModel.name, CharacterModel.posts_created, CharacterModel.total_likes)
                .order_by(CharacterModel.posts_created.desc())
                .limit(5)
            )
            top_characters = [
                {"name": r[0], "posts": r[1], "likes": r[2]}
                for r in top_chars_q.all()
            ]

            # Top angles
            angle_q = await session.execute(
                select(
                    CharacterCarouselModel.angle,
                    sql_func.count().label("count"),
                )
                .group_by(CharacterCarouselModel.angle)
                .order_by(sql_func.count().desc())
                .limit(5)
            )
            top_angles = [{"angle": r[0], "count": r[1]} for r in angle_q.all()]

        return CharacterStats(
            total_characters=total_chars or 0,
            characters_researched=researched or 0,
            total_carousels=total_carousels or 0,
            carousels_by_status=status_counts,
            total_published=published or 0,
            total_views=total_views or 0,
            total_likes=total_likes or 0,
            avg_engagement_rate=0.0,
            top_characters=top_characters,
            top_angles=top_angles,
        )

    # ==================================================================
    # BRAIN INTEGRATION
    # ==================================================================

    async def _get_brain_context(self, character_name: str, angle: str) -> Dict[str, Any]:
        """Fetch brain learnings to inject into carousel generation prompt."""
        context = {}
        try:
            from app.services.zero_brain_service import get_zero_brain_service
            brain = get_zero_brain_service()

            # Episodic memory: find similar successful carousels
            memory_results = await brain.search_memory(
                f"carousel {character_name} {angle} engagement",
                namespace="content",
                limit=3,
            )
            if memory_results:
                context["past_experience"] = [r.memory.content for r in memory_results]

            # Get content domain learnings
            learnings = await brain.get_learnings(domain="content", days=30, limit=5)
            if learnings:
                context["learnings"] = learnings

        except (ValueError, KeyError, TypeError, ImportError) as e:
            logger.debug("brain_context_failed", error=str(e))

        return context

    # ==================================================================
    # CAROUSEL SERIES
    # ==================================================================

    async def generate_carousel_series(
        self, character_id: str, template_type: Optional[str] = None, parts: int = 3
    ) -> List[CharacterCarousel]:
        """Generate a multi-part carousel series with cliffhangers."""
        char = await self.get_character(character_id)
        if not char:
            raise ValueError(f"Character {character_id} not found")

        series_id = self._generate_id("cs")
        angles = ["hidden_truths", "dark_facts", "behind_scenes", "fan_theories", "origin_story"]
        carousels = []

        for part_num in range(1, parts + 1):
            angle = angles[(part_num - 1) % len(angles)]
            data = CarouselCreate(
                character_id=character_id,
                angle=ContentAngle(angle),
                story_template=template_type,
                series_id=series_id,
                series_part=part_num,
                slide_count=6,
            )
            try:
                carousel = await self.generate_carousel(data)
                carousels.append(carousel)
            except (ValueError, json.JSONDecodeError, TimeoutError, ConnectionError) as e:
                logger.warning("series_generation_failed", part=part_num, error=str(e))

        return carousels

    # ==================================================================
    # SMART BATCH GENERATION
    # ==================================================================

    async def smart_batch_generate(self, count: int = 12) -> Dict[str, Any]:
        """Smart batch: prioritizes characters, rotates angles/templates, auto-reviews.

        Includes angle diversity enforcement: underused angles get priority,
        and no more than 3 carousels per angle per batch.
        """
        characters = await self.list_characters(research_status="completed")
        if not characters:
            return {"generated": 0, "top_scored": [], "needs_work": [], "message": "No researched characters"}

        # Score characters by content potential
        scored = []
        for char in characters:
            score = 0.0
            score += min(len(char.fact_bank or []) * 2, 60)
            if char.last_researched:
                days_old = (datetime.now(timezone.utc) - char.last_researched).days
                score += max(0, 30 - days_old)
            score += max(0, 20 - (char.posts_created or 0) * 2)
            score += min(char.avg_engagement * 100, 20)
            scored.append((score, char))
        scored.sort(key=lambda x: x[0], reverse=True)

        # Get available templates
        template_svc = get_story_template_service()
        templates = await template_svc.list_templates()
        template_types = [t.template_type for t in templates] if templates else [None]

        # Angle diversity: prefer underused angles
        underused_angles = await self._get_underused_angles(limit=len(ContentAngle))
        angles = [ContentAngle(a) for a in underused_angles] if underused_angles else list(ContentAngle)
        angle_usage_this_batch: Dict[str, int] = {}
        max_per_angle = 3

        generated = []
        top_scored = []
        needs_work = []

        for idx, (_, char) in enumerate(scored[:count]):
            # Pick angle with diversity enforcement
            selected_angle = None
            for candidate in angles:
                angle_val = candidate.value if hasattr(candidate, "value") else candidate
                if angle_usage_this_batch.get(angle_val, 0) < max_per_angle:
                    selected_angle = candidate
                    break
            if selected_angle is None:
                selected_angle = angles[idx % len(angles)]

            angle = selected_angle
            angle_val = angle.value if hasattr(angle, "value") else angle
            angle_usage_this_batch[angle_val] = angle_usage_this_batch.get(angle_val, 0) + 1
            # Rotate angles for next iteration
            angles = angles[1:] + angles[:1]

            template = template_types[idx % len(template_types)]
            try:
                carousel = await self.generate_carousel(CarouselCreate(
                    character_id=char.id,
                    angle=angle,
                    story_template=template,
                    slide_count=6,
                ))
                # Auto AI-review
                carousel = await self.ai_review_carousel(carousel.id)
                generated.append(carousel)

                if carousel.ai_review and carousel.ai_review.get("overall_score", 0) >= 7:
                    top_scored.append(carousel.id)
                else:
                    needs_work.append(carousel.id)

            except (ValueError, json.JSONDecodeError, TimeoutError, ConnectionError) as e:
                logger.warning("smart_batch_failed", char=char.name, error=str(e))

        return {
            "generated": len(generated),
            "top_scored": top_scored,
            "needs_work": needs_work,
        }

    # ==================================================================
    # PRIORITY REVIEW QUEUE
    # ==================================================================

    async def list_review_queue_smart(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Review queue sorted by predicted viral potential."""
        queue = await self.list_review_queue(limit=limit * 2)

        scored_queue = []
        for carousel in queue:
            priority = 50
            if carousel.ai_review:
                priority += carousel.ai_review.get("overall_score", 5) * 5
                priority += carousel.ai_review.get("hook_strength", 5) * 3
            if carousel.story_template:
                priority += 10
            if carousel.multi_character_ids:
                priority += 15
            scored_queue.append((priority, carousel))

        scored_queue.sort(key=lambda x: x[0], reverse=True)
        return [c for _, c in scored_queue[:limit]]

    async def get_source_analytics(self) -> Dict[str, Any]:
        """Get research source effectiveness analytics."""
        from app.db.models import CharacterResearchFragmentModel
        async with get_session() as session:
            result = await session.execute(
                select(CharacterResearchFragmentModel)
            )
            fragments = result.scalars().all()

        source_stats: Dict[str, Dict[str, Any]] = {}
        for frag in fragments:
            src = frag.source or "unknown"
            if src not in source_stats:
                source_stats[src] = {"fragment_count": 0, "total_relevance": 0.0}
            source_stats[src]["fragment_count"] += 1
            source_stats[src]["total_relevance"] += (frag.relevance_score or 0.5)

        sources = []
        for src, stats in sorted(source_stats.items(), key=lambda x: x[1]["fragment_count"], reverse=True):
            avg_rel = stats["total_relevance"] / stats["fragment_count"] if stats["fragment_count"] > 0 else 0
            sources.append({"source": src, "fragment_count": stats["fragment_count"], "avg_relevance": avg_rel})

        return {"sources": sources, "total_fragments": len(fragments)}

    # ==================================================================
    # PUBLISHING PIPELINE
    # ==================================================================

    async def queue_for_publishing(
        self, carousel_id: str, platform: str = "tiktok", schedule_at: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """Queue carousel for publishing. Must be approved first."""
        async with get_session() as session:
            row = await session.get(CharacterCarouselModel, carousel_id)
            if not row:
                raise ValueError(f"Carousel {carousel_id} not found")
            if row.status != "approved":
                raise ValueError(f"Carousel must be approved first (current: {row.status})")
            row.publish_status = "queued"
            row.publish_platform = platform
            await session.commit()
            return {
                "carousel_id": carousel_id,
                "publish_status": "queued",
                "publish_platform": platform,
                "published_at": None,
                "publish_url": row.publish_url,
                "download_urls": row.download_urls,
            }

    async def publish_carousel(self, carousel_id: str) -> Dict[str, Any]:
        """Render and export carousel for publishing."""
        from app.services.carousel_renderer_service import get_carousel_renderer

        async with get_session() as session:
            row = await session.get(CharacterCarouselModel, carousel_id)
            if not row:
                raise ValueError(f"Carousel {carousel_id} not found")
            if row.publish_status != "queued":
                raise ValueError("Carousel not queued for publishing")
            row.publish_status = "publishing"
            await session.commit()

            slides = row.slides or []
            text_overlay_specs = row.text_overlay_specs or []
            character_id = row.character_id

        # Get character image for rendering
        char = await self.get_character(character_id)
        image_url = char.image_url if char else None
        image_urls = char.image_urls if char else []

        # Render all slides
        renderer = get_carousel_renderer()
        render_result = await renderer.render_carousel(
            carousel_id=carousel_id,
            slides=slides,
            text_overlay_specs=text_overlay_specs,
            character_image_url=image_url,
            character_image_urls=image_urls,
        )
        rendered_paths = render_result.get("paths", [])

        # Mark published
        now = datetime.now(timezone.utc)
        async with get_session() as session:
            row = await session.get(CharacterCarouselModel, carousel_id)
            if row:
                row.publish_status = "published"
                row.published_at = now
                row.download_urls = rendered_paths
                row.status = "published"
                row.watermark_applied = True
                await session.commit()

        return {
            "carousel_id": carousel_id,
            "publish_status": "published",
            "download_urls": rendered_paths,
            "published_at": now.isoformat(),
            "publish_platform": row.publish_platform if row else None,
            "publish_url": None,
        }

    async def get_download_urls(self, carousel_id: str) -> List[str]:
        """Get rendered slide paths for manual download."""
        from app.services.carousel_renderer_service import get_carousel_renderer
        renderer = get_carousel_renderer()
        return await renderer.list_rendered(carousel_id)

    async def generate_caption_variants(self, carousel_id: str, count: int = 3) -> List[str]:
        """Generate A/B caption variants for a carousel."""
        async with get_session() as session:
            row = await session.get(CharacterCarouselModel, carousel_id)
            if not row:
                raise ValueError("Carousel not found")
            character_name = ""
            char = await session.get(CharacterModel, row.character_id)
            if char:
                character_name = char.name
            hook_text = row.hook_text or ""
            angle = row.angle or ""

        variants = []
        for i in range(count):
            prompt = (
                f"Write a TikTok caption variant #{i+1} for a carousel about {character_name}. "
                f"Hook: {hook_text}. Angle: {angle}. Keep under 150 chars. Include 3 hashtags. "
                f"Return ONLY the caption text, no explanation.\n\n/no_think"
            )
            try:
                response = await self._ollama.chat(
                    prompt=prompt,
                    system="You are a viral TikTok caption writer. Return only the caption.",
                    model=RESEARCH_LLM_MODEL,
                    temperature=0.9,
                    num_predict=256,
                    timeout=60,
                )
                text = response.strip() if isinstance(response, str) else str(response)
                variants.append(text)
            except (ValueError, TimeoutError, ConnectionError) as e:
                logger.debug("caption_variant_failed", variant=i, error=str(e))

        return variants

    async def export_for_platform(self, carousel_id: str, platform: str) -> List[str]:
        """Export carousel in platform-specific format.

        Platform dimension targets:
        - tiktok: 1080x1350
        - instagram: 1080x1080
        - youtube: 1280x720

        Currently returns rendered slides as-is (TikTok format is default).
        """
        return await self.get_download_urls(carousel_id)

    # ==================================================================
    # ANGLE DIVERSITY HELPERS
    # ==================================================================

    async def _get_underused_angles(self, limit: int = 5) -> List[str]:
        """Return angles with fewer carousels, useful for diversifying content."""
        all_angles = [a.value for a in ContentAngle]
        async with get_session() as session:
            angle_counts = await session.execute(
                select(
                    CharacterCarouselModel.angle,
                    sql_func.count().label("cnt"),
                )
                .group_by(CharacterCarouselModel.angle)
            )
            counts = {r[0]: r[1] for r in angle_counts.all()}

        # Return angles sorted by usage count (ascending), least used first
        sorted_angles = sorted(all_angles, key=lambda a: counts.get(a, 0))
        return sorted_angles[:limit]


@lru_cache()
def get_character_content_service() -> CharacterContentService:
    return CharacterContentService()
