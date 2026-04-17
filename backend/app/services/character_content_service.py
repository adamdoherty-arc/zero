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
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.infrastructure.database import get_session
from app.infrastructure.config import get_settings
from app.infrastructure.ollama_client import OllamaClient
from app.infrastructure.llm_router import get_llm_router
from app.db.models import (
    CharacterModel, CharacterCarouselModel, CharacterImageModel,
    CharacterCarouselVersionModel,
    CharacterResearchFragmentModel, CharacterResearchStepStatModel,
    StoryTemplateModel,
)
from app.models.character_content import (
    Character, CharacterCreate, CharacterUpdate,
    CharacterCarousel, CarouselCreate, CarouselUpdate,
    CharacterImage, CharacterImageCreate,
    CarouselApproval, CarouselRejection,
    BatchGenerateRequest, CharacterStats,
    ContentAngle,
    ResearchJob, ResearchJobStep, ResearchQueueStatus, ResearchJobStatus,
    CarouselVersion,
    EnhanceCarouselRequest, EnhanceCarouselVariant, EnhanceCarouselResponse,
    ApplyEnhanceRequest, CouncilVoteRequest, CouncilVoteResponse,
    ApplyCouncilWinnerRequest, RestoreVersionResponse,
    BackfillBannedHooksRequest, BackfillBannedHooksResult,
)
from app.services.searxng_service import get_searxng_service
from app.services.character_research_sources import get_research_sources
from app.services.story_template_service import get_story_template_service
from app.services.music_library_service import get_music_library_service
from app.services.character_content_utils import (
    generate_id,
    sanitize_text,
    parse_json_response,
    repair_truncated_json,
    is_generic_hook,
    rewrite_generic_hook,
    sanitize_carousel,
    character_to_pydantic,
    carousel_to_pydantic,
    image_to_pydantic,
    version_to_pydantic,
)

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Prompt instrumentation helpers
# ---------------------------------------------------------------------------

async def _select_prompt_variant(task_type: str, default_template: str, default_system: str):
    """Select best active variant for a task type. Fall back to defaults.

    Returns (variant_or_none, template_text, system_prompt_text).
    """
    try:
        from app.services.prompt_evolution_service import get_prompt_evolution_service
        pe_svc = get_prompt_evolution_service()
        variant = await pe_svc.select_best(task_type)
        if variant:
            vparams = variant.parameters or {}
            system = vparams.get("system_prompt") or default_system
            return variant, variant.prompt_template, system
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, AttributeError, RuntimeError, TypeError, SQLAlchemyError) as e:
        logger.debug("variant_select_failed", task_type=task_type, error=str(e))
    return None, default_template, default_system


async def _record_prompt_run_safe(
    *,
    variant_id,
    task_type,
    source,
    source_id,
    provider,
    model="unknown",
    system_prompt,
    user_prompt,
    rendered_variables,
    response_text,
    success,
    error_type=None,
    error_message=None,
    latency_ms=0.0,
    context=None,
):
    """Persist a prompt run. Never raise."""
    try:
        from app.services.prompt_evolution_service import get_prompt_evolution_service
        from app.models.brain import PromptRunCreate

        pe_svc = get_prompt_evolution_service()
        await pe_svc.record_run(PromptRunCreate(
            variant_id=variant_id,
            task_type=task_type,
            source=source,
            source_id=source_id,
            provider=provider,
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            rendered_variables=rendered_variables or {},
            response_text=response_text,
            success=success,
            error_type=error_type,
            error_message=(error_message or "")[:1000] if error_message else None,
            latency_ms=latency_ms,
            context=context or {},
        ))
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, AttributeError, RuntimeError, TypeError, SQLAlchemyError) as e:
        logger.debug("prompt_run_record_failed_silent", task_type=task_type, error=str(e))


# In-memory research progress tracking (survives within process lifetime)
_research_queue: Dict[str, Any] = {
    "jobs": {},          # job_id -> ResearchJob dict
    "order": [],         # ordered list of job_ids
    "running": False,
    "started_at": None,
    "cancel_requested": False,
}

# Serialize all heavy Ollama calls across parallel characters so the GPU
# doesn't thrash. Multiple characters can race through the cheap I/O steps
# (searxng, wiki, deep_research, image_sourcing) concurrently, then queue
# here for synthesis and fact_extraction.
_OLLAMA_SEMAPHORE = asyncio.Semaphore(1)

# Fallback per-step duration priors used when we don't yet have enough history
# to compute averages (n < 3). Values in milliseconds, rough defaults based on
# observed behaviour. See get_step_duration_averages().
_STEP_DURATION_PRIORS_MS: Dict[str, int] = {
    "searxng_search": 15_000,
    "wiki_scrape": 8_000,
    "deep_research": 30_000,
    "synthesis": 240_000,
    "fact_extraction": 180_000,
    "image_sourcing": 45_000,
    "save_results": 2_000,
}

# Cached aggregate of per-step durations. Refreshed lazily every TTL seconds.
_step_stats_cache: Dict[str, Any] = {
    "data": None,          # Dict[step_name, {avg_ms, p50_ms, p95_ms, n}]
    "expires_at": 0.0,     # monotonic deadline
}
_STEP_STATS_TTL_SEC = 60.0

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
- Notable storylines: specific comic arcs, episodes, or movie plots where something dramatic happened (use category "storylines")

Research data:
{research_text}

Return JSON array. Each fact:
{{
  "text": "The actual fact written in engaging, direct language",
  "category": "origin|powers|relationships|hidden_details|fan_theories|behind_scenes|character_evolution|dark_facts|storylines",
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
- Slide 1: A scroll-stopping hook that is UNIQUE to THIS character and THIS angle. It must reference a specific fact, name, object, or secret from their story. Never reuse the same hook template across different characters.
- Slides 2-6: Numbered facts with bold, engaging text
- Final slide: Engagement CTA
- Caption: Emotional, debate-sparking, with emojis
- Hashtags: character + franchise + niche tags

HOOK DIVERSITY RULES (strict):
- Every hook must be tailored to the character. If a reader could swap in a different character and the hook still works, it is too generic. Rewrite it.
- Do NOT start hooks with stock phrases like "The Hammer Lie:", "Nobody talks about this", or "What they do not want you to know". These are banned.
- Pick a hook style that matches the facts: a pointed question, a stat drop, a named secret, a contradiction, a "wait until you see slide X" tease, or a rewritten origin line. Vary the style between carousels.
- The first line must contain at least one proper noun or concrete reference drawn from the character facts (a name, a weapon, a planet, a relationship, a line of dialogue, etc.).

CRITICAL: Never use em dashes, markdown asterisks, or any formatting markup. Plain text only.

Return ONLY valid JSON."""

CAROUSEL_GENERATION_PROMPT = """Create a TikTok photo carousel about {name} ({universe}) with angle: {angle}.

Character facts available:
{facts_text}

Generate a {slide_count}-slide carousel. Return JSON:
{{
  "title": "Internal reference title (5-8 words, descriptive, NOT the hook)",
  "hook_text": "A scroll-stopping first line that is unique to {name}. Reference a specific fact, name, object, or twist from the facts above. Do NOT use generic openers like 'The Hammer Lie:', 'Nobody talks about...', 'What they never told you'. Examples of good hook shapes (pick different shape each time, never reuse template): 'Vader killed his first Jedi at age 9.', 'Why Luke's green lightsaber is the most spoiled twist in Star Wars.', 'Batman's richest year was his worst.', '3 things Tony Stark built before the suit.' Your hook must not be swappable to another character.",
  "slides": [
    {{
      "slide_num": 1,
      "text": "Slide 1 on-image copy. Usually matches the hook, but can be a shorter punchline version. Should immediately hint at the promise of slides 2-6.",
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

Hook construction checklist (every item must be true):
- The hook mentions {name} or a proper noun pulled from the facts (a name, weapon, place, organization, relationship, or line of dialogue).
- The hook is NOT a reused template. It is written fresh for this character and angle.
- The hook passes the swap test: if you replaced {name} with another character, the hook would stop making sense.
- The hook is 4-14 words on slide 1. Short and sharp beats long and vague.

Style rules:
- Text overlays: Bold white text on dark images, short punchy lines
- Use numbered facts (1. 2. 3. etc.)
- Include dramatic pauses with "..."
- End text with impact words or emojis ( mind-blown, lightning, skull, etc.)
- Caption should provoke comments ("Comment which fact surprised you most")

Hashtag strategy (include exactly 9 hashtags in this mix):
- 3 broad hashtags (e.g., marvel, dc, anime, moviefacts, characterfacts)
- 3 niche hashtags specific to the character (e.g., lokilore, marveltheory, batmanfacts)
- 3 trending/topical hashtags (e.g., fyp, viral, didyouknow, mindblown)

FORMATTING RULES (strict):
- NEVER use em dashes. Use periods, commas, or colons instead.
- NEVER use markdown asterisks (*text* or **text**). Write plain text only.
- NEVER use parenthetical asides with dashes. Use separate sentences."""

AI_REVIEW_SYSTEM_PROMPT = """You are a TikTok content strategist reviewing carousel posts for viral potential.
Score each dimension 1-10 and provide actionable feedback.
Return ONLY valid JSON."""

FINAL_REVIEW_SYSTEM_PROMPT = """You are a top-tier viral TikTok editor. You already know the carousel passed a first-pass review.
Your job is the final polish: tighten the hook, sharpen the caption, validate fact sequencing, and protect the emotional arc.
Score each viral-instinct dimension 1-10 with discipline. Be honest: a 10 is rare.
Return ONLY valid JSON. Never use em dashes, markdown asterisks, or formatting markup in polished text."""

FINAL_REVIEW_PROMPT = """Final-stage viral review for this character carousel:

Character: {name} ({universe})
Angle: {angle}
Hook: {hook_text}

Slides:
{slides_text}

Caption: {caption}
Hashtags: {hashtags}

Stage-1 review scores:
{stage1_scores}

Return ONLY this JSON shape:
{{
  "hook_tension": score (1-10, does the first slide force the swipe?),
  "fact_sequencing": score (1-10, do facts escalate and pay off?),
  "emotional_arc": score (1-10, does the carousel deliver a feeling?),
  "caption_cta": score (1-10, does the caption reward engagement?),
  "overall_score": score (1-10, composite),
  "verdict": "approve" | "revise" | "kill",
  "polish_suggestions": ["1-3 concrete fixes"],
  "final_hook": "optional: your tightened hook (only if it clearly beats current)",
  "final_caption": "optional: your sharper caption (only if it clearly beats current)"
}}

CRITICAL: If you provide final_hook or final_caption, plain text only. No em dashes, no asterisks, no markdown."""

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
}}

CRITICAL: If you provide rewrite_hook or rewrite_caption, NEVER use em dashes, markdown asterisks (*text* or **text**), or formatting markup. Write plain text only."""


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class CharacterContentService:
    """Manages character content creation pipeline."""

    def __init__(self):
        self._ollama = OllamaClient()  # All generation uses Ollama (free)

    # ==================================================================
    # CHARACTER CRUD
    # ==================================================================

    async def create_character(self, data: CharacterCreate) -> Character:
        char_id = generate_id("ch")
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
            return character_to_pydantic(row)

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
            rows = result.scalars().all()

            char_ids = [r.id for r in rows]
            counts: Dict[str, int] = {}
            if char_ids:
                count_result = await session.execute(
                    select(
                        CharacterCarouselModel.character_id,
                        sql_func.count(CharacterCarouselModel.id),
                    )
                    .where(CharacterCarouselModel.character_id.in_(char_ids))
                    .group_by(CharacterCarouselModel.character_id)
                )
                counts = {cid: cnt for cid, cnt in count_result.all()}
            return [character_to_pydantic(r, carousels_created=counts.get(r.id, 0)) for r in rows]

    async def get_character(self, character_id: str) -> Optional[Character]:
        async with get_session() as session:
            row = await session.get(CharacterModel, character_id)
            if not row:
                return None
            count_result = await session.execute(
                select(sql_func.count(CharacterCarouselModel.id))
                .where(CharacterCarouselModel.character_id == character_id)
            )
            carousels_created = count_result.scalar() or 0
            return character_to_pydantic(row, carousels_created=carousels_created)

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
            return character_to_pydantic(row)

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
            char = character_to_pydantic(row)

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
                            id=generate_id("rf"),
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

            # Save everything. Mark "needs_retry" when fact extraction yielded nothing
            # so batch-research picks them up on the next cycle instead of silently
            # declaring the character fully researched.
            final_status = "completed" if len(fact_bank) >= 3 else "needs_retry"
            async with get_session() as session:
                row = await session.get(CharacterModel, character_id)
                if row:
                    row.research_data = research_data
                    row.fact_bank = fact_bank
                    row.research_status = final_status
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
                        depth_score=depth_score, relationships=len(rel_map),
                        status=final_status)

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
            async with _OLLAMA_SEMAPHORE:
                raw = await self._ollama.chat(
                    prompt=prompt,
                    system=RESEARCH_SYSTEM_PROMPT,
                    task_type="character_research",
                    temperature=0.3,
                    num_predict=16384,
                    timeout=900,
                    max_retries=1,
                )
            return parse_json_response(raw, name)
        except (ValueError, json.JSONDecodeError, TimeoutError, ConnectionError) as e:
            logger.warning("research_synthesis_failed", name=name, error=str(e))
            return {"bio": f"Research data for {name}", "powers": [], "key_relationships": []}

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

        _fact_default_system = "You are a pop culture fact compiler. Return ONLY a JSON array of facts. No explanation."
        research_text_full = f"{research_text}\n\nSnippets:\n{source_snippets[:2000]}\n\nDeep sources:\n{deep_snippets[:2000]}"
        variant, _fact_template, _fact_system = await _select_prompt_variant(
            "character_research_facts",
            default_template=FACT_EXTRACTION_PROMPT,
            default_system=_fact_default_system,
        )
        try:
            prompt = _fact_template.format(
                name=name,
                research_text=research_text_full,
            ) + "\n\n/no_think"
        except (KeyError, ValueError, IndexError):
            prompt = FACT_EXTRACTION_PROMPT.format(
                name=name,
                research_text=research_text_full,
            ) + "\n\n/no_think"

        raw = None
        _t_start = time.monotonic()
        _run_success = True
        _run_error_type = None
        _run_error_message = None
        try:
            async with _OLLAMA_SEMAPHORE:
                raw = await self._ollama.chat(
                    prompt=prompt,
                    system=_fact_system,
                    task_type="character_research",
                    temperature=0.4,
                    num_predict=16384,
                    timeout=900,
                    max_retries=1,
                )
        except (TimeoutError, ConnectionError, ValueError) as e:
            _run_success = False
            _run_error_type = type(e).__name__
            _run_error_message = str(e)
        finally:
            await _record_prompt_run_safe(
                variant_id=variant.id if variant else None,
                task_type="character_research_facts",
                source="character_content",
                source_id=name,
                provider="ollama",
                system_prompt=_fact_system,
                user_prompt=prompt,
                rendered_variables={"name": name, "research_text_chars": len(research_text_full)},
                response_text=raw if isinstance(raw, str) else None,
                success=_run_success,
                error_type=_run_error_type,
                error_message=_run_error_message,
                latency_ms=(time.monotonic() - _t_start) * 1000,
            )

        if not _run_success or raw is None:
            logger.warning("fact_extraction_failed", name=name, error=_run_error_message)
            fallback = []
            for fact_text in research_data.get("fun_facts", []):
                fallback.append({"text": fact_text, "category": "hidden_details", "surprise_score": 5, "source": "research", "verified": False})
            for fact_text in research_data.get("behind_the_scenes", []):
                fallback.append({"text": fact_text, "category": "behind_scenes", "surprise_score": 6, "source": "research", "verified": False})
            for fact_text in research_data.get("controversies", []):
                fallback.append({"text": fact_text, "category": "dark_facts", "surprise_score": 7, "source": "research", "verified": False})
            return fallback

        try:
            facts = parse_json_response(raw, f"facts_{name}")
            if isinstance(facts, list):
                for fact in facts:
                    if fact.get("text"):
                        fact["text"] = sanitize_text(fact["text"])
                return sorted(facts, key=lambda f: f.get("surprise_score", 0), reverse=True)
            fact_list = facts.get("facts", []) if isinstance(facts, dict) else []
            for fact in fact_list:
                if fact.get("text"):
                    fact["text"] = sanitize_text(fact["text"])
            return fact_list
        except (ValueError, json.JSONDecodeError) as e:
            logger.warning("fact_extraction_parse_failed", name=name, error=str(e))
            fallback = []
            for fact_text in research_data.get("fun_facts", []):
                fallback.append({"text": fact_text, "category": "hidden_details", "surprise_score": 5, "source": "research", "verified": False})
            for fact_text in research_data.get("behind_the_scenes", []):
                fallback.append({"text": fact_text, "category": "behind_scenes", "surprise_score": 6, "source": "research", "verified": False})
            for fact_text in research_data.get("controversies", []):
                fallback.append({"text": fact_text, "category": "dark_facts", "surprise_score": 7, "source": "research", "verified": False})
            return fallback

    async def _validate_image_url(self, url: str) -> Dict[str, Any]:
        """HTTP HEAD + partial download to validate image URL and extract dimensions."""
        result: Dict[str, Any] = {
            "is_valid": False, "width": None, "height": None,
            "content_type": None, "file_size": 0,
        }
        try:
            async with aiohttp.ClientSession() as http:
                async with http.head(
                    url, timeout=aiohttp.ClientTimeout(total=8),
                    allow_redirects=True,
                ) as resp:
                    if resp.status != 200:
                        return result
                    ct = resp.headers.get("content-type", "")
                    if not ct.startswith("image/"):
                        return result
                    result["content_type"] = ct
                    cl = resp.headers.get("content-length")
                    if cl:
                        result["file_size"] = int(cl)

                # Download first 64KB to check dimensions via PIL
                async with http.get(
                    url, timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status != 200:
                        return result
                    chunk = await resp.content.read(65536)

            from PIL import Image
            import io
            img = Image.open(io.BytesIO(chunk))
            result["width"] = img.width
            result["height"] = img.height
            result["is_valid"] = img.width >= 800  # minimum 800px wide for TikTok
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError, ValueError):
            pass
        return result

    async def _source_images(self, character_id: str, name: str,
                              universe: str, franchise: str) -> List[Dict]:
        """Multi-source image discovery with validation and quality scoring."""
        from app.services.image_source_service import get_image_source_service, compute_quality_score

        # Load blocked + existing URLs to skip duplicates and re-imports
        skip_urls: set = set()
        async with get_session() as session:
            char_row = await session.get(CharacterModel, character_id)
            if char_row:
                skip_urls.update(char_row.blocked_image_urls or [])
            existing = await session.execute(
                select(CharacterImageModel.url)
                .where(CharacterImageModel.character_id == character_id)
            )
            skip_urls.update(r[0] for r in existing.all())

        image_svc = get_image_source_service()
        raw_images = await image_svc.discover_images(
            name=name, universe=universe, franchise=franchise, max_per_source=10,
        )

        images = []
        for img_data in raw_images[:30]:  # Store top 30 validated images
            if img_data["url"] in skip_urls:
                continue
            img_id = generate_id("ci")
            try:
                async with get_session() as session:
                    session.add(CharacterImageModel(
                        id=img_id,
                        character_id=character_id,
                        url=img_data["url"],
                        source=img_data.get("source", "searxng"),
                        query_used=img_data.get("query_used"),
                        width=img_data.get("width"),
                        height=img_data.get("height"),
                        quality_score=img_data.get("quality_score", 0.0),
                        content_type=img_data.get("content_type"),
                        file_size=img_data.get("file_size"),
                    ))
                    await session.commit()
                images.append({"id": img_id, **img_data})
            except (IntegrityError, ValueError, OSError):
                pass

        logger.info("image_sourcing_done", name=name, images_stored=len(images),
                     sources_found=len(set(img.get("source") for img in images)))
        return images

    # ==================================================================
    # IMAGE MANAGEMENT
    # ==================================================================

    async def list_images(
        self,
        character_id: str,
        include_invalid: bool = False,
    ) -> List[CharacterImage]:
        async with get_session() as session:
            query = (
                select(CharacterImageModel)
                .where(CharacterImageModel.character_id == character_id)
                .order_by(CharacterImageModel.is_primary.desc(), CharacterImageModel.created_at.desc())
            )
            if not include_invalid:
                query = query.where(CharacterImageModel.is_valid == True)
            result = await session.execute(query)
            return [image_to_pydantic(r) for r in result.scalars().all()]

    async def add_image(self, data: CharacterImageCreate) -> CharacterImage:
        img_id = generate_id("ci")
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
            return image_to_pydantic(row)

    async def validate_all_images(self, limit: int = 100) -> Dict[str, Any]:
        """Validate all unvalidated images. Marks broken ones is_valid=False, populates dimensions."""
        async with get_session() as session:
            result = await session.execute(
                select(CharacterImageModel)
                .where(CharacterImageModel.width.is_(None))
                .where(CharacterImageModel.is_valid == True)
                .limit(limit)
            )
            images = result.scalars().all()

        validated = 0
        invalidated = 0
        for img in images:
            validation = await self._validate_image_url(img.url)
            async with get_session() as session:
                row = await session.get(CharacterImageModel, img.id)
                if not row:
                    continue
                if validation["is_valid"]:
                    row.width = validation["width"]
                    row.height = validation["height"]
                    validated += 1
                else:
                    row.is_valid = False
                    invalidated += 1
                await session.commit()

        logger.info("image_validation_complete",
                     validated=validated, invalidated=invalidated, total=len(images))
        return {
            "total_checked": len(images),
            "validated": validated,
            "invalidated": invalidated,
        }

    async def purge_broken_images(self, limit: int = 200) -> Dict[str, Any]:
        """Validate existing images and auto-delete broken ones.

        For each image whose URL no longer resolves (404, DNS failure, non-image
        content, or PIL decode failure), delete the row, add the URL to the
        character's blocklist, remove it from image_urls, and reassign the primary
        image_url if necessary. Prevents re-import via the blocklist.
        """
        async with get_session() as session:
            result = await session.execute(
                select(CharacterImageModel)
                .where(CharacterImageModel.is_valid == True)
                .order_by(CharacterImageModel.created_at.asc())
                .limit(limit)
            )
            images = result.scalars().all()
            # Detach plain fields so the session can close before network I/O.
            image_rows = [
                {"id": r.id, "character_id": r.character_id, "url": r.url}
                for r in images
            ]

        purged = 0
        kept = 0
        for img in image_rows:
            validation = await self._validate_image_url(img["url"])
            if validation["is_valid"]:
                kept += 1
                continue

            # Broken image: delete row and blocklist URL.
            async with get_session() as session:
                row = await session.get(CharacterImageModel, img["id"])
                if row:
                    await session.delete(row)
                char_row = await session.get(CharacterModel, img["character_id"])
                if char_row:
                    blocked = list(char_row.blocked_image_urls or [])
                    if img["url"] not in blocked:
                        blocked.append(img["url"])
                        char_row.blocked_image_urls = blocked
                    urls = list(char_row.image_urls or [])
                    if img["url"] in urls:
                        urls.remove(img["url"])
                        char_row.image_urls = urls
                    if char_row.image_url == img["url"]:
                        char_row.image_url = urls[0] if urls else None
                await session.commit()
            purged += 1
            logger.info("broken_image_purged",
                         character_id=img["character_id"],
                         image_id=img["id"],
                         url=img["url"])

        logger.info("purge_broken_images_complete",
                     checked=len(image_rows), purged=purged, kept=kept)
        return {
            "total_checked": len(image_rows),
            "purged": purged,
            "kept": kept,
        }

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
            "storyline_recap": ["storylines", "character_evolution", "origin"],
            "power_ranking": ["powers", "hidden_details", "origin"],
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

        _carousel_variant = None
        _carousel_system = CAROUSEL_SYSTEM_PROMPT
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
            _carousel_variant, _carousel_template, _carousel_system = await _select_prompt_variant(
                "character_carousel_generation",
                default_template=CAROUSEL_GENERATION_PROMPT,
                default_system=CAROUSEL_SYSTEM_PROMPT,
            )
            try:
                prompt = _carousel_template.format(
                    name=name,
                    universe=universe,
                    angle=angle.replace("_", " ").title(),
                    facts_text=facts_text,
                    slide_count=slide_count,
                )
            except (KeyError, ValueError, IndexError):
                prompt = CAROUSEL_GENERATION_PROMPT.format(
                    name=name,
                    universe=universe,
                    angle=angle.replace("_", " ").title(),
                    facts_text=facts_text,
                    slide_count=slide_count,
                )

        # Add hook style instruction to prompt
        hook_style = getattr(data, 'hook_style', None)
        content_format = getattr(data, 'content_format', None)
        if hook_style:
            hook_instructions = {
                "numbered_list": 'Hook style: Start with a number. Example: "5 Things They Don\'t Tell You About {name}..."',
                "story_opener": 'Hook style: Start with "When [character] [dramatic past tense verb]..." Example: "When {name} destroyed everything..."',
                "hot_take": 'Hook style: Bold one-sentence claim stated as fact. No questions. Example: "{name} is the most overrated character in {universe}."',
                "question": 'Hook style: Ask a dramatic question. Example: "Do you know who actually defeated {name}?"',
                "comparison": 'Hook style: Frame as a matchup. Example: "{name} vs [rival]: Only one walks away."',
                "reveal": 'Hook style: Tease a secret reveal. Example: "{name}\'s secret [noun] changes everything..."',
                "superlative": 'Hook style: Use a superlative. Example: "The most [adjective] moment in {universe} history..."',
            }
            instruction = hook_instructions.get(hook_style, "")
            if instruction:
                prompt += f"\n\n{instruction.format(name=name, universe=universe)}"

        # Add brain context to prompt if available
        if brain_context:
            brain_hint = ""
            if brain_context.get("learnings"):
                brain_hint += "\nLearnings from past carousels:\n" + "\n".join(f"- {l}" for l in brain_context["learnings"][:3])
            if brain_context.get("past_experience"):
                brain_hint += "\nPast successful patterns:\n" + "\n".join(f"- {p}" for p in brain_context["past_experience"][:2])
            if brain_hint:
                prompt += f"\n\nOptimization hints:{brain_hint}"

        _carousel_raw = None
        _c_t_start = time.monotonic()
        _c_success = True
        _c_error_type = None
        _c_error_message = None
        try:
            async with _OLLAMA_SEMAPHORE:
                _carousel_raw = await self._ollama.chat(
                    prompt=prompt,
                    system=_carousel_system,
                    task_type="character_research",
                    temperature=0.8,
                    num_predict=4096,
                    timeout=600,
                    max_retries=1,
                )
        except (TimeoutError, ConnectionError, ValueError) as e:
            _c_success = False
            _c_error_type = type(e).__name__
            _c_error_message = str(e)
        finally:
            await _record_prompt_run_safe(
                variant_id=_carousel_variant.id if _carousel_variant else None,
                task_type="character_carousel_generation",
                source="character_content",
                source_id=data.character_id,
                provider="ollama",
                system_prompt=_carousel_system,
                user_prompt=prompt,
                rendered_variables={
                    "name": name,
                    "universe": universe,
                    "angle": angle,
                    "slide_count": slide_count,
                    "template": data.story_template,
                },
                response_text=_carousel_raw if isinstance(_carousel_raw, str) else None,
                success=_c_success,
                error_type=_c_error_type,
                error_message=_c_error_message,
                latency_ms=(time.monotonic() - _c_t_start) * 1000,
                context={"character_id": data.character_id, "has_template": bool(template_prompt)},
            )

        try:
            if not _c_success or _carousel_raw is None:
                raise ValueError(_c_error_message or "carousel_generation_failed")
            result = parse_json_response(_carousel_raw, f"carousel_{name}")
            result = sanitize_carousel(result, character_name=name)
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
        carousel_id = generate_id("cc")
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
                hook_style=hook_style,
                content_format=content_format,
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
                    "model": get_llm_router().resolve("character_research"),
                    "duration_ms": duration_ms,
                    "angle": angle,
                    "hook_style": hook_style,
                    "content_format": content_format,
                    "prompt_preview": prompt[:500] if prompt else None,
                },
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)

            char_row = await session.get(CharacterModel, data.character_id)
            char_name = char_row.name if char_row else None

            carousel_id_for_review = row.id

        # Auto-invoke two-stage AI review (Stage 1 Ollama + Stage 2 Minimax/Kimi
        # for scores >= 7.0). Best-effort: review failures must not fail generation.
        # This closes the gap where generate_carousel never triggered the review
        # chain, leaving final_review_score at NULL for every carousel.
        try:
            return await self.ai_review_carousel(carousel_id_for_review)
        except (ValueError, KeyError, RuntimeError, TimeoutError) as exc:
            logger.warning(
                "carousel_auto_review_failed",
                carousel_id=carousel_id_for_review,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            async with get_session() as session:
                row = await session.get(CharacterCarouselModel, carousel_id_for_review)
                return carousel_to_pydantic(row, char_name)

    def _match_image_to_query(
        self, query: str, images: list, used_ids: set
    ) -> Optional[Any]:
        """Keyword-match an image_query against existing images' query_used fields."""
        if not query:
            return None
        query_words = set(query.lower().split())
        best_score = 0
        best_img = None
        for img in images:
            if img.id in used_ids:
                continue
            if not img.query_used:
                continue
            img_words = set(img.query_used.lower().split())
            overlap = len(query_words & img_words)
            if overlap > best_score:
                best_score = overlap
                best_img = img
        return best_img if best_score >= 2 else None

    async def _assign_slide_images(self, character_id: str, slides: List[Dict]):
        """Match images to slides using 3-tier strategy:
        1. Keyword match slide's image_query against existing images
        2. On-demand SearXNG search with slide's image_query
        3. Fallback to least-used existing image
        """
        # Load all valid images for this character, sorted by quality then usage
        async with get_session() as session:
            result = await session.execute(
                select(CharacterImageModel)
                .where(CharacterImageModel.character_id == character_id)
                .where(CharacterImageModel.is_valid == True)
                .order_by(
                    CharacterImageModel.quality_score.desc(),
                    CharacterImageModel.usage_count.asc(),
                )
            )
            existing = result.scalars().all()

        used_ids: set = set()
        assigned_ids: list = []

        for slide in slides:
            image_query = slide.get("image_query", "")
            assigned = False

            # Tier 1: Keyword match against existing images
            if image_query and existing:
                match = self._match_image_to_query(image_query, existing, used_ids)
                if match:
                    slide["image_url"] = match.url
                    used_ids.add(match.id)
                    assigned_ids.append(match.id)
                    assigned = True

            # Tier 2: On-demand SearXNG search with slide-specific query
            if not assigned and image_query:
                try:
                    searxng = get_searxng_service()
                    results = await searxng.search(
                        image_query, num_results=5, categories=["images"],
                    )
                    for r in results:
                        img_url = (
                            getattr(r, "img_src", None) or getattr(r, "url", None)
                            or (r.get("img_src") if isinstance(r, dict) else None)
                            or (r.get("url") if isinstance(r, dict) else "")
                        )
                        if not img_url or not img_url.startswith("http"):
                            continue
                        validation = await self._validate_image_url(img_url)
                        if not validation["is_valid"]:
                            continue
                        # Store new image and assign
                        img_id = generate_id("ci")
                        try:
                            async with get_session() as session:
                                session.add(CharacterImageModel(
                                    id=img_id,
                                    character_id=character_id,
                                    url=img_url,
                                    source="searxng_slide",
                                    query_used=image_query,
                                    width=validation["width"],
                                    height=validation["height"],
                                    usage_count=1,
                                ))
                                await session.commit()
                        except (ValueError, OSError):
                            pass
                        slide["image_url"] = img_url
                        used_ids.add(img_id)
                        assigned = True
                        break
                except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, ConnectionError):
                    pass

            # Tier 3: Fallback to least-used existing image
            if not assigned and existing:
                for img in existing:
                    if img.id not in used_ids:
                        slide["image_url"] = img.url
                        used_ids.add(img.id)
                        assigned_ids.append(img.id)
                        break

        # Increment usage_count for all assigned existing images
        if assigned_ids:
            async with get_session() as session:
                await session.execute(
                    update(CharacterImageModel)
                    .where(CharacterImageModel.id.in_(assigned_ids))
                    .values(usage_count=CharacterImageModel.usage_count + 1)
                )
                await session.commit()

    # ==================================================================
    # IMAGE REFRESH (per-carousel / per-slide / fresh-source)
    # ==================================================================

    async def reimage_carousel(self, carousel_id: str) -> CharacterCarousel:
        """Re-run the 3-tier image matcher on every slide of a carousel.

        Uses the existing character image pool. Does NOT add new images to the
        pool; use reimage_carousel_with_fresh_sources for that.
        """
        async with get_session() as session:
            row = await session.get(CharacterCarouselModel, carousel_id)
            if not row:
                raise ValueError(f"Carousel {carousel_id} not found")
            slides = [dict(s) for s in (row.slides or [])]
            character_id = row.character_id

        if not slides:
            raise ValueError(f"Carousel {carousel_id} has no slides")

        # Clear existing assignments so the matcher picks fresh images
        for slide in slides:
            slide.pop("image_url", None)

        await self._assign_slide_images(character_id, slides)

        async with get_session() as session:
            await session.execute(
                update(CharacterCarouselModel)
                .where(CharacterCarouselModel.id == carousel_id)
                .values(slides=slides, updated_at=datetime.now(timezone.utc))
            )
            await session.commit()

        logger.info("carousel_reimaged", carousel_id=carousel_id, slides=len(slides))
        carousel = await self.get_carousel(carousel_id)
        if not carousel:
            raise ValueError(f"Carousel {carousel_id} not found after reimage")
        return carousel

    async def reimage_slide(
        self,
        carousel_id: str,
        slide_index: int,
        query_override: Optional[str] = None,
    ) -> CharacterCarousel:
        """Refresh a single slide's image.

        If query_override is provided, it replaces the slide's image_query
        for this matching pass, letting users steer image choice.
        """
        async with get_session() as session:
            row = await session.get(CharacterCarouselModel, carousel_id)
            if not row:
                raise ValueError(f"Carousel {carousel_id} not found")
            slides = [dict(s) for s in (row.slides or [])]
            character_id = row.character_id

        if slide_index < 0 or slide_index >= len(slides):
            raise ValueError(
                f"Invalid slide_index {slide_index} (carousel has {len(slides)} slides)"
            )

        target = slides[slide_index]
        previous_url = target.get("image_url")
        target.pop("image_url", None)
        if query_override:
            target["image_query"] = query_override

        await self._assign_slide_images(character_id, [target])

        # If the matcher gave us the same image back and no override was set,
        # bias the query toward the slide text to force a fresh match.
        if target.get("image_url") == previous_url and not query_override:
            char = await self.get_character(character_id)
            if char:
                snippet = str(target.get("text", ""))[:60]
                target["image_query"] = f"{char.name} {snippet}".strip()
                target.pop("image_url", None)
                await self._assign_slide_images(character_id, [target])

        slides[slide_index] = target

        async with get_session() as session:
            await session.execute(
                update(CharacterCarouselModel)
                .where(CharacterCarouselModel.id == carousel_id)
                .values(slides=slides, updated_at=datetime.now(timezone.utc))
            )
            await session.commit()

        logger.info(
            "slide_reimaged",
            carousel_id=carousel_id,
            slide_index=slide_index,
            changed=target.get("image_url") != previous_url,
        )
        carousel = await self.get_carousel(carousel_id)
        if not carousel:
            raise ValueError(f"Carousel {carousel_id} not found after slide reimage")
        return carousel

    async def reimage_carousel_with_fresh_sources(
        self, carousel_id: str
    ) -> CharacterCarousel:
        """Expand the character image pool from fresh sources, then reimage.

        Runs source_images_on_demand first (adds new images via SearXNG and
        configured image APIs), then re-matches every slide.
        """
        async with get_session() as session:
            row = await session.get(CharacterCarouselModel, carousel_id)
            if not row:
                raise ValueError(f"Carousel {carousel_id} not found")
            character_id = row.character_id

        await self.source_images_on_demand(character_id)
        return await self.reimage_carousel(carousel_id)

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

        _rv_variant, _rv_template, _rv_system = await _select_prompt_variant(
            "character_content_review",
            default_template=AI_REVIEW_PROMPT,
            default_system=AI_REVIEW_SYSTEM_PROMPT,
        )
        _rv_vars = {
            "name": char_name,
            "universe": char_universe,
            "angle": row.angle,
            "hook_text": row.hook_text or "",
            "slides_text": slides_text,
            "caption": row.caption or "",
            "hashtags": ", ".join(row.hashtags or []),
        }
        try:
            prompt = _rv_template.format(**_rv_vars)
        except (KeyError, ValueError, IndexError):
            prompt = AI_REVIEW_PROMPT.format(**_rv_vars)

        _rv_raw = None
        _rv_t_start = time.monotonic()
        _rv_success = True
        _rv_error_type = None
        _rv_error_message = None
        try:
            async with _OLLAMA_SEMAPHORE:
                _rv_raw = await self._ollama.chat(
                    prompt=prompt,
                    system=_rv_system,
                    task_type="character_research",
                    temperature=0.3,
                    num_predict=2048,
                    timeout=300,
                    max_retries=1,
                )
        except (TimeoutError, ConnectionError, ValueError) as e:
            _rv_success = False
            _rv_error_type = type(e).__name__
            _rv_error_message = str(e)
        finally:
            await _record_prompt_run_safe(
                variant_id=_rv_variant.id if _rv_variant else None,
                task_type="character_content_review",
                source="character_content",
                source_id=carousel_id,
                provider="ollama",
                system_prompt=_rv_system,
                user_prompt=prompt,
                rendered_variables={"name": char_name, "universe": char_universe, "angle": row.angle},
                response_text=_rv_raw if isinstance(_rv_raw, str) else None,
                success=_rv_success,
                error_type=_rv_error_type,
                error_message=_rv_error_message,
                latency_ms=(time.monotonic() - _rv_t_start) * 1000,
                context={"carousel_id": carousel_id, "character_id": row.character_id},
            )

        try:
            if not _rv_success or _rv_raw is None:
                raise ValueError(_rv_error_message or "ai_review_failed")
            review = parse_json_response(_rv_raw, f"review_{carousel_id}")
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
                        row.hook_text = sanitize_text(rewrite_hook)
                    if rewrite_caption:
                        row.caption = sanitize_text(rewrite_caption)
                    row.ai_review = review
                    row.status = "pending_review"  # Still send to human after rewrite
                    await session.commit()
                    await session.refresh(row)
                    return carousel_to_pydantic(row, char_name)

        async with get_session() as session:
            row = await session.get(CharacterCarouselModel, carousel_id)
            row.ai_review = review
            row.status = new_status
            await session.commit()
            await session.refresh(row)

        # Stage 2: Minimax final polish (only if Stage 1 passed the bar)
        if overall >= 7:
            try:
                await self._final_review_carousel(carousel_id, review)
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, AttributeError, RuntimeError, TypeError, SQLAlchemyError) as exc:
                # Final review failures must never block Stage 1 result
                logger.warning(
                    "final_review_skipped",
                    carousel_id=carousel_id,
                    error=str(exc),
                )

        async with get_session() as session:
            row = await session.get(CharacterCarouselModel, carousel_id)
            return carousel_to_pydantic(row, char_name)

    async def _final_review_carousel(
        self,
        carousel_id: str,
        stage1_review: Dict[str, Any],
    ) -> None:
        """Stage 2: route carousel through Minimax (with Kimi fallback) for viral polish.

        Writes `final_review`, `final_review_score`, `final_review_model` columns.
        Does not change `status` or `ai_review`.
        """
        from app.infrastructure.unified_llm_client import get_unified_llm_client

        async with get_session() as session:
            row = await session.get(CharacterCarouselModel, carousel_id)
            if not row:
                return
            char = await session.get(CharacterModel, row.character_id)
            char_name = char.name if char else "Unknown"
            char_universe = char.universe if char else "unknown"
            slides = row.slides or []
            angle = row.angle
            hook_text = row.hook_text or ""
            caption = row.caption or ""
            hashtags = list(row.hashtags or [])

        slides_text = "\n".join(
            f"Slide {s.get('slide_num', i+1)}: {s.get('text', '')}"
            for i, s in enumerate(slides)
        )

        stage1_scores = json.dumps({
            k: stage1_review.get(k)
            for k in ("hook_strength", "fact_quality", "engagement_potential", "caption_quality", "overall_score")
        })

        _fr_variant, _fr_template, _fr_system = await _select_prompt_variant(
            "character_content_review_final",
            default_template=FINAL_REVIEW_PROMPT,
            default_system=FINAL_REVIEW_SYSTEM_PROMPT,
        )
        _fr_vars = {
            "name": char_name,
            "universe": char_universe,
            "angle": angle,
            "hook_text": hook_text,
            "slides_text": slides_text,
            "caption": caption,
            "hashtags": ", ".join(hashtags),
            "stage1_scores": stage1_scores,
        }
        try:
            prompt = _fr_template.format(**_fr_vars)
        except (KeyError, ValueError, IndexError):
            prompt = FINAL_REVIEW_PROMPT.format(**_fr_vars)

        client = get_unified_llm_client()
        model_used = "unknown"
        _fr_provider = "unknown"
        _fr_model_name = "unknown"
        try:
            from app.infrastructure.llm_router import get_llm_router
            _fr_provider, _fr_model_name, _ = get_llm_router().resolve_provider_model(
                "character_content_review_final"
            )
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, AttributeError, RuntimeError, TypeError, SQLAlchemyError):
            _fr_provider = "minimax"
            _fr_model_name = "unknown"

        _fr_raw = None
        _fr_t_start = time.monotonic()
        _fr_success = True
        _fr_error_type = None
        _fr_error_message = None
        parsed = None
        try:
            # Use structured_chat so the router handles provider fallback from Minimax -> Kimi -> Ollama
            _fr_raw = await client.chat(
                prompt=prompt,
                system=_fr_system,
                task_type="character_content_review_final",
                temperature=0.3,
                max_tokens=2048,
            )
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, AttributeError, RuntimeError, TypeError, SQLAlchemyError) as exc:
            _fr_success = False
            _fr_error_type = type(exc).__name__
            _fr_error_message = str(exc)
        finally:
            await _record_prompt_run_safe(
                variant_id=_fr_variant.id if _fr_variant else None,
                task_type="character_content_review_final",
                source="character_content",
                source_id=carousel_id,
                provider=_fr_provider,
                model=_fr_model_name,
                system_prompt=_fr_system,
                user_prompt=prompt,
                rendered_variables={"name": char_name, "universe": char_universe, "angle": angle},
                response_text=_fr_raw if isinstance(_fr_raw, str) else None,
                success=_fr_success,
                error_type=_fr_error_type,
                error_message=_fr_error_message,
                latency_ms=(time.monotonic() - _fr_t_start) * 1000,
                context={"carousel_id": carousel_id, "stage1_overall": stage1_review.get("overall_score")},
            )

        if not _fr_success or _fr_raw is None:
            logger.warning(
                "final_review_failed",
                carousel_id=carousel_id,
                error=_fr_error_message,
            )
            return

        try:
            parsed = parse_json_response(_fr_raw, f"final_review_{carousel_id}")
            if not isinstance(parsed, dict) or "overall_score" not in parsed:
                raise ValueError("Invalid final review JSON")
            model_used = f"{_fr_provider}/{_fr_model_name}"
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, AttributeError, RuntimeError, TypeError, SQLAlchemyError) as exc:
            logger.warning(
                "final_review_parse_failed",
                carousel_id=carousel_id,
                error=str(exc),
            )
            return

        final_score = float(parsed.get("overall_score", 0) or 0)

        # Phase 024: Optional MiniMax escalation for high-scoring priority-tier carousels.
        rounds = [{"model": model_used, "provider": _fr_provider, "parsed": parsed, "score": final_score}]
        escalated = False
        if await self._should_escalate_to_minimax(char, parsed):
            esc_parsed = await self._run_minimax_escalation(
                carousel_id=carousel_id,
                prompt=prompt,
                system=_fr_system,
                stage2_parsed=parsed,
            )
            if esc_parsed:
                esc_score = float(esc_parsed.get("overall_score", 0) or 0)
                parsed = esc_parsed
                final_score = esc_score
                model_used = get_llm_router().resolve("character_content_review_escalated")
                escalated = True
                rounds.append({"model": model_used, "provider": "minimax", "parsed": esc_parsed, "score": esc_score})

        final_hook = sanitize_text(parsed.get("final_hook")) if parsed.get("final_hook") else None
        final_caption = sanitize_text(parsed.get("final_caption")) if parsed.get("final_caption") else None

        async with get_session() as session:
            row = await session.get(CharacterCarouselModel, carousel_id)
            if not row:
                return
            final_payload = dict(parsed)
            final_payload["rounds"] = rounds
            final_payload["escalated"] = escalated
            row.final_review = final_payload
            row.final_review_score = final_score
            row.final_review_model = model_used
            # Only apply hook/caption polish when Stage 2 explicitly suggested a rewrite and Stage 1 did not already rewrite.
            # Do not silently overwrite human edits. Store suggestions in final_review for review-queue display.
            if final_hook and not row.hook_text:
                row.hook_text = final_hook
            if final_caption and not row.caption:
                row.caption = final_caption
            await session.commit()

        logger.info(
            "final_review_completed",
            carousel_id=carousel_id,
            model=model_used,
            final_score=final_score,
            escalated=escalated,
            verdict=parsed.get("verdict"),
        )

        # Close the template feedback loop: update story_templates.avg_score
        # with a running average of final_review_score. Previously all templates
        # stayed at avg_score=0.0 forever because no code ever wrote this field.
        await self._update_template_score(carousel_id, final_score)

    async def _update_template_score(self, carousel_id: str, new_score: float) -> None:
        """Update StoryTemplate.avg_score with a running average from Stage 2 score.

        Uses: new_avg = (old_avg * times_used + new_score) / (times_used + 1)
        """
        if new_score <= 0:
            return
        try:
            async with get_session() as session:
                row = await session.get(CharacterCarouselModel, carousel_id)
                if not row or not row.story_template:
                    return
                result = await session.execute(
                    select(StoryTemplateModel).where(
                        StoryTemplateModel.template_type == row.story_template
                    )
                )
                template = result.scalar_one_or_none()
                if not template:
                    return
                prev_uses = int(template.times_used or 0)
                prev_avg = float(template.avg_score or 0.0)
                new_uses = prev_uses + 1
                new_avg = (prev_avg * prev_uses + new_score) / new_uses
                template.times_used = new_uses
                template.avg_score = round(new_avg, 3)
                await session.commit()
                logger.info(
                    "template_score_updated",
                    template_type=row.story_template,
                    carousel_id=carousel_id,
                    prev_avg=prev_avg,
                    new_avg=template.avg_score,
                    times_used=new_uses,
                )
        except (SQLAlchemyError, ValueError, KeyError) as exc:
            logger.warning(
                "template_score_update_failed",
                carousel_id=carousel_id,
                error=str(exc),
                error_type=type(exc).__name__,
            )

    async def _should_escalate_to_minimax(
        self,
        character: Optional[CharacterModel],
        stage2_parsed: Dict[str, Any],
    ) -> bool:
        """Return True iff this carousel warrants paying for MiniMax Stage 3.

        Criteria:
          - Feature flag `character_autopilot_enabled` on
          - Stage 2 overall_score >= character_minimax_min_stage2_score (default 80)
          - Character priority_tier in {"priority", "probation"}
          - Today's MiniMax spend below character_minimax_daily_cap_usd
        """
        from app.infrastructure.config import get_settings
        from app.infrastructure.llm_router import get_llm_router

        settings = get_settings()
        if not getattr(settings, "character_autopilot_enabled", True):
            return False

        try:
            stage2_score = float(stage2_parsed.get("overall_score", 0) or 0)
        except (TypeError, ValueError):
            return False
        if stage2_score < float(getattr(settings, "character_minimax_min_stage2_score", 80.0)):
            return False

        tier = getattr(character, "priority_tier", "standard") if character else "standard"
        if tier not in ("priority", "probation"):
            return False

        cap = float(getattr(settings, "character_minimax_daily_cap_usd", 2.0))
        try:
            if await get_llm_router().is_budget_exceeded("minimax", cap):
                logger.info(
                    "minimax_escalation_skipped_budget",
                    cap_usd=cap,
                    spent_usd=await get_llm_router().get_daily_spend("minimax"),
                )
                return False
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, AttributeError, RuntimeError, TypeError, SQLAlchemyError):
            # If budget tracking fails, err on the side of not spending
            return False

        return True

    async def _run_minimax_escalation(
        self,
        carousel_id: str,
        prompt: str,
        system: str,
        stage2_parsed: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Call MiniMax via the character_content_review_escalated task and return parsed JSON."""
        from app.infrastructure.unified_llm_client import get_unified_llm_client

        client = get_unified_llm_client()
        try:
            raw = await client.chat(
                prompt=prompt,
                system=system,
                task_type="character_content_review_escalated",
                temperature=0.3,
                max_tokens=2048,
            )
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, AttributeError, RuntimeError, TypeError, SQLAlchemyError) as exc:
            logger.warning("minimax_escalation_failed", carousel_id=carousel_id, error=str(exc))
            return None

        try:
            parsed = parse_json_response(raw, f"escalation_{carousel_id}")
            if not isinstance(parsed, dict) or "overall_score" not in parsed:
                raise ValueError("Invalid escalation JSON")
            return parsed
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, AttributeError, RuntimeError, TypeError, SQLAlchemyError) as exc:
            logger.warning("minimax_escalation_parse_failed", carousel_id=carousel_id, error=str(exc))
            return None

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
                carousels.append(carousel_to_pydantic(row, char_name))
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

            # Record outcome for brain learning
            await self._record_carousel_outcome(
                row, char_name, approved=True,
                ai_score=row.ai_review.get("overall_score") if row.ai_review else None,
            )

            return carousel_to_pydantic(row, char_name)

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

            # Record outcome for brain learning
            await self._record_carousel_outcome(
                row, char_name, approved=False,
                ai_score=row.ai_review.get("overall_score") if row.ai_review else None,
            )

            return carousel_to_pydantic(row, char_name)

    async def _record_carousel_outcome(
        self, carousel, char_name: Optional[str], approved: bool,
        ai_score: Optional[float] = None,
    ) -> None:
        """Record carousel approval/rejection as brain outcome for learning."""
        try:
            from app.services.zero_brain_service import get_zero_brain_service
            brain = get_zero_brain_service()
            slides = carousel.slides or []
            await brain.record_interaction_outcome(
                domain="character_content",
                action_type="carousel_approved" if approved else "carousel_rejected",
                action_id=carousel.id,
                strategy_used=carousel.angle or "unknown",
                predicted_score=ai_score,
                actual_score=100.0 if approved else 0.0,
                metrics={
                    "character": char_name,
                    "angle": carousel.angle,
                    "slide_count": len(slides),
                    "image_count": sum(1 for s in slides if s.get("image_url")),
                    "template": getattr(carousel, "story_template", None),
                },
                text_for_memory=(
                    f"{'Approved' if approved else 'Rejected'} carousel for {char_name}: "
                    f"angle={carousel.angle}, hook={carousel.hook_text}"
                ),
            )
        except (ValueError, KeyError, TypeError, ImportError, AttributeError) as e:
            logger.debug("brain_outcome_recording_failed", error=str(e))

        # Propagate outcome to every prompt run that contributed to this carousel
        try:
            from app.services.prompt_evolution_service import get_prompt_evolution_service
            pe_svc = get_prompt_evolution_service()
            # Approved = strong positive, rejected = strong negative
            outcome_score = 80.0 if approved else 15.0
            updated = await pe_svc.record_outcome_by_source(
                source="character_content",
                source_id=carousel.id,
                outcome_score=outcome_score,
            )
            if updated:
                logger.info(
                    "prompt_runs_outcome_recorded",
                    carousel_id=carousel.id,
                    approved=approved,
                    runs_updated=updated,
                )
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, AttributeError, RuntimeError, TypeError, SQLAlchemyError) as e:
            logger.debug("prompt_run_outcome_propagation_failed", error=str(e))

    async def approve_image(self, character_id: str, image_id: str) -> CharacterImage:
        """Mark an image as approved (good quality)."""
        async with get_session() as session:
            row = await session.get(CharacterImageModel, image_id)
            if not row or row.character_id != character_id:
                raise ValueError(f"Image {image_id} not found for character {character_id}")
            row.is_approved = True
            row.feedback_reason = None
            await session.commit()
            await session.refresh(row)
            return image_to_pydantic(row)

    async def reject_image(self, character_id: str, image_id: str, reason: str = "") -> CharacterImage:
        """Mark an image as rejected (bad quality). Sets is_valid=False to exclude from future use."""
        async with get_session() as session:
            row = await session.get(CharacterImageModel, image_id)
            if not row or row.character_id != character_id:
                raise ValueError(f"Image {image_id} not found for character {character_id}")
            row.is_approved = False
            row.is_valid = False
            row.feedback_reason = reason or "Rejected by user"
            await session.commit()
            await session.refresh(row)
            return image_to_pydantic(row)

    async def delete_image(self, character_id: str, image_id: str) -> Dict[str, Any]:
        """Delete an image and add its URL to the character's blocklist to prevent re-import."""
        async with get_session() as session:
            img_row = await session.get(CharacterImageModel, image_id)
            if not img_row or img_row.character_id != character_id:
                raise ValueError(f"Image {image_id} not found for character {character_id}")
            blocked_url = img_row.url
            await session.delete(img_row)
            await session.commit()

        # Add URL to blocklist and remove from image_urls list
        async with get_session() as session:
            char_row = await session.get(CharacterModel, character_id)
            if char_row:
                blocked = list(char_row.blocked_image_urls or [])
                if blocked_url not in blocked:
                    blocked.append(blocked_url)
                char_row.blocked_image_urls = blocked

                urls = list(char_row.image_urls or [])
                if blocked_url in urls:
                    urls.remove(blocked_url)
                    char_row.image_urls = urls

                # Reassign primary if needed
                if char_row.image_url == blocked_url:
                    char_row.image_url = urls[0] if urls else None

                await session.commit()

        logger.info("image_deleted", character_id=character_id, image_id=image_id, blocked_url=blocked_url)
        return {"deleted": True, "blocked_url": blocked_url}

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
                carousels.append(carousel_to_pydantic(row, char_name))
            return carousels

    async def get_carousel(self, carousel_id: str) -> Optional[CharacterCarousel]:
        async with get_session() as session:
            row = await session.get(CharacterCarouselModel, carousel_id)
            if not row:
                return None
            char = await session.get(CharacterModel, row.character_id)
            char_name = char.name if char else None
            return carousel_to_pydantic(row, char_name)

    async def update_carousel(
        self,
        carousel_id: str,
        data: CarouselUpdate,
        *,
        created_by: str = "user",
        snapshot_source: str = "manual_edit",
        source_metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[CharacterCarousel]:
        async with get_session() as session:
            row = await session.get(CharacterCarouselModel, carousel_id)
            if not row:
                return None
            updates = data.model_dump(exclude_unset=True)

            # Snapshot BEFORE mutating if any content field changes.
            content_fields = {
                "hook_text", "slides", "caption", "hashtags",
                "title", "human_notes", "music_track", "text_overlay_specs",
            }
            changed_content = content_fields.intersection(updates.keys())
            if changed_content:
                meta = {"fields": sorted(changed_content)}
                if source_metadata:
                    meta.update(source_metadata)
                await self._snapshot_carousel(
                    session, row,
                    source=snapshot_source,
                    source_metadata=meta,
                    created_by=created_by,
                )

            for key, val in updates.items():
                setattr(row, key, val)
            await session.commit()
            await session.refresh(row)
            char = await session.get(CharacterModel, row.character_id)
            char_name = char.name if char else None
            return carousel_to_pydantic(row, char_name)

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

    async def bulk_reimage_carousels(
        self, status: Optional[str] = "draft", limit: int = 20,
    ) -> Dict[str, Any]:
        """Re-source images for existing carousels using the improved pipeline."""
        async with get_session() as session:
            query = select(CharacterCarouselModel)
            if status:
                query = query.where(CharacterCarouselModel.status == status)
            query = query.order_by(CharacterCarouselModel.created_at.desc()).limit(limit)
            result = await session.execute(query)
            carousels = result.scalars().all()

        updated = 0
        errors = 0
        for carousel in carousels:
            try:
                char_id = carousel.character_id
                # Check if character has enough valid images
                async with get_session() as session:
                    count_result = await session.execute(
                        select(sql_func.count(CharacterImageModel.id))
                        .where(CharacterImageModel.character_id == char_id)
                        .where(CharacterImageModel.is_valid == True)
                    )
                    img_count = count_result.scalar() or 0

                # Re-source if too few
                if img_count < 6:
                    await self.source_images_on_demand(char_id)

                # Re-assign images using smart matching
                slides = list(carousel.slides or [])
                await self._assign_slide_images(char_id, slides)

                async with get_session() as session:
                    row = await session.get(CharacterCarouselModel, carousel.id)
                    if row:
                        row.slides = slides
                        await session.commit()
                updated += 1
            except (ValueError, OSError, TypeError) as e:
                logger.warning("bulk_reimage_failed", carousel_id=carousel.id, error=str(e))
                errors += 1

        logger.info("bulk_reimage_complete", updated=updated, errors=errors)
        return {"updated": updated, "errors": errors, "total": len(carousels)}

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
            return character_to_pydantic(row)

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
            return character_to_pydantic(row)

    # ==================================================================
    # RESEARCH QUEUE (async with progress tracking)
    # ==================================================================

    # Steps that use the LLM. Used to tag model in step stats.
    _LLM_STEPS = {"synthesis", "fact_extraction"}

    async def _record_step_stat(
        self,
        *,
        character_id: str,
        job_id: str,
        step_name: str,
        started_at_iso: Optional[str],
        completed_at_iso: Optional[str],
        status: str,
    ) -> None:
        """Persist a single step's duration to character_research_step_stats.

        Silent on error: pipeline must not block on observability writes.
        """
        try:
            if not started_at_iso or not completed_at_iso:
                return
            try:
                started = datetime.fromisoformat(started_at_iso.replace("Z", "+00:00"))
                completed = datetime.fromisoformat(completed_at_iso.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                return
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            if completed.tzinfo is None:
                completed = completed.replace(tzinfo=timezone.utc)
            duration_ms = int((completed - started).total_seconds() * 1000)
            if duration_ms < 0:
                duration_ms = 0
            model = get_llm_router().resolve("character_research") if step_name in self._LLM_STEPS else None
            async with get_session() as session:
                row = CharacterResearchStepStatModel(
                    character_id=character_id,
                    job_id=job_id,
                    step_name=step_name,
                    started_at=started,
                    completed_at=completed,
                    duration_ms=duration_ms,
                    status=status,
                    model=model,
                )
                session.add(row)
                await session.commit()
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, AttributeError, RuntimeError, TypeError, SQLAlchemyError) as e:
            logger.debug("record_step_stat_failed",
                         step=step_name, character_id=character_id, error=str(e))

    async def get_step_duration_averages(self) -> Dict[str, Dict[str, int]]:
        """Return rolling stats per step. Cached 60s.

        Returns dict keyed by step_name with values {avg_ms, p50_ms, p95_ms, n}.
        Falls back to _STEP_DURATION_PRIORS_MS when n < 3 for a step.
        """
        global _step_stats_cache

        now = time.monotonic()
        if _step_stats_cache["data"] is not None and _step_stats_cache["expires_at"] > now:
            return _step_stats_cache["data"]

        # Seed every known step with priors; overwrite where DB has >= 3 samples.
        result: Dict[str, Dict[str, int]] = {
            name: {
                "avg_ms": prior_ms,
                "p50_ms": prior_ms,
                "p95_ms": int(prior_ms * 1.5),
                "n": 0,
            }
            for name, prior_ms in _STEP_DURATION_PRIORS_MS.items()
        }

        try:
            async with get_session() as session:
                # Pull most recent 200 successful rows per step.
                # Simpler path: fetch last 1400 completed rows total (7 steps * 200),
                # aggregate in Python. Cheap for this volume.
                stmt = (
                    select(
                        CharacterResearchStepStatModel.step_name,
                        CharacterResearchStepStatModel.duration_ms,
                    )
                    .where(CharacterResearchStepStatModel.status == "completed")
                    .order_by(CharacterResearchStepStatModel.created_at.desc())
                    .limit(1400)
                )
                rows = await session.execute(stmt)
                by_step: Dict[str, List[int]] = {}
                for step_name, duration_ms in rows.all():
                    if duration_ms is None:
                        continue
                    bucket = by_step.setdefault(step_name, [])
                    if len(bucket) < 200:
                        bucket.append(int(duration_ms))

                for step_name, durations in by_step.items():
                    if not durations:
                        continue
                    n = len(durations)
                    if n < 3:
                        # Not enough samples; keep prior but record observed count.
                        if step_name in result:
                            result[step_name]["n"] = n
                        continue
                    sorted_d = sorted(durations)
                    avg = sum(sorted_d) // n
                    p50 = sorted_d[n // 2]
                    p95_idx = min(n - 1, int(n * 0.95))
                    p95 = sorted_d[p95_idx]
                    result[step_name] = {
                        "avg_ms": int(avg),
                        "p50_ms": int(p50),
                        "p95_ms": int(p95),
                        "n": n,
                    }
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, AttributeError, RuntimeError, TypeError, SQLAlchemyError) as e:
            logger.debug("step_duration_averages_failed", error=str(e))

        _step_stats_cache["data"] = result
        _step_stats_cache["expires_at"] = now + _STEP_STATS_TTL_SEC
        return result

    def _eta_for_job(
        self,
        job: ResearchJob,
        averages: Dict[str, Dict[str, int]],
        *,
        now_utc: Optional[datetime] = None,
    ) -> Optional[int]:
        """Compute ETA seconds for a single job based on step averages.

        Rules:
        - queued: sum(avg_ms for all 7 steps) / 1000
        - researching: for pending steps use avg; for running step use
          max(0, avg - elapsed_so_far); completed/failed steps contribute 0.
        - completed/failed: None
        """
        try:
            if job.status in (ResearchJobStatus.COMPLETED, ResearchJobStatus.FAILED):
                return None

            total_ms = 0
            now = now_utc or datetime.now(timezone.utc)

            for step in job.steps:
                avg_ms = averages.get(step.name, {}).get("avg_ms") or \
                         _STEP_DURATION_PRIORS_MS.get(step.name, 60_000)
                status = step.status
                if status == "completed" or status == "failed":
                    continue
                if status == "running" and step.started_at:
                    try:
                        started = step.started_at
                        if isinstance(started, str):
                            started = datetime.fromisoformat(started.replace("Z", "+00:00"))
                        if started.tzinfo is None:
                            started = started.replace(tzinfo=timezone.utc)
                        elapsed_ms = int((now - started).total_seconds() * 1000)
                        remaining = max(0, avg_ms - elapsed_ms)
                        total_ms += remaining
                    except (ValueError, TypeError, AttributeError):
                        total_ms += avg_ms
                else:
                    total_ms += avg_ms

            return max(1, total_ms // 1000)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, AttributeError, RuntimeError, TypeError, SQLAlchemyError) as e:
            logger.debug("eta_for_job_failed", job_id=getattr(job, "id", "?"), error=str(e))
            return None

    def _annotate_jobs_with_eta(
        self,
        jobs: List[ResearchJob],
        averages: Dict[str, Dict[str, int]],
    ) -> None:
        """Mutate jobs to add eta_seconds and per-step avg_duration_ms."""
        now = datetime.now(timezone.utc)
        for job in jobs:
            for step in job.steps:
                avg_ms = averages.get(step.name, {}).get("avg_ms")
                if avg_ms is None:
                    avg_ms = _STEP_DURATION_PRIORS_MS.get(step.name)
                if avg_ms is not None:
                    step.avg_duration_ms = int(avg_ms)
            job.eta_seconds = self._eta_for_job(job, averages, now_utc=now)

    def _estimated_queue_completion(
        self,
        jobs: List[ResearchJob],
        averages: Dict[str, Dict[str, int]],
    ) -> Optional[str]:
        """Compute wall-clock ETA for the full queue given BATCH_SIZE parallelism.

        Returns an ISO 8601 timestamp string to match ResearchQueueStatus schema.
        """
        try:
            active = [j for j in jobs if j.status in (
                ResearchJobStatus.QUEUED, ResearchJobStatus.RESEARCHING
            )]
            if not active:
                return None
            # Average full-job duration in seconds (sum of per-step avg).
            job_avg_ms = sum(
                averages.get(s, {}).get("avg_ms", _STEP_DURATION_PRIORS_MS.get(s, 60_000))
                for s in _STEP_DURATION_PRIORS_MS.keys()
            )
            job_avg_sec = max(1, job_avg_ms // 1000)
            # We process BATCH_SIZE in parallel. Running job's remaining time
            # is captured in its eta_seconds; assume the longest remaining
            # running ETA dominates the current batch.
            running = [j for j in active if j.status == ResearchJobStatus.RESEARCHING]
            queued = [j for j in active if j.status == ResearchJobStatus.QUEUED]
            batch_size = 3
            # Time to finish the batch currently running.
            current_batch_remaining = max(
                (j.eta_seconds or job_avg_sec for j in running),
                default=0,
            )
            # Remaining queued characters after current batch.
            # running count fills part of the batch; queue absorbs the rest.
            capacity_after_current = max(0, batch_size - len(running))
            queued_after_current = max(0, len(queued) - capacity_after_current)
            future_batches = -(-queued_after_current // batch_size)  # ceil
            total_seconds = current_batch_remaining + future_batches * job_avg_sec
            if total_seconds <= 0:
                return None
            from datetime import timedelta
            eta_dt = datetime.now(timezone.utc) + timedelta(seconds=int(total_seconds))
            return eta_dt.isoformat()
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, AttributeError, RuntimeError, TypeError, SQLAlchemyError) as e:
            logger.debug("estimated_completion_failed", error=str(e))
            return None

    async def get_research_queue_status(self) -> ResearchQueueStatus:
        """Return research queue status. Merges in-memory live jobs with DB state."""
        global _research_queue

        averages = await self.get_step_duration_averages()

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

            # Annotate with ETA + per-step averages.
            self._annotate_jobs_with_eta(jobs_list, averages)

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
                estimated_completion=self._estimated_queue_completion(jobs_list, averages),
            )

        # No live queue — rebuild status from database
        jobs_list = await self._get_db_jobs()
        self._annotate_jobs_with_eta(jobs_list, averages)

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
            estimated_completion=self._estimated_queue_completion(jobs_list, averages),
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

        # Get candidates: pending + failed + needs_retry (0-fact completed)
        chars = await self.list_characters(
            universe=universe, research_status="pending", limit=limit,
        )
        failed = await self.list_characters(
            universe=universe, research_status="failed", limit=limit,
        )
        chars.extend(failed)
        needs_retry = await self.list_characters(
            universe=universe, research_status="needs_retry", limit=limit,
        )
        chars.extend(needs_retry)
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
        """Process the research queue in parallel batches.

        Multiple characters run concurrently through the cheap I/O steps
        (searxng, wiki, deep_research, image_sourcing). Heavy LLM steps
        (synthesis, fact_extraction) are serialized via _OLLAMA_SEMAPHORE
        so we don't thrash the GPU.
        """
        global _research_queue
        BATCH_SIZE = 3  # Parallelize cheap steps; Ollama serialized by semaphore
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
                    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, AttributeError, RuntimeError, TypeError, SQLAlchemyError) as e:  # Catch all to prevent queue from dying on unexpected errors
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
        def _update_step(step_name: str, status: str, result_summary: str = None, error: str = None, links_found: list = None):
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
                    if links_found:
                        step["links_found"] = links_found
                    # Persist stats for completed/failed steps (fire-and-forget).
                    if status in ("completed", "failed"):
                        try:
                            asyncio.create_task(self._record_step_stat(
                                character_id=character_id,
                                job_id=job_id,
                                step_name=step_name,
                                started_at_iso=step.get("started_at"),
                                completed_at_iso=step.get("completed_at"),
                                status=status,
                            ))
                        except RuntimeError:
                            # No running event loop; ignore.
                            pass
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

        # Steps 1-3 run in parallel. Each has no dependency on the others
        # (SearXNG, Wikipedia REST, and deep sources are all independent).
        async def _do_searxng():
            _update_step("searxng_search", "running")
            try:
                results = await self._search_character(name, universe, franchise)
                seen_urls = set()
                search_links = []
                for r in results:
                    url = r.get("url", "")
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        search_links.append({"url": url, "title": r.get("title", ""), "source": "searxng"})
                _update_step("searxng_search", "completed",
                             result_summary=f"{len(results)} results from web search",
                             links_found=search_links[:20])
                return results
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, ConnectionError) as e:
                _update_step("searxng_search", "failed", error=str(e))
                return []

        async def _do_wiki():
            _update_step("wiki_scrape", "running")
            try:
                data = await self._scrape_wikis(name, universe)
                wiki_links = [
                    {"url": url.replace("#full", ""), "title": f"Wikipedia: {name}", "source": "wikipedia"}
                    for url in data.keys() if not url.endswith("#full")
                ]
                _update_step("wiki_scrape", "completed",
                             result_summary=f"{len(data)} wiki pages scraped",
                             links_found=wiki_links)
                return data
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, ConnectionError) as e:
                _update_step("wiki_scrape", "failed", error=str(e))
                return {}

        async def _do_deep():
            _update_step("deep_research", "running")
            try:
                sources_svc = get_research_sources()
                fragments = await sources_svc.research_from_all_sources(name, universe, franchise)
                seen_deep = set()
                deep_links = []
                for frag in fragments:
                    url = getattr(frag, "url", "") or ""
                    if url and url not in seen_deep:
                        seen_deep.add(url)
                        deep_links.append({"url": url, "title": getattr(frag, "fragment_type", ""), "source": frag.source})
                _update_step("deep_research", "completed",
                             result_summary=f"{len(fragments)} fragments from deep sources",
                             links_found=deep_links[:30])
                return fragments
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, ConnectionError) as e:
                _update_step("deep_research", "failed", error=str(e))
                return []

        search_results, wiki_data, deep_fragments = await asyncio.gather(
            _do_searxng(), _do_wiki(), _do_deep()
        )

        # Store fragments in DB
        if deep_fragments:
            try:
                async with get_session() as session:
                    for frag in deep_fragments[:50]:
                        session.add(CharacterResearchFragmentModel(
                            id=generate_id("rf"),
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

        # Step 4: LLM synthesis (check DB for existing data to survive restarts)
        research_data = None
        async with get_session() as session:
            existing = await session.get(CharacterModel, character_id)
            if existing and isinstance(existing.research_data, dict) and existing.research_data.get("bio") and not existing.research_data.get("error"):
                research_data = existing.research_data
                logger.info("synthesis_skipped_existing_data", name=name, fields=len(research_data))
                _update_step("synthesis", "completed", result_summary=f"Reused existing {len(research_data)} fields")

        if research_data is None:
            _update_step("synthesis", "running")
            try:
                deep_text = "\n\n".join(
                    f"[{f.source}/{f.fragment_type}] {f.content[:1000]}"
                    for f in deep_fragments[:20]
                )
                research_data = await self._synthesize_research(name, universe, search_results, wiki_data, deep_text)
                _update_step("synthesis", "completed",
                             result_summary=f"Synthesized into {len(research_data)} fields")
                # Save intermediate result to DB so it survives container restarts
                try:
                    async with get_session() as session:
                        row = await session.get(CharacterModel, character_id)
                        if row:
                            row.research_data = research_data
                            await session.commit()
                    logger.info("synthesis_intermediate_save", name=name)
                except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, AttributeError, RuntimeError, TypeError, SQLAlchemyError) as e:
                    logger.warning("synthesis_intermediate_save_failed", name=name, error=str(e))
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, AttributeError, RuntimeError, TypeError, SQLAlchemyError) as e:
                _update_step("synthesis", "failed", error=str(e))
                logger.warning("synthesis_failed", name=name, error=str(e), error_type=type(e).__name__)
                research_data = {"bio": f"Research data for {name}", "powers": [], "key_relationships": []}

        # Steps 5 & 6 run in parallel: fact_extraction is an Ollama call
        # (serialized by _OLLAMA_SEMAPHORE), image_sourcing is SearXNG image
        # search. They share no state except synthesis output.

        # Check for existing fact_bank to survive restarts
        existing_fact_bank = None
        async with get_session() as session:
            existing = await session.get(CharacterModel, character_id)
            if existing and existing.fact_bank and len(existing.fact_bank) > 0:
                existing_fact_bank = existing.fact_bank
                logger.info("fact_extraction_skipped_existing_data", name=name, facts=len(existing_fact_bank))
                _update_step("fact_extraction", "completed", result_summary=f"Reused existing {len(existing_fact_bank)} facts")

        async def _do_facts():
            if existing_fact_bank is not None:
                return existing_fact_bank
            _update_step("fact_extraction", "running")
            try:
                fb = await self._extract_facts(name, research_data, search_results, deep_fragments)
                job["facts_found"] = len(fb)
                _update_step("fact_extraction", "completed",
                             result_summary=f"{len(fb)} facts extracted")
                # Save intermediate result to DB so it survives container restarts
                try:
                    async with get_session() as session:
                        row = await session.get(CharacterModel, character_id)
                        if row:
                            row.fact_bank = fb
                            await session.commit()
                    logger.info("fact_extraction_intermediate_save", name=name)
                except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, AttributeError, RuntimeError, TypeError, SQLAlchemyError) as e:
                    logger.warning("fact_extraction_intermediate_save_failed", name=name, error=str(e))
                return fb
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, AttributeError, RuntimeError, TypeError, SQLAlchemyError) as e:
                _update_step("fact_extraction", "failed", error=str(e))
                logger.warning("fact_extraction_failed", name=name, error=str(e), error_type=type(e).__name__)
                return []

        async def _do_images():
            _update_step("image_sourcing", "running")
            try:
                imgs = await self._source_images(character_id, name, universe, franchise)
                job["images_found"] = len(imgs)
                _update_step("image_sourcing", "completed",
                             result_summary=f"{len(imgs)} images sourced")
                return imgs
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, ConnectionError) as e:
                _update_step("image_sourcing", "failed", error=str(e))
                return []

        fact_bank, images = await asyncio.gather(_do_facts(), _do_images())

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

            # Snapshot step history into research_data so result_summary
            # survives container restarts. Enables post-hoc research debugging.
            step_summaries = [
                {
                    "name": s.get("name"),
                    "status": s.get("status"),
                    "result_summary": s.get("result_summary"),
                    "error": s.get("error"),
                    "started_at": s.get("started_at"),
                    "completed_at": s.get("completed_at"),
                    "links_count": len(s.get("links_found") or []),
                }
                for s in steps
            ]
            research_data["steps_history"] = step_summaries
            research_data["last_job_id"] = job_id
            research_data["last_run_at"] = datetime.now(timezone.utc).isoformat()

            final_status = "completed" if len(fact_bank) >= 3 else "needs_retry"
            async with get_session() as session:
                row = await session.get(CharacterModel, character_id)
                if row:
                    row.research_data = research_data
                    row.fact_bank = fact_bank
                    row.research_status = final_status
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
        # Also include failed and needs_retry (0-fact completed) for retry
        failed = await self.list_characters(
            universe=universe,
            research_status="failed",
            limit=limit,
        )
        chars.extend(failed)
        needs_retry = await self.list_characters(
            universe=universe,
            research_status="needs_retry",
            limit=limit,
        )
        chars.extend(needs_retry)

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
    # CHARACTER ENHANCE (Phase 4)
    # ==================================================================

    async def enhance_character(
        self,
        character_id: str,
        refresh_research: bool = True,
        add_images: int = 8,
        regenerate_weak_carousels: bool = True,
        weak_threshold: float = 7.0,
    ) -> Dict[str, Any]:
        """Deep-enhance a character: refresh research, top up images, regenerate weak carousels.

        Returns a structured summary of what changed.
        """
        async with get_session() as session:
            char = await session.get(CharacterModel, character_id)
            if not char:
                raise ValueError(f"Character {character_id} not found")

            facts_before = len(char.fact_bank or [])
            depth_before = float(char.research_depth_score or 0.0)

            img_count_q = await session.execute(
                select(sql_func.count(CharacterImageModel.id)).where(
                    CharacterImageModel.character_id == character_id
                )
            )
            images_before = int(img_count_q.scalar() or 0)

        errors: List[str] = []

        # Step 1: Refresh research (synchronously). Reuses the full pipeline so
        # facts, relationships, and research_depth_score all get recomputed.
        if refresh_research:
            try:
                await self._research_pipeline(character_id)
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, AttributeError, RuntimeError, TypeError, SQLAlchemyError) as exc:
                msg = f"research_pipeline_failed: {exc}"
                logger.warning("enhance_research_failed", character_id=character_id, error=str(exc))
                errors.append(msg)

        # Step 2: Top up images. `source_images_on_demand` is idempotent and
        # preserves approved images.
        if add_images and add_images > 0:
            try:
                await self.source_images_on_demand(character_id)
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, AttributeError, RuntimeError, TypeError, SQLAlchemyError) as exc:
                msg = f"source_images_failed: {exc}"
                logger.warning("enhance_images_failed", character_id=character_id, error=str(exc))
                errors.append(msg)

        # Step 3: Identify and regenerate weak carousels.
        regenerated = 0
        archived = 0
        if regenerate_weak_carousels:
            async with get_session() as session:
                result = await session.execute(
                    select(CharacterCarouselModel).where(
                        CharacterCarouselModel.character_id == character_id,
                        CharacterCarouselModel.status.in_(
                            ["draft", "ai_reviewed", "pending_review", "rejected"]
                        ),
                    )
                )
                weak_rows = []
                for row in result.scalars().all():
                    score = (row.ai_review or {}).get("overall_score") if row.ai_review else None
                    if score is not None and float(score) < weak_threshold:
                        weak_rows.append(row)

            for row in weak_rows:
                try:
                    angle_value = row.angle
                    template = row.story_template
                    create = CarouselCreate(
                        character_id=character_id,
                        angle=ContentAngle(angle_value) if isinstance(angle_value, str) else angle_value,
                        story_template=template,
                    )
                    new_carousel = await self.generate_carousel(create)
                    regenerated += 1

                    # Archive the old one
                    async with get_session() as session:
                        old = await session.get(CharacterCarouselModel, row.id)
                        if old:
                            old.status = "archived"
                            await session.commit()
                    archived += 1

                    # Queue Stage 1 review inline for the new one (Stage 2 auto-chains on score >= 7)
                    try:
                        await self.ai_review_carousel(new_carousel.id)
                    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, AttributeError, RuntimeError, TypeError, SQLAlchemyError) as exc:
                        logger.debug(
                            "enhance_review_deferred",
                            carousel_id=new_carousel.id,
                            error=str(exc),
                        )
                except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, AttributeError, RuntimeError, TypeError, SQLAlchemyError) as exc:
                    msg = f"regenerate_failed:{row.id}: {exc}"
                    logger.warning(
                        "enhance_regenerate_failed",
                        carousel_id=row.id,
                        error=str(exc),
                    )
                    errors.append(msg)

        # Step 4: Collect final numbers
        async with get_session() as session:
            char = await session.get(CharacterModel, character_id)
            facts_after = len(char.fact_bank or []) if char else facts_before
            depth_after = float(char.research_depth_score or 0.0) if char else depth_before

            img_count_q = await session.execute(
                select(sql_func.count(CharacterImageModel.id)).where(
                    CharacterImageModel.character_id == character_id
                )
            )
            images_after = int(img_count_q.scalar() or 0)

        summary = {
            "character_id": character_id,
            "facts_before": facts_before,
            "facts_after": facts_after,
            "facts_added": max(0, facts_after - facts_before),
            "images_before": images_before,
            "images_after": images_after,
            "images_added": max(0, images_after - images_before),
            "carousels_regenerated": regenerated,
            "carousels_archived": archived,
            "research_depth_before": depth_before,
            "research_depth_after": depth_after,
            "research_depth_delta": depth_after - depth_before,
            "errors": errors,
        }
        logger.info("character_enhanced", **summary)
        return summary

    # ==================================================================
    # SEED DATA
    # ==================================================================

    async def seed_characters(self) -> List[Character]:
        """Pre-populate with iconic characters across Marvel, DC, Star Wars,
        LOTR, Harry Potter, Prestige TV, Anime, Gaming, and Film.

        Idempotent: characters already present by name are skipped.
        """
        seed_data = [
            # ============================================================
            # Marvel
            # ============================================================
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
            # ============================================================
            # DC
            # ============================================================
            {"name": "Batman", "universe": "dc", "franchise": "Justice League", "real_name": "Bruce Wayne", "tags": ["dc", "detective", "gotham"]},
            {"name": "Superman", "universe": "dc", "franchise": "Justice League", "real_name": "Clark Kent / Kal-El", "tags": ["dc", "krypton", "godlike"]},
            {"name": "Joker", "universe": "dc", "franchise": "Batman", "real_name": "Unknown", "tags": ["dc", "villain", "gotham"]},
            {"name": "Wonder Woman", "universe": "dc", "franchise": "Justice League", "real_name": "Diana Prince", "tags": ["dc", "amazon", "warrior"]},
            {"name": "Aquaman", "universe": "dc", "franchise": "Justice League", "real_name": "Arthur Curry", "tags": ["dc", "atlantis", "ocean"]},
            {"name": "The Flash", "universe": "dc", "franchise": "Justice League", "real_name": "Barry Allen", "tags": ["dc", "speedforce", "speedster"]},
            {"name": "Harley Quinn", "universe": "dc", "franchise": "Batman", "real_name": "Harleen Quinzel", "tags": ["dc", "villain", "antihero"]},
            {"name": "Green Lantern", "universe": "dc", "franchise": "Justice League", "real_name": "Hal Jordan", "tags": ["dc", "cosmic", "willpower"]},
            # ============================================================
            # Star Wars
            # ============================================================
            {"name": "Darth Vader", "universe": "star_wars", "franchise": "Star Wars", "real_name": "Anakin Skywalker", "tags": ["starwars", "sith", "villain"]},
            {"name": "Yoda", "universe": "star_wars", "franchise": "Star Wars", "real_name": "Yoda", "tags": ["starwars", "jedi", "mentor"]},
            {"name": "Obi-Wan Kenobi", "universe": "star_wars", "franchise": "Star Wars", "real_name": "Obi-Wan Kenobi", "tags": ["starwars", "jedi", "mentor"]},
            {"name": "Luke Skywalker", "universe": "star_wars", "franchise": "Star Wars", "real_name": "Luke Skywalker", "tags": ["starwars", "jedi", "hero"]},
            {"name": "Rey", "universe": "star_wars", "franchise": "Star Wars", "real_name": "Rey Skywalker", "tags": ["starwars", "jedi", "scavenger"]},
            {"name": "Grogu", "universe": "star_wars", "franchise": "Star Wars", "real_name": "Grogu", "tags": ["starwars", "mandalorian", "force"]},
            # ============================================================
            # LOTR
            # ============================================================
            {"name": "Gandalf", "universe": "lotr", "franchise": "Lord of the Rings", "real_name": "Olórin", "tags": ["lotr", "wizard", "tolkien"]},
            {"name": "Aragorn", "universe": "lotr", "franchise": "Lord of the Rings", "real_name": "Aragorn II Elessar", "tags": ["lotr", "king", "ranger"]},
            {"name": "Legolas", "universe": "lotr", "franchise": "Lord of the Rings", "real_name": "Legolas Greenleaf", "tags": ["lotr", "elf", "archer"]},
            {"name": "Frodo", "universe": "lotr", "franchise": "Lord of the Rings", "real_name": "Frodo Baggins", "tags": ["lotr", "hobbit", "ringbearer"]},
            # ============================================================
            # Harry Potter
            # ============================================================
            {"name": "Harry Potter", "universe": "harry_potter", "franchise": "Harry Potter", "real_name": "Harry James Potter", "tags": ["hogwarts", "gryffindor", "chosen"]},
            {"name": "Hermione Granger", "universe": "harry_potter", "franchise": "Harry Potter", "real_name": "Hermione Jean Granger", "tags": ["hogwarts", "gryffindor", "genius"]},
            {"name": "Severus Snape", "universe": "harry_potter", "franchise": "Harry Potter", "real_name": "Severus Snape", "tags": ["hogwarts", "slytherin", "antihero"]},
            {"name": "Voldemort", "universe": "harry_potter", "franchise": "Harry Potter", "real_name": "Tom Marvolo Riddle", "tags": ["hogwarts", "villain", "slytherin"]},
            {"name": "Albus Dumbledore", "universe": "harry_potter", "franchise": "Harry Potter", "real_name": "Albus Percival Wulfric Brian Dumbledore", "tags": ["hogwarts", "mentor", "headmaster"]},
            # ============================================================
            # Prestige TV
            # ============================================================
            {"name": "Walter White", "universe": "tv", "franchise": "Breaking Bad", "real_name": "Walter Hartwell White", "tags": ["breakingbad", "antihero", "drama"]},
            {"name": "Saul Goodman", "universe": "tv", "franchise": "Better Call Saul", "real_name": "Jimmy McGill", "tags": ["breakingbad", "lawyer", "antihero"]},
            {"name": "Tony Soprano", "universe": "tv", "franchise": "The Sopranos", "real_name": "Anthony Soprano", "tags": ["sopranos", "mob", "antihero"]},
            {"name": "Don Draper", "universe": "tv", "franchise": "Mad Men", "real_name": "Dick Whitman", "tags": ["madmen", "ad-exec", "drama"]},
            {"name": "Logan Roy", "universe": "tv", "franchise": "Succession", "real_name": "Logan Roy", "tags": ["succession", "mogul", "patriarch"]},
            {"name": "Tyrion Lannister", "universe": "tv", "franchise": "Game of Thrones", "real_name": "Tyrion Lannister", "tags": ["got", "lannister", "clever"]},
            {"name": "Jon Snow", "universe": "tv", "franchise": "Game of Thrones", "real_name": "Aegon Targaryen", "tags": ["got", "stark", "night-watch"]},
            {"name": "Daenerys Targaryen", "universe": "tv", "franchise": "Game of Thrones", "real_name": "Daenerys Targaryen", "tags": ["got", "targaryen", "dragons"]},
            {"name": "Eleven", "universe": "tv", "franchise": "Stranger Things", "real_name": "Jane Hopper", "tags": ["strangerthings", "psychic", "hawkins"]},
            {"name": "Wednesday Addams", "universe": "tv", "franchise": "Wednesday", "real_name": "Wednesday Addams", "tags": ["addamsfamily", "dark", "teen"]},
            {"name": "Jack Bauer", "universe": "tv", "franchise": "24", "real_name": "Jack Bauer", "tags": ["24", "agent", "action"]},
            {"name": "Michael Scott", "universe": "tv", "franchise": "The Office", "real_name": "Michael Gary Scott", "tags": ["comedy", "theoffice", "boss"]},
            # ============================================================
            # Anime
            # ============================================================
            {"name": "Naruto Uzumaki", "universe": "anime", "franchise": "Naruto", "real_name": "Naruto Uzumaki", "tags": ["naruto", "ninja", "hokage"]},
            {"name": "Goku", "universe": "anime", "franchise": "Dragon Ball", "real_name": "Son Goku", "tags": ["dragonball", "saiyan", "hero"]},
            {"name": "Monkey D. Luffy", "universe": "anime", "franchise": "One Piece", "real_name": "Monkey D. Luffy", "tags": ["onepiece", "pirate", "devil-fruit"]},
            {"name": "Eren Yeager", "universe": "anime", "franchise": "Attack on Titan", "real_name": "Eren Yeager", "tags": ["aot", "titan", "antihero"]},
            {"name": "Light Yagami", "universe": "anime", "franchise": "Death Note", "real_name": "Light Yagami", "tags": ["deathnote", "antihero", "genius"]},
            {"name": "Levi Ackerman", "universe": "anime", "franchise": "Attack on Titan", "real_name": "Levi Ackerman", "tags": ["aot", "captain", "skilled"]},
            {"name": "Sukuna", "universe": "anime", "franchise": "Jujutsu Kaisen", "real_name": "Ryomen Sukuna", "tags": ["jjk", "curse", "villain"]},
            {"name": "Gojo Satoru", "universe": "anime", "franchise": "Jujutsu Kaisen", "real_name": "Satoru Gojo", "tags": ["jjk", "sorcerer", "teacher"]},
            # ============================================================
            # Gaming
            # ============================================================
            {"name": "Master Chief", "universe": "gaming", "franchise": "Halo", "real_name": "John-117", "tags": ["halo", "spartan", "unsc"]},
            {"name": "Kratos", "universe": "gaming", "franchise": "God of War", "real_name": "Kratos", "tags": ["godofwar", "spartan", "god-slayer"]},
            {"name": "Geralt of Rivia", "universe": "gaming", "franchise": "The Witcher", "real_name": "Geralt of Rivia", "tags": ["witcher", "monster-hunter", "mutant"]},
            {"name": "Lara Croft", "universe": "gaming", "franchise": "Tomb Raider", "real_name": "Lara Croft", "tags": ["tombraider", "archaeologist", "adventurer"]},
            {"name": "Mario", "universe": "gaming", "franchise": "Super Mario", "real_name": "Mario Mario", "tags": ["nintendo", "plumber", "mushroom"]},
            {"name": "Link", "universe": "gaming", "franchise": "The Legend of Zelda", "real_name": "Link", "tags": ["zelda", "hero", "hyrule"]},
            {"name": "Solid Snake", "universe": "gaming", "franchise": "Metal Gear", "real_name": "David / Solid Snake", "tags": ["metalgear", "stealth", "soldier"]},
            {"name": "Arthur Morgan", "universe": "gaming", "franchise": "Red Dead Redemption", "real_name": "Arthur Morgan", "tags": ["rdr2", "outlaw", "cowboy"]},
            {"name": "Joel Miller", "universe": "gaming", "franchise": "The Last of Us", "real_name": "Joel Miller", "tags": ["tlou", "smuggler", "survivor"]},
            {"name": "Ellie Williams", "universe": "gaming", "franchise": "The Last of Us", "real_name": "Ellie Williams", "tags": ["tlou", "immune", "survivor"]},
            # ============================================================
            # Film
            # ============================================================
            {"name": "John Wick", "universe": "film", "franchise": "John Wick", "real_name": "Jardani Jovonovich", "tags": ["action", "assassin", "revenge"]},
            {"name": "Vito Corleone", "universe": "film", "franchise": "The Godfather", "real_name": "Vito Andolini Corleone", "tags": ["godfather", "mob", "patriarch"]},
            {"name": "Michael Corleone", "universe": "film", "franchise": "The Godfather", "real_name": "Michael Corleone", "tags": ["godfather", "mob", "don"]},
            {"name": "Hannibal Lecter", "universe": "film", "franchise": "Hannibal", "real_name": "Hannibal Lecter", "tags": ["thriller", "villain", "cannibal"]},
            {"name": "Tyler Durden", "universe": "film", "franchise": "Fight Club", "real_name": "Tyler Durden", "tags": ["fightclub", "antihero", "anarchy"]},
            {"name": "Neo", "universe": "film", "franchise": "The Matrix", "real_name": "Thomas A. Anderson", "tags": ["matrix", "hero", "chosen"]},
            {"name": "Indiana Jones", "universe": "film", "franchise": "Indiana Jones", "real_name": "Henry Walton Jones Jr.", "tags": ["adventure", "archaeologist", "hero"]},
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

        series_id = generate_id("cs")
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
    # MULTI-CHARACTER RANKING CAROUSEL
    # ==================================================================

    RANKING_THEMES = {
        "heroes_turned_villain": "Heroes Who Became Villains",
        "most_powerful": "Most Powerful Characters",
        "best_fighters": "Best Hand-to-Hand Fighters",
        "tragic_backstories": "Most Tragic Backstories",
        "best_redemption_arcs": "Best Redemption Arcs",
        "most_intelligent": "Smartest Characters",
        "scariest_villains": "Most Terrifying Villains",
        "underrated_heroes": "Most Underrated Heroes",
    }

    async def generate_ranking_carousel(
        self,
        theme: str = "most_powerful",
        universe: Optional[str] = None,
        character_ids: Optional[List[str]] = None,
    ) -> CharacterCarousel:
        """Generate a multi-character ranking (Top 5) carousel.

        Each slide features a different character from the ranking.
        """
        theme_title = self.RANKING_THEMES.get(theme, theme.replace("_", " ").title())

        # Get characters to rank
        if character_ids:
            characters = []
            async with get_session() as session:
                for cid in character_ids[:5]:
                    char = await session.get(CharacterModel, cid)
                    if char and char.fact_bank:
                        characters.append(char)
        else:
            all_chars = await self.list_characters(research_status="completed")
            if universe:
                all_chars = [c for c in all_chars if c.universe == universe]
            characters_raw = []
            for char in all_chars:
                async with get_session() as session:
                    row = await session.get(CharacterModel, char.id)
                    if row and row.fact_bank and len(row.fact_bank) >= 5:
                        characters_raw.append(row)
            # Pick 5 random characters with enough facts
            import random
            characters = random.sample(characters_raw, min(5, len(characters_raw)))

        if len(characters) < 3:
            raise ValueError(f"Need at least 3 researched characters for a ranking, found {len(characters)}")

        # Build facts for all characters
        char_names = [c.name for c in characters]
        all_facts = ""
        for char in characters:
            facts = [f.get("text", "") for f in (char.fact_bank or [])[:8]]
            all_facts += f"\n\n{char.name}:\n" + "\n".join(f"- {f}" for f in facts)

        universe_label = universe or characters[0].universe

        # Get the power_ranking template
        template_svc = get_story_template_service()
        template = await template_svc.get_template("power_ranking")

        if template:
            prompt = template.prompt_template.format(
                ranking_theme=theme_title,
                universe=universe_label,
                character_names=", ".join(char_names),
                facts=all_facts,
            )
            system = CAROUSEL_SYSTEM_PROMPT
        else:
            prompt = f"""Create a 6-slide "Top 5" ranking carousel: {theme_title} in {universe_label}.

Characters: {', '.join(char_names)}
Facts: {all_facts}

Slide 1: Hook announcing the ranking.
Slides 2-6: Count down from #5 to #1. Each slide features ONE different character.
Each entry: Character name + 1-2 sentences why they rank here.
Use image_query to find each character.
NEVER use em dashes, markdown asterisks, or formatting markup. Plain text only.

Return JSON:
{{"hook_text": "...", "slides": [{{"slide_num": 1, "text": "...", "image_query": "..."}}], "caption": "...", "hashtags": ["..."], "music_mood": "epic"}}"""
            system = CAROUSEL_SYSTEM_PROMPT

        gen_start = time.monotonic()
        raw_response = None
        try:
            async with _OLLAMA_SEMAPHORE:
                raw_response = await self._ollama.chat(
                    prompt=prompt,
                    system=system,
                    task_type="character_research",
                    temperature=0.8,
                    num_predict=4096,
                    timeout=600,
                    max_retries=1,
                )
        except (TimeoutError, ConnectionError, ValueError) as e:
            logger.warning("ranking_carousel_llm_failed", error=str(e))

        try:
            if not raw_response:
                raise ValueError("LLM call failed")
            result = parse_json_response(raw_response, f"ranking_{theme}")
            result = sanitize_carousel(result, character_name=char_names[0])
            if not isinstance(result, dict) or "slides" not in result:
                raise ValueError("Invalid ranking carousel JSON")
        except (ValueError, json.JSONDecodeError) as e:
            logger.debug("ranking_carousel_fallback", error=str(e))
            result = {
                "hook_text": f"Top {len(characters)} {theme_title}...",
                "slides": [
                    {"slide_num": 1, "text": f"Top {len(characters)} {theme_title}", "image_query": f"{universe_label} characters"}
                ] + [
                    {"slide_num": i + 2, "text": f"#{len(characters) - i}: {c.name}", "image_query": f"{c.name} {universe_label}"}
                    for i, c in enumerate(characters)
                ],
                "caption": f"Who would you add to this list? #{universe_label}",
                "hashtags": [universe_label.lower(), "top5", "ranking", "fyp"],
                "music_mood": "epic",
            }

        slides = result.get("slides", [])
        # Assign images from each ranked character
        for slide in slides:
            query = slide.get("image_query", "")
            for char in characters:
                if char.name.lower() in query.lower():
                    images = char.image_urls or []
                    if images:
                        slide["image_url"] = images[0] if isinstance(images[0], str) else images[0]
                    break

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

        duration_ms = int((time.monotonic() - gen_start) * 1000)
        carousel_id = generate_id("cc")
        primary_char = characters[0]

        async with get_session() as session:
            row = CharacterCarouselModel(
                id=carousel_id,
                character_id=primary_char.id,
                angle="power_ranking",
                title=result.get("title", f"Top {len(characters)} {theme_title}"),
                hook_text=result.get("hook_text", ""),
                slides=slides,
                caption=result.get("caption", ""),
                hashtags=result.get("hashtags", []),
                music_mood=result.get("music_mood", "epic"),
                status="draft",
                story_template="power_ranking",
                multi_character_ids=[c.id for c in characters],
                text_overlay_specs=text_overlay_specs,
                hook_style="superlative",
                content_format="ranking",
                generation_metadata={
                    "template": "power_ranking",
                    "template_name": "Power Ranking",
                    "ranking_theme": theme,
                    "ranking_theme_title": theme_title,
                    "ranked_characters": char_names,
                    "duration_ms": duration_ms,
                    "angle": "power_ranking",
                    "content_format": "ranking",
                },
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            char_name = primary_char.name

        try:
            return await self.ai_review_carousel(carousel_id)
        except (ValueError, KeyError, RuntimeError, TimeoutError) as exc:
            logger.warning("ranking_carousel_review_failed", error=str(exc))
            async with get_session() as session:
                row = await session.get(CharacterCarouselModel, carousel_id)
                return carousel_to_pydantic(row, char_name)

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

        # Hook style rotation: cycle through styles, max 2 per style per batch
        from app.models.character_content import HookStyle
        hook_styles = [hs.value for hs in HookStyle]
        hook_style_usage: Dict[str, int] = {}
        max_per_hook_style = 2

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

            # Pick hook style with diversity enforcement
            selected_hook_style = None
            candidate_style = hook_styles[idx % len(hook_styles)]
            if hook_style_usage.get(candidate_style, 0) < max_per_hook_style:
                selected_hook_style = candidate_style
            else:
                for hs in hook_styles:
                    if hook_style_usage.get(hs, 0) < max_per_hook_style:
                        selected_hook_style = hs
                        break
            if selected_hook_style:
                hook_style_usage[selected_hook_style] = hook_style_usage.get(selected_hook_style, 0) + 1

            # Map template to content format
            template_format_map = {
                "storyline_recap": "storyline",
                "power_ranking": "ranking",
                "versus_battle": "versus",
                "versus_breakdown": "versus",
                "timeline_story": "timeline",
                "timeline_tragedy": "timeline",
                "hot_take": "hot_take",
            }
            content_format = template_format_map.get(template, "fact_list")

            try:
                carousel = await self.generate_carousel(CarouselCreate(
                    character_id=char.id,
                    angle=angle,
                    story_template=template,
                    slide_count=6,
                    hook_style=selected_hook_style,
                    content_format=content_format,
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
    # PHASE 024: CHARACTER AUTOPILOT
    # ==================================================================

    async def auto_approve_eligible(self, limit: int = 20) -> Dict[str, Any]:
        """Auto-approve carousels with final_review_score >= threshold.

        - status='review' or 'pending_review' AND final_review_score >= threshold
        - character.autonomous_disabled=false
        - Flags carousels below 75 as needs_work, 75-84 stays in review for humans.
        """
        from app.infrastructure.config import get_settings
        settings = get_settings()
        if not getattr(settings, "character_autopilot_enabled", True):
            return {"approved": 0, "needs_work": 0, "reason": "autopilot_disabled"}

        threshold = float(getattr(settings, "character_auto_approve_threshold", 85.0))
        approved_count = 0
        needs_work_count = 0

        async with get_session() as session:
            result = await session.execute(
                select(CharacterCarouselModel, CharacterModel)
                .join(CharacterModel, CharacterModel.id == CharacterCarouselModel.character_id)
                .where(
                    CharacterCarouselModel.status.in_(["review", "pending_review", "ai_reviewed"]),
                    CharacterCarouselModel.final_review_score.is_not(None),
                    CharacterCarouselModel.auto_approved.is_(None),
                    CharacterModel.autonomous_disabled.is_(False),
                )
                .order_by(CharacterCarouselModel.final_review_score.desc())
                .limit(limit)
            )
            rows = result.all()
            now = datetime.now(timezone.utc)
            for carousel, _char in rows:
                score = float(carousel.final_review_score or 0)
                if score >= threshold:
                    carousel.status = "approved"
                    carousel.auto_approved = True
                    carousel.auto_approved_at = now
                    carousel.auto_approve_reason = f"final_review_score>={threshold}"
                    carousel.publish_status = "queued"
                    approved_count += 1
                elif score < 75:
                    carousel.status = "needs_work"
                    needs_work_count += 1
            await session.commit()

        logger.info(
            "character_auto_approve_eligible",
            approved=approved_count,
            needs_work=needs_work_count,
            threshold=threshold,
        )
        return {"approved": approved_count, "needs_work": needs_work_count, "threshold": threshold}

    async def ensure_publish_backlog(self, target: int = 6) -> Dict[str, Any]:
        """Keep the approved+queued backlog above `target` by generating more carousels."""
        from app.infrastructure.config import get_settings
        settings = get_settings()
        if not getattr(settings, "character_autopilot_enabled", True):
            return {"backlog": 0, "generated": 0, "reason": "autopilot_disabled"}

        async with get_session() as session:
            result = await session.execute(
                select(sql_func.count())
                .select_from(CharacterCarouselModel)
                .where(
                    CharacterCarouselModel.status == "approved",
                    CharacterCarouselModel.publish_status == "queued",
                )
            )
            backlog = int(result.scalar() or 0)

        if backlog >= target:
            return {"backlog": backlog, "generated": 0, "reason": "sufficient"}

        needed = target - backlog
        gen_result = await self.smart_batch_generate(count=needed)
        approve_result = await self.auto_approve_eligible(limit=needed * 2)

        logger.info(
            "character_publish_backlog_topup",
            prior_backlog=backlog,
            target=target,
            generated=gen_result.get("generated", 0),
            auto_approved=approve_result.get("approved", 0),
        )
        return {
            "backlog": backlog,
            "target": target,
            "generated": gen_result.get("generated", 0),
            "auto_approved": approve_result.get("approved", 0),
        }

    async def update_priority_tier(self, character_id: str) -> str:
        """Recompute and persist a character's priority tier.

        - priority: avg_engagement >= 0.05 OR total_views >= 10000 OR discovery_hits >= 3
        - probation: posts_created >= 5 AND avg_engagement < 0.01
        - standard: otherwise
        """
        async with get_session() as session:
            char = await session.get(CharacterModel, character_id)
            if not char:
                return "standard"

            avg_eng = char.avg_engagement or 0.0
            views = char.total_views or 0
            posts = char.posts_created or 0
            hits = getattr(char, "discovery_hits", 0) or 0

            if avg_eng >= 0.05 or views >= 10000 or hits >= 3:
                tier = "priority"
            elif posts >= 5 and avg_eng < 0.01:
                tier = "probation"
            else:
                tier = "standard"

            if char.priority_tier != tier:
                char.priority_tier = tier
                await session.commit()

        return tier

    async def audit_character_gaps(self, character_id: str) -> Dict[str, Any]:
        """Return the gap dict for a single character."""
        async with get_session() as session:
            char = await session.get(CharacterModel, character_id)
            if not char:
                return {"error": "character_not_found"}

            # Count validated images
            img_result = await session.execute(
                select(sql_func.count())
                .select_from(CharacterImageModel)
                .where(
                    CharacterImageModel.character_id == character_id,
                    CharacterImageModel.is_valid.is_(True),
                )
            )
            image_count = int(img_result.scalar() or 0)

            # Existing angles used
            angle_result = await session.execute(
                select(CharacterCarouselModel.angle)
                .where(CharacterCarouselModel.character_id == character_id)
                .distinct()
            )
            used_angles = {row[0] for row in angle_result.all()}

            # Weak hooks
            hooks_result = await session.execute(
                select(CharacterCarouselModel.id, CharacterCarouselModel.ai_review)
                .where(
                    CharacterCarouselModel.character_id == character_id,
                    CharacterCarouselModel.status.in_(["draft", "review", "pending_review", "ai_reviewed"]),
                )
            )
            weak_hooks = []
            for cid, ai_review in hooks_result.all():
                if isinstance(ai_review, dict):
                    strength = ai_review.get("hook_strength")
                    if isinstance(strength, (int, float)) and strength < 6:
                        weak_hooks.append(cid)

            fact_count = len(char.fact_bank or [])
            all_angles = [a.value for a in ContentAngle]
            missing_angles = [a for a in all_angles if a not in used_angles]

        return {
            "character_id": character_id,
            "image_gap": max(0, 10 - image_count),
            "image_count": image_count,
            "missing_angles": missing_angles,
            "used_angles": sorted(used_angles),
            "fact_gap": max(0, 20 - fact_count),
            "fact_count": fact_count,
            "weak_hooks": weak_hooks,
        }

    async def fill_character_gaps(
        self,
        character_id: str,
        caps: Optional[Dict[str, int]] = None,
    ) -> Dict[str, Any]:
        """Best-effort fill for all 4 gap types, bounded by per-run caps."""
        caps = caps or {}
        images_cap = int(caps.get("images", 5))
        angles_cap = int(caps.get("angles", 3))
        hooks_cap = int(caps.get("hooks", 5))

        gaps = await self.audit_character_gaps(character_id)
        if gaps.get("error"):
            return gaps

        summary = {"character_id": character_id, "images_added": 0, "carousels_created": 0, "facts_added": 0, "hooks_regenerated": 0}

        async with get_session() as session:
            char = await session.get(CharacterModel, character_id)
            if not char:
                return summary
            name = char.name
            universe = char.universe
            franchise = char.franchise or ""

        # Images
        if gaps["image_gap"] > 0 and images_cap > 0:
            try:
                added_imgs = await self._source_images(character_id, name, universe, franchise)
                summary["images_added"] = min(len(added_imgs or []), images_cap)
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, AttributeError, RuntimeError, TypeError, SQLAlchemyError) as e:
                logger.warning("gap_fill_images_failed", character_id=character_id, error=str(e))

        # Angles: generate up to angles_cap missing angles
        for angle_val in gaps.get("missing_angles", [])[:angles_cap]:
            try:
                from app.models.character_content import CarouselCreate
                created = await self.generate_carousel(CarouselCreate(
                    character_id=character_id,
                    angle=ContentAngle(angle_val),
                ))
                if created:
                    summary["carousels_created"] += 1
                    try:
                        await self.ai_review_carousel(created.id)
                    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, AttributeError, RuntimeError, TypeError, SQLAlchemyError) as re:
                        logger.warning("gap_fill_ai_review_failed", carousel_id=created.id, error=str(re))
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, AttributeError, RuntimeError, TypeError, SQLAlchemyError) as e:
                logger.warning("gap_fill_angle_failed", character_id=character_id, angle=angle_val, error=str(e))

        # Facts: let research sources top up to 20
        if gaps["fact_gap"] > 0:
            try:
                rs = get_research_sources()
                refresh = await rs.refresh_research(character_id=character_id, name=name, universe=universe)
                summary["facts_added"] = int(refresh.get("new_facts", 0)) if isinstance(refresh, dict) else 0
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, AttributeError, RuntimeError, TypeError, SQLAlchemyError) as e:
                logger.warning("gap_fill_facts_failed", character_id=character_id, error=str(e))

        # Hooks: delegate to hook service if present (Phase 5)
        try:
            from app.services.character_hook_service import get_character_hook_service
            hook_svc = get_character_hook_service()
            for cid in gaps.get("weak_hooks", [])[:hooks_cap]:
                try:
                    await hook_svc.regenerate_hook(cid)
                    summary["hooks_regenerated"] += 1
                except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, AttributeError, RuntimeError, TypeError, SQLAlchemyError) as he:
                    logger.warning("gap_fill_hook_failed", carousel_id=cid, error=str(he))
        except ImportError:
            # Phase 5 not yet deployed. Log-and-skip.
            logger.info("gap_fill_hooks_skipped_no_service", character_id=character_id,
                        weak_hooks=len(gaps.get("weak_hooks", [])))

        await self.update_priority_tier(character_id)
        return summary

    async def run_gap_audit_cycle(self, max_characters: int = 20) -> Dict[str, Any]:
        """Iterate active, non-disabled characters and fill gaps (priority tier first)."""
        from sqlalchemy import case
        tier_rank = case(
            (CharacterModel.priority_tier == "priority", 0),
            (CharacterModel.priority_tier == "probation", 1),
            else_=2,
        )
        async with get_session() as session:
            result = await session.execute(
                select(CharacterModel.id)
                .where(
                    CharacterModel.status == "active",
                    CharacterModel.autonomous_disabled.is_(False),
                )
                .order_by(
                    tier_rank.asc(),
                    CharacterModel.last_researched.asc().nulls_first(),
                )
                .limit(max_characters)
            )
            ids = [row[0] for row in result.all()]

        totals = {"characters_audited": 0, "images_added": 0, "carousels_created": 0, "facts_added": 0, "hooks_regenerated": 0}
        for cid in ids:
            try:
                summary = await self.fill_character_gaps(cid)
                totals["characters_audited"] += 1
                totals["images_added"] += summary.get("images_added", 0)
                totals["carousels_created"] += summary.get("carousels_created", 0)
                totals["facts_added"] += summary.get("facts_added", 0)
                totals["hooks_regenerated"] += summary.get("hooks_regenerated", 0)
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, AttributeError, RuntimeError, TypeError, SQLAlchemyError) as e:
                logger.warning("gap_audit_character_failed", character_id=cid, error=str(e))

        return totals

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

        # Build no-break term set from character name so multi-word names
        # ("Black Widow", "Iron Man") never split across lines. Defaults for
        # franchise terms ("The MCU") are baked into the renderer.
        no_break_terms: List[str] = []
        if char and char.name:
            no_break_terms.append(char.name)

        # Render all slides
        renderer = get_carousel_renderer()
        render_result = await renderer.render_carousel(
            carousel_id=carousel_id,
            slides=slides,
            text_overlay_specs=text_overlay_specs,
            character_image_url=image_url,
            character_image_urls=image_urls,
            no_break_terms=no_break_terms or None,
        )
        rendered_paths = render_result.get("paths", [])
        render_warnings = render_result.get("render_warnings", [])

        # Mark published, persist render_warnings on generation_metadata for the
        # visual-qa skill to read.
        now = datetime.now(timezone.utc)
        async with get_session() as session:
            row = await session.get(CharacterCarouselModel, carousel_id)
            if row:
                row.publish_status = "published"
                row.published_at = now
                row.download_urls = rendered_paths
                row.status = "published"
                row.watermark_applied = True
                meta = dict(row.generation_metadata or {})
                meta["render_warnings"] = render_warnings
                meta["last_rendered_at"] = now.isoformat()
                row.generation_metadata = meta
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
                async with _OLLAMA_SEMAPHORE:
                    response = await self._ollama.chat(
                        prompt=prompt,
                        system="You are a viral TikTok caption writer. Return only the caption.",
                        task_type="character_research",
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

    # ==================================================================
    # CAROUSEL VERSIONING + AI ENHANCEMENT (Phase 027)
    # ==================================================================

    _VERSION_SNAPSHOT_DEBOUNCE_SEC = 60
    _VERSION_MAX_ROWS_PER_CAROUSEL = 50

    async def _snapshot_carousel(
        self,
        session,
        row: CharacterCarouselModel,
        source: str,
        source_metadata: Dict[str, Any],
        created_by: str = "user",
    ) -> str:
        """Insert a version row capturing the carousel's current state.

        Debounces consecutive manual_edit snapshots within 60s when they
        touch overlapping fields so UI auto-save doesn't spam the history.
        """
        # Find latest version number + debounce candidate.
        q = (
            select(CharacterCarouselVersionModel)
            .where(CharacterCarouselVersionModel.carousel_id == row.id)
            .order_by(CharacterCarouselVersionModel.version_number.desc())
            .limit(1)
        )
        result = await session.execute(q)
        last = result.scalar_one_or_none()

        next_number = (last.version_number + 1) if last else 1
        parent_id = last.id if last else None

        # Debounce: if same source+overlap within window, overwrite in place.
        if (
            last is not None
            and source == "manual_edit"
            and last.source == "manual_edit"
            and last.created_at is not None
        ):
            now = datetime.now(timezone.utc)
            age = (now - last.created_at).total_seconds()
            last_fields = set((last.source_metadata or {}).get("fields", []))
            new_fields = set(source_metadata.get("fields", []))
            if age < self._VERSION_SNAPSHOT_DEBOUNCE_SEC and (last_fields & new_fields):
                # Update the existing snapshot in place (merge field lists).
                merged_fields = sorted(last_fields | new_fields)
                last.source_metadata = {**(last.source_metadata or {}), "fields": merged_fields}
                last.title = row.title
                last.hook_text = row.hook_text
                last.slides = list(row.slides or [])
                last.caption = row.caption
                last.hashtags = list(row.hashtags or [])
                last.human_notes = row.human_notes
                last.music_track = row.music_track
                last.text_overlay_specs = list(row.text_overlay_specs or [])
                row.current_version_id = last.id
                return last.id

        version_id = f"ccv-{uuid.uuid4().hex[:12]}"
        version = CharacterCarouselVersionModel(
            id=version_id,
            carousel_id=row.id,
            version_number=next_number,
            parent_version_id=parent_id,
            title=row.title,
            hook_text=row.hook_text,
            slides=list(row.slides or []),
            caption=row.caption,
            hashtags=list(row.hashtags or []),
            human_notes=row.human_notes,
            music_track=row.music_track,
            text_overlay_specs=list(row.text_overlay_specs or []),
            source=source,
            source_metadata=source_metadata,
            created_by=created_by,
        )
        session.add(version)
        row.current_version_id = version_id

        # Prune oldest if cap exceeded.
        if next_number > self._VERSION_MAX_ROWS_PER_CAROUSEL:
            prune_q = (
                select(CharacterCarouselVersionModel.id)
                .where(CharacterCarouselVersionModel.carousel_id == row.id)
                .order_by(CharacterCarouselVersionModel.version_number.asc())
                .limit(next_number - self._VERSION_MAX_ROWS_PER_CAROUSEL)
            )
            to_prune = (await session.execute(prune_q)).scalars().all()
            if to_prune:
                await session.execute(
                    delete(CharacterCarouselVersionModel).where(
                        CharacterCarouselVersionModel.id.in_(to_prune)
                    )
                )

        return version_id

    async def list_carousel_versions(self, carousel_id: str, limit: int = 50) -> List[CarouselVersion]:
        async with get_session() as session:
            q = (
                select(CharacterCarouselVersionModel)
                .where(CharacterCarouselVersionModel.carousel_id == carousel_id)
                .order_by(CharacterCarouselVersionModel.version_number.desc())
                .limit(limit)
            )
            rows = (await session.execute(q)).scalars().all()
            return [version_to_pydantic(r) for r in rows]

    async def restore_carousel_version(
        self, carousel_id: str, version_id: str, *, force: bool = False, created_by: str = "user"
    ) -> Optional[RestoreVersionResponse]:
        async with get_session() as session:
            row = await session.get(CharacterCarouselModel, carousel_id)
            if not row:
                return None
            if not force and (row.status or "").lower() == "published":
                raise ValueError("Cannot restore a published carousel without force=True")

            version = await session.get(CharacterCarouselVersionModel, version_id)
            if not version or version.carousel_id != carousel_id:
                raise ValueError(f"Version {version_id} not found for carousel {carousel_id}")

            # Snapshot current state before overwriting.
            await self._snapshot_carousel(
                session, row,
                source="restore",
                source_metadata={"restored_from": version_id, "restored_version_number": version.version_number},
                created_by=created_by,
            )

            # Copy fields from version into row.
            row.title = version.title
            row.hook_text = version.hook_text
            row.slides = list(version.slides or [])
            row.caption = version.caption
            row.hashtags = list(version.hashtags or [])
            row.human_notes = version.human_notes
            row.music_track = version.music_track
            row.text_overlay_specs = list(version.text_overlay_specs or [])

            await session.commit()
            await session.refresh(row)
            char = await session.get(CharacterModel, row.character_id)
            char_name = char.name if char else None
            return RestoreVersionResponse(
                carousel=carousel_to_pydantic(row, char_name),
                restored_from=version_id,
            )

    # ------------------------------------------------------------------
    # AI ENHANCEMENT
    # ------------------------------------------------------------------

    _ENHANCE_SYSTEM_PROMPT = (
        "You rewrite TikTok carousel copy to be more specific, surprising, and captivating. "
        "Never use em dashes. Keep it punchy. Always reference the specific character. "
        "No stock openers like 'The Hammer Lie', 'Nobody talks about', 'What they don't tell you'. "
        "Return ONLY the new text, no quotes, no commentary, no markdown."
    )

    def _build_enhance_prompt(
        self,
        target: str,
        slide_num: Optional[int],
        carousel: CharacterCarouselModel,
        character: Optional[CharacterModel],
        instruction: Optional[str],
    ) -> tuple[str, str]:
        """Return (system_prompt, user_prompt)."""
        char_name = character.name if character else "the character"
        universe = character.universe if character else ""
        angle = carousel.angle or "general"

        # Snippet of other slides for context.
        slide_lines = []
        for s in (carousel.slides or [])[:8]:
            n = s.get("slide_num", 0)
            t = (s.get("text") or "")[:140]
            slide_lines.append(f"  Slide {n}: {t}")
        slide_block = "\n".join(slide_lines) or "  (no slides)"

        base_context = (
            f"Character: {char_name}\n"
            f"Universe: {universe}\n"
            f"Angle: {angle}\n"
            f"Existing hook: {(carousel.hook_text or '')[:200]}\n"
            f"Existing caption: {(carousel.caption or '')[:200]}\n"
            f"Slides:\n{slide_block}\n"
        )

        if target == "hook":
            user = (
                f"{base_context}\n"
                "Rewrite the hook (opening line that stops the scroll). "
                "Must name the character or a specific proper noun. "
                "<=110 chars. No quotes. No emoji. One line."
            )
        elif target == "slide":
            current = ""
            if slide_num is not None:
                for s in carousel.slides or []:
                    if s.get("slide_num") == slide_num:
                        current = s.get("text") or ""
                        break
            user = (
                f"{base_context}\n"
                f"Rewrite the body text for slide #{slide_num}. "
                f"Current text: {current[:400]}\n"
                "Make it punchier, specific to the character, no generic filler. "
                "<=220 chars. No quotes. Preserve any concrete facts."
            )
        elif target == "caption":
            user = (
                f"{base_context}\n"
                "Rewrite the TikTok caption. "
                "Include 1-2 relevant emoji, a short question or hook, no hashtags. "
                "<=150 chars."
            )
        elif target == "hashtags":
            user = (
                f"{base_context}\n"
                "Produce 6-10 TikTok hashtags for this carousel. "
                "Mix: 2 broad reach tags, 3 niche tags, 2 character-specific. "
                "Return space-separated hashtags starting with #. No other text."
            )
        else:  # all
            user = (
                f"{base_context}\n"
                "Rewrite hook, all slide bodies, and caption. Return JSON with keys "
                '"hook_text" (string), "slides" (array of {slide_num, text}), '
                '"caption" (string), "hashtags" (array of strings).'
            )

        if instruction:
            user = f"{user}\n\nExtra instruction from operator: {instruction.strip()}"

        return self._ENHANCE_SYSTEM_PROMPT, user

    async def enhance_carousel_piece(
        self,
        carousel_id: str,
        req: EnhanceCarouselRequest,
    ) -> EnhanceCarouselResponse:
        """Generate N variants for the requested target without applying them."""
        from app.infrastructure.unified_llm_client import get_unified_llm_client

        async with get_session() as session:
            carousel = await session.get(CharacterCarouselModel, carousel_id)
            if not carousel:
                raise ValueError(f"Carousel {carousel_id} not found")
            character = await session.get(CharacterModel, carousel.character_id)

        provider = (req.provider or "kimi").strip().lower()
        # Default models per provider. Operator can override via req.model.
        default_model = {
            "kimi": "moonshot-v1-32k",
            "minimax": "MiniMax-M2.7",
            "ollama": "qwen3.6:35b-a3b-q8_0",
            "gemini": "gemini-2.5-flash",
        }.get(provider, "kimi-k2.5")
        model_name = req.model or default_model
        # Kimi K2.5 requires temperature=1 exactly; pick diverse temps otherwise.
        temps = [1.0] if model_name == "kimi-k2.5" else [0.7, 0.85, 0.95, 0.6, 0.75][: max(1, req.n_variants)]
        if len(temps) < req.n_variants:
            temps = (temps * ((req.n_variants // len(temps)) + 1))[: req.n_variants]

        system, user = self._build_enhance_prompt(
            req.target, req.slide_num, carousel, character, req.instruction,
        )

        client = get_unified_llm_client()
        variants: List[EnhanceCarouselVariant] = []
        for i in range(req.n_variants):
            try:
                text = await client.chat(
                    prompt=user,
                    system=system,
                    model=f"{provider}/{model_name}",
                    temperature=temps[i],
                    max_tokens=1024,
                )
                clean = sanitize_text((text or "").strip().strip('"').strip("'"))
                if not clean:
                    continue
                variants.append(EnhanceCarouselVariant(
                    target=req.target,
                    slide_num=req.slide_num,
                    text=clean,
                    provider=provider,
                    model=model_name,
                ))
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, AttributeError, RuntimeError, TypeError, SQLAlchemyError) as exc:
                logger.warning(
                    "carousel_enhance_variant_failed",
                    carousel_id=carousel_id,
                    provider=provider,
                    model=model_name,
                    error=str(exc)[:200],
                )

        return EnhanceCarouselResponse(carousel_id=carousel_id, variants=variants)

    async def apply_enhance_variant(
        self,
        carousel_id: str,
        req: ApplyEnhanceRequest,
        *,
        created_by: str = "user",
        source: str = "enhance",
    ) -> Optional[CharacterCarousel]:
        """Apply a chosen variant to the carousel, snapshotting first."""
        async with get_session() as session:
            row = await session.get(CharacterCarouselModel, carousel_id)
            if not row:
                return None

            meta = {
                "target": req.target,
                "slide_num": req.slide_num,
                "provider": req.provider,
                "model": req.model,
            }
            await self._snapshot_carousel(
                session, row,
                source=source,
                source_metadata=meta,
                created_by=created_by,
            )

            if req.target == "hook":
                row.hook_text = sanitize_text(req.text)
            elif req.target == "caption":
                row.caption = sanitize_text(req.text)
            elif req.target == "hashtags":
                tags = [t.strip() for t in re.split(r"[\s,]+", req.text) if t.strip()]
                row.hashtags = [t if t.startswith("#") else f"#{t}" for t in tags]
            elif req.target == "slide":
                if req.slide_num is None:
                    raise ValueError("slide_num required when target='slide'")
                slides = list(row.slides or [])
                for idx, s in enumerate(slides):
                    if s.get("slide_num") == req.slide_num:
                        slides[idx] = {**s, "text": sanitize_text(req.text)}
                        break
                row.slides = slides
            elif req.target == "all":
                # Expect JSON payload in req.text.
                try:
                    payload = json.loads(req.text)
                except json.JSONDecodeError:
                    raise ValueError("target='all' requires JSON text payload")
                if "hook_text" in payload:
                    row.hook_text = sanitize_text(payload["hook_text"])
                if "caption" in payload:
                    row.caption = sanitize_text(payload["caption"])
                if "hashtags" in payload:
                    row.hashtags = [str(h) for h in payload["hashtags"] or []]
                if "slides" in payload:
                    existing = {s.get("slide_num"): s for s in (row.slides or [])}
                    new_slides = []
                    for s in payload["slides"] or []:
                        n = s.get("slide_num")
                        base = existing.get(n, {"slide_num": n})
                        base = {**base, "text": sanitize_text(s.get("text") or "")}
                        new_slides.append(base)
                    if new_slides:
                        row.slides = new_slides

            await session.commit()
            await session.refresh(row)
            char = await session.get(CharacterModel, row.character_id)
            char_name = char.name if char else None
            return carousel_to_pydantic(row, char_name)

    # ------------------------------------------------------------------
    # COUNCIL VOTE ON VARIANTS
    # ------------------------------------------------------------------

    async def run_council_on_carousel(
        self,
        carousel_id: str,
        req: CouncilVoteRequest,
    ) -> CouncilVoteResponse:
        """Generate N variants across multiple providers, let the council rank
        them, return the winner. Does NOT auto-apply.
        """
        from app.infrastructure.unified_llm_client import get_unified_llm_client
        from app.services.council_service import get_council_service, COUNCIL_ROLES
        from app.models.agent_company import CouncilProposal
        from app.db.models import CouncilDecisionModel

        # 1. Generate diverse variants across providers.
        providers = req.providers or ["kimi", "minimax", "ollama"]
        n_per = max(1, req.n_variants // max(1, len(providers)))
        remainder = req.n_variants - n_per * len(providers)
        variants: List[EnhanceCarouselVariant] = []
        for idx, provider in enumerate(providers):
            count = n_per + (1 if idx < remainder else 0)
            if count <= 0:
                continue
            enh_req = EnhanceCarouselRequest(
                target=req.target,
                slide_num=req.slide_num,
                provider=provider,
                n_variants=count,
            )
            try:
                resp = await self.enhance_carousel_piece(carousel_id, enh_req)
                variants.extend(resp.variants)
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, AttributeError, RuntimeError, TypeError, SQLAlchemyError) as exc:
                logger.warning(
                    "council_variant_gen_failed",
                    carousel_id=carousel_id,
                    provider=provider,
                    error=str(exc)[:200],
                )

        if len(variants) < 2:
            raise ValueError(
                f"Council vote requires >=2 variants, got {len(variants)}. "
                "Check provider availability or budget."
            )

        # 2. Propose council decision.
        council = get_council_service()
        async with get_session() as session:
            row = await session.get(CharacterCarouselModel, carousel_id)
            character = await session.get(CharacterModel, row.character_id) if row else None

        char_name = character.name if character else "character"
        proposal = CouncilProposal(
            topic=f"Pick best {req.target} rewrite for {char_name}"[:500],
            context={
                "carousel_id": carousel_id,
                "character_name": char_name,
                "target": req.target,
                "slide_num": req.slide_num,
                "variants": [{"rank": i, "provider": v.provider, "model": v.model, "text": v.text} for i, v in enumerate(variants)],
            },
            proposer_role="ceo",
        )
        decision = await council.propose(proposal)

        # 3. Ask each role to rank variants. Structured output.
        client = get_unified_llm_client()
        variants_text = "\n".join(
            f"[{i}] {v.text}" for i, v in enumerate(variants)
        )

        role_rankings: Dict[str, Dict[str, Any]] = {}
        for role_id, config in COUNCIL_ROLES.items():
            prompt = (
                f"You are ranking {len(variants)} TikTok hook/body variants for {char_name}.\n"
                f"Target field: {req.target}\n\n"
                f"Variants:\n{variants_text}\n\n"
                f"{config['prompt']}\n\n"
                "Return JSON: {\"best_index\": <int>, \"ranking\": [<indices in order best->worst>], "
                "\"reasoning\": \"why best wins\", \"confidence\": 0-100}"
            )
            try:
                result = await client.structured_chat(
                    prompt=prompt,
                    system=f"Pick the most captivating, character-specific variant from the {config['lens']} lens.",
                    task_type="structured_output",
                    temperature=0.3,
                    max_tokens=512,
                )
                if isinstance(result, dict):
                    role_rankings[role_id] = result
                else:
                    role_rankings[role_id] = {"best_index": 0, "ranking": list(range(len(variants))), "reasoning": str(result)[:200], "confidence": 50}
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, AttributeError, RuntimeError, TypeError, SQLAlchemyError) as exc:
                logger.warning(
                    "council_role_rank_failed",
                    carousel_id=carousel_id,
                    role=role_id,
                    error=str(exc)[:200],
                )
                role_rankings[role_id] = {"best_index": 0, "ranking": list(range(len(variants))), "reasoning": "vote_failed", "confidence": 25}

        # 4. Aggregate using Borda count (rank points).
        scores = [0.0 for _ in variants]
        for role_id, result in role_rankings.items():
            ranking = result.get("ranking") or []
            confidence = float(result.get("confidence", 50)) / 100.0
            for rank_pos, v_idx in enumerate(ranking):
                if 0 <= v_idx < len(variants):
                    scores[v_idx] += (len(variants) - rank_pos) * confidence

        winning_rank = max(range(len(variants)), key=lambda i: scores[i])
        winning_variant = variants[winning_rank]
        reasoning = [
            f"{role}: {(r.get('reasoning') or '')[:180]}"
            for role, r in role_rankings.items()
        ]
        avg_conf = sum(float(r.get("confidence", 50)) for r in role_rankings.values()) / max(len(role_rankings), 1)

        # 5. Persist council decision outcome.
        async with get_session() as session:
            d_row = await session.get(CouncilDecisionModel, decision.id)
            if d_row:
                d_row.rounds = [{"round": 1, "votes": role_rankings}]
                d_row.votes = role_rankings
                d_row.decision = f"variant_{winning_rank}"
                d_row.confidence_score = round(avg_conf, 1)
                d_row.decided_at = datetime.now(timezone.utc)
                await session.commit()

        logger.info(
            "carousel_council_vote",
            carousel_id=carousel_id,
            decision_id=decision.id,
            target=req.target,
            winning_rank=winning_rank,
            confidence=avg_conf,
        )

        return CouncilVoteResponse(
            carousel_id=carousel_id,
            decision_id=decision.id,
            target=req.target,
            slide_num=req.slide_num,
            winning_variant=winning_variant,
            winning_rank=winning_rank,
            variants=variants,
            votes={k: v for k, v in role_rankings.items()},
            reasoning=reasoning,
        )

    # ------------------------------------------------------------------
    # BANNED HOOK BACKFILL
    # ------------------------------------------------------------------

    async def backfill_banned_hooks(
        self,
        req: BackfillBannedHooksRequest,
        *,
        created_by: str = "scheduler",
    ) -> BackfillBannedHooksResult:
        """Scan existing carousels for banned hook patterns and rewrite them.

        Only touches carousels in status draft/review/approved. Never published.
        """
        result = BackfillBannedHooksResult()
        safe_statuses = ("draft", "review", "approved", "ai_reviewed", "pending_review")

        async with get_session() as session:
            q = (
                select(CharacterCarouselModel)
                .where(CharacterCarouselModel.status.in_(safe_statuses))
                .order_by(CharacterCarouselModel.created_at.desc())
                .limit(req.limit)
            )
            rows = (await session.execute(q)).scalars().all()
            result.scanned = len(rows)

            for row in rows:
                try:
                    char = await session.get(CharacterModel, row.character_id)
                    char_name = char.name if char else None
                    hook = row.hook_text or ""
                    if not hook or not char_name:
                        continue
                    if not is_generic_hook(hook, char_name):
                        continue
                    result.flagged += 1
                    if req.dry_run:
                        continue

                    # Prefer deterministic rewrite first (fast, cheap).
                    rewritten = rewrite_generic_hook(hook, char_name, {"slides": row.slides or []})
                    if rewritten and not is_generic_hook(rewritten, char_name):
                        await self._snapshot_carousel(
                            session, row,
                            source="backfill",
                            source_metadata={"old_hook": hook[:200], "strategy": "deterministic"},
                            created_by=created_by,
                        )
                        row.hook_text = rewritten
                        await session.commit()
                        result.rewritten += 1
                        logger.info("carousel_hook_backfilled", carousel_id=row.id, old=hook[:80], new=rewritten[:80])
                except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, AttributeError, RuntimeError, TypeError, SQLAlchemyError) as exc:
                    result.errors.append(f"{row.id}: {str(exc)[:120]}")
                    logger.warning("carousel_backfill_failed", carousel_id=row.id, error=str(exc)[:200])

        return result


@lru_cache()
def get_character_content_service() -> CharacterContentService:
    return CharacterContentService()
