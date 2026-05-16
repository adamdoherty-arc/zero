"""
Media Content Service.

Manages TV show and movie profiles, research pipelines, carousel generation,
and content linking to characters. Shares carousel review/enhance/publish
infrastructure with the character content pipeline.
"""

import asyncio
import json
import re
import uuid
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from functools import lru_cache, wraps

import structlog
from sqlalchemy import select, update, delete, func as sql_func
from sqlalchemy.exc import IntegrityError

from app.infrastructure.database import get_session
from app.infrastructure.config import get_settings
from app.infrastructure.llm_router import get_llm_router
from app.db.models import (
    CharacterModel, CharacterCarouselModel,
    MediaTitleModel, CharacterMediaTitleModel,
    MediaImageModel, MediaResearchFragmentModel,
)
from app.models.media_content import (
    MediaTitle, MediaTitleCreate, MediaTitleUpdate,
    MediaCarouselCreate, MediaContentAngle, MediaStoryTemplate,
    CharacterMediaLink, CharacterMediaLinkCreate,
    MediaImage, MediaImageCreate,
    MediaStats, TMDBSearchResult,
    MediaBatchGenerateRequest,
)
from app.models.character_content import (
    CharacterCarousel, CarouselApproval, CarouselRejection,
    HookStyle, ContentFormat,
)
from app.services.character_content_utils import (
    generate_id, sanitize_text, parse_json_response,
    carousel_to_pydantic, media_title_to_pydantic, media_image_to_pydantic,
)
from app.services.media_research_sources import MediaResearchService

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Angle-to-category mapping for fact filtering
# ---------------------------------------------------------------------------

MEDIA_ANGLE_CATEGORIES = {
    "plot_holes": ["plot", "trivia", "behind_scenes"],
    "best_episodes": ["plot", "review", "production"],
    "showrunner_secrets": ["production", "behind_scenes", "cast"],
    "casting_stories": ["cast", "behind_scenes", "trivia"],
    "deleted_scenes": ["behind_scenes", "production", "plot"],
    "fan_theories": ["plot", "trivia", "fan_theory"],
    "sequel_predictions": ["plot", "production", "review"],
    "box_office_analysis": ["production", "review"],
    "cinematography": ["production", "behind_scenes"],
    "soundtrack_breakdown": ["production", "behind_scenes", "trivia"],
    "season_ranking": ["review", "plot", "production"],
    "hidden_details": ["trivia", "behind_scenes", "plot"],
    "production_disasters": ["production", "behind_scenes", "cast"],
    "cultural_impact": ["review", "production", "trivia"],
    "adaptation_changes": ["plot", "behind_scenes", "production"],
    "controversial_decisions": ["review", "production", "behind_scenes"],
}


# Media carousel generation system prompt
MEDIA_CAROUSEL_SYSTEM_PROMPT = """You are a viral TikTok content creator specializing in TV show and movie content.
You create carousel posts (swipeable image posts) about TV shows and movies that go viral.

RULES:
- Every hook MUST be unique and specific to THIS show/movie. No generic hooks.
- First line must contain the title of the show/movie.
- Use surprising, specific facts that most viewers don't know.
- NO em dashes. Use periods, commas, semicolons instead.
- NO markdown formatting. Plain text only.
- Each slide should have one clear, punchy fact or point.
- Hook must create immediate curiosity gap.
- Caption should feel conversational, not corporate.
- Include 5-8 relevant hashtags.

HOOK STYLE VARIETY:
- numbered_list: "5 Things About [Title] That Will Change How You Watch It"
- story_opener: "When [director/actor] walked onto the set of [Title]..."
- hot_take: "[Title] was never supposed to be [X]. Here's proof."
- question: "Why did [Title] really [event]? The answer changes everything."
- comparison: "[Title] vs [Title]: The detail nobody noticed"
- reveal: "The secret behind [Title]'s most famous scene"
- superlative: "The most expensive scene in [Title] history cost $X"

Return ONLY valid JSON with this structure:
{
  "title": "carousel title",
  "hook_text": "compelling first-slide hook text",
  "slides": [
    {"slide_num": 1, "text": "hook text", "image_query": "search query for slide image"},
    {"slide_num": 2, "text": "fact/point", "image_query": "search query"},
    ...
  ],
  "caption": "engaging caption text",
  "hashtags": ["tag1", "tag2"],
  "music_mood": "epic|dark|emotional|mysterious|dramatic|hype|chill"
}"""


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class MediaContentService:
    """Manages TV & Movie content lifecycle."""

    def __init__(self):
        self._settings = get_settings()
        self._research_service = MediaResearchService()
        self._research_jobs: Dict[str, Dict[str, Any]] = {}

    # -----------------------------------------------------------------------
    # Media Title CRUD
    # -----------------------------------------------------------------------

    async def create_media_title(self, data: MediaTitleCreate) -> MediaTitle:
        """Create a new media title."""
        title_id = generate_id("mt")

        async with get_session() as session:
            # Check for duplicates by tmdb_id
            if data.tmdb_id:
                existing = await session.execute(
                    select(MediaTitleModel).where(MediaTitleModel.tmdb_id == data.tmdb_id)
                )
                if existing.scalar_one_or_none():
                    raise ValueError(f"Media title with TMDB ID {data.tmdb_id} already exists")

            row = MediaTitleModel(
                id=title_id,
                media_type=data.media_type.value if hasattr(data.media_type, "value") else data.media_type,
                title=data.title,
                year=data.year,
                end_year=data.end_year,
                genre=data.genre or [],
                franchise=data.franchise,
                universe=data.universe or "other",
                synopsis=data.synopsis,
                tagline=data.tagline,
                season_count=data.season_count,
                episode_count=data.episode_count,
                network=data.network,
                show_status=data.show_status,
                runtime_minutes=data.runtime_minutes,
                budget_usd=data.budget_usd,
                box_office_usd=data.box_office_usd,
                mpaa_rating=data.mpaa_rating,
                tmdb_id=data.tmdb_id,
                imdb_id=data.imdb_id,
                tags=data.tags or [],
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return media_title_to_pydantic(row)

    async def list_media_titles(
        self,
        media_type: Optional[str] = None,
        universe: Optional[str] = None,
        status: Optional[str] = None,
        research_status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[MediaTitle]:
        """List media titles with optional filters."""
        async with get_session() as session:
            query = select(MediaTitleModel).order_by(MediaTitleModel.created_at.desc())

            if media_type:
                query = query.where(MediaTitleModel.media_type == media_type)
            if universe:
                query = query.where(MediaTitleModel.universe == universe)
            if status:
                query = query.where(MediaTitleModel.status == status)
            if research_status:
                query = query.where(MediaTitleModel.research_status == research_status)

            query = query.limit(limit).offset(offset)
            result = await session.execute(query)
            titles = []
            for row in result.scalars().all():
                # Get character count
                count_result = await session.execute(
                    select(sql_func.count(CharacterMediaTitleModel.id))
                    .where(CharacterMediaTitleModel.media_title_id == row.id)
                )
                char_count = count_result.scalar() or 0
                titles.append(media_title_to_pydantic(row, character_count=char_count))
            return titles

    async def get_media_title(self, media_title_id: str) -> MediaTitle:
        """Get a single media title by ID."""
        async with get_session() as session:
            row = await session.get(MediaTitleModel, media_title_id)
            if not row:
                raise ValueError(f"Media title {media_title_id} not found")

            count_result = await session.execute(
                select(sql_func.count(CharacterMediaTitleModel.id))
                .where(CharacterMediaTitleModel.media_title_id == row.id)
            )
            char_count = count_result.scalar() or 0
            return media_title_to_pydantic(row, character_count=char_count)

    async def update_media_title(self, media_title_id: str, data: MediaTitleUpdate) -> MediaTitle:
        """Update a media title."""
        async with get_session() as session:
            row = await session.get(MediaTitleModel, media_title_id)
            if not row:
                raise ValueError(f"Media title {media_title_id} not found")

            update_data = data.model_dump(exclude_unset=True)
            for key, value in update_data.items():
                if key == "media_type" and hasattr(value, "value"):
                    value = value.value
                setattr(row, key, value)

            await session.commit()
            await session.refresh(row)
            return media_title_to_pydantic(row)

    async def delete_media_title(self, media_title_id: str) -> None:
        """Delete a media title and all related data."""
        async with get_session() as session:
            row = await session.get(MediaTitleModel, media_title_id)
            if not row:
                raise ValueError(f"Media title {media_title_id} not found")
            await session.delete(row)
            await session.commit()

    # -----------------------------------------------------------------------
    # Character-Media Linking
    # -----------------------------------------------------------------------

    async def link_character(self, data: CharacterMediaLinkCreate) -> CharacterMediaLink:
        """Link a character to a media title."""
        link_id = generate_id("cml")

        async with get_session() as session:
            # Verify both exist
            char = await session.get(CharacterModel, data.character_id)
            if not char:
                raise ValueError(f"Character {data.character_id} not found")
            media = await session.get(MediaTitleModel, data.media_title_id)
            if not media:
                raise ValueError(f"Media title {data.media_title_id} not found")

            try:
                row = CharacterMediaTitleModel(
                    id=link_id,
                    character_id=data.character_id,
                    media_title_id=data.media_title_id,
                    role_name=data.role_name,
                    role_type=data.role_type.value if hasattr(data.role_type, "value") else data.role_type,
                    actor_name=data.actor_name,
                    seasons_appeared=data.seasons_appeared or [],
                    notes=data.notes,
                )
                session.add(row)
                await session.commit()
                await session.refresh(row)

                return CharacterMediaLink(
                    id=row.id,
                    character_id=row.character_id,
                    media_title_id=row.media_title_id,
                    character_name=char.name,
                    media_title_name=media.title,
                    role_name=row.role_name,
                    role_type=row.role_type,
                    actor_name=row.actor_name,
                    seasons_appeared=row.seasons_appeared or [],
                    notes=row.notes,
                    created_at=row.created_at,
                )
            except IntegrityError:
                raise ValueError(f"Character {data.character_id} is already linked to {data.media_title_id}")

    async def unlink_character(self, media_title_id: str, character_id: str) -> None:
        """Unlink a character from a media title."""
        async with get_session() as session:
            result = await session.execute(
                select(CharacterMediaTitleModel).where(
                    CharacterMediaTitleModel.media_title_id == media_title_id,
                    CharacterMediaTitleModel.character_id == character_id,
                )
            )
            row = result.scalar_one_or_none()
            if not row:
                raise ValueError("Link not found")
            await session.delete(row)
            await session.commit()

    async def list_linked_characters(self, media_title_id: str) -> List[CharacterMediaLink]:
        """List characters linked to a media title.

        Sorted lead-first then alphabetically. Includes character image and
        media metadata so the UI can render rich cast cards from this single
        endpoint.
        """
        async with get_session() as session:
            result = await session.execute(
                select(CharacterMediaTitleModel)
                .where(CharacterMediaTitleModel.media_title_id == media_title_id)
            )
            rows = list(result.scalars().all())
            media = await session.get(MediaTitleModel, media_title_id)

            chars: Dict[str, CharacterModel] = {}
            for row in rows:
                if row.character_id not in chars:
                    c = await session.get(CharacterModel, row.character_id)
                    if c:
                        chars[row.character_id] = c

        role_rank = {"lead": 0, "supporting": 1, "recurring": 2, "guest": 3, "cameo": 4}
        rows.sort(key=lambda r: (
            role_rank.get((r.role_type or "supporting").lower(), 5),
            (chars.get(r.character_id).name if chars.get(r.character_id) else "").lower(),
        ))

        links: List[CharacterMediaLink] = []
        for row in rows:
            char = chars.get(row.character_id)
            links.append(CharacterMediaLink(
                id=row.id,
                character_id=row.character_id,
                media_title_id=row.media_title_id,
                character_name=char.name if char else None,
                media_title_name=media.title if media else None,
                role_name=row.role_name,
                role_type=row.role_type,
                actor_name=row.actor_name,
                seasons_appeared=row.seasons_appeared or [],
                notes=row.notes,
                created_at=row.created_at,
                character_image_url=getattr(char, "image_url", None) if char else None,
                character_status=getattr(char, "status", None) if char else None,
                media_type=getattr(media, "media_type", None) if media else None,
                media_year=getattr(media, "year", None) if media else None,
                media_poster_url=getattr(media, "poster_url", None) if media else None,
                media_franchise=getattr(media, "franchise", None) if media else None,
                media_universe=getattr(media, "universe", None) if media else None,
            ))
        return links

    async def list_media_for_character(self, character_id: str) -> List[CharacterMediaLink]:
        """List media titles linked to a character.

        Sorted by year descending so newest appearances surface first.
        """
        async with get_session() as session:
            result = await session.execute(
                select(CharacterMediaTitleModel)
                .where(CharacterMediaTitleModel.character_id == character_id)
            )
            rows = list(result.scalars().all())
            char = await session.get(CharacterModel, character_id) if rows else None

            medias: Dict[str, MediaTitleModel] = {}
            for row in rows:
                if row.media_title_id not in medias:
                    m = await session.get(MediaTitleModel, row.media_title_id)
                    if m:
                        medias[row.media_title_id] = m

        rows.sort(
            key=lambda r: (medias.get(r.media_title_id).year or 0)
            if medias.get(r.media_title_id) else 0,
            reverse=True,
        )

        links: List[CharacterMediaLink] = []
        for row in rows:
            media = medias.get(row.media_title_id)
            links.append(CharacterMediaLink(
                id=row.id,
                character_id=row.character_id,
                media_title_id=row.media_title_id,
                character_name=char.name if char else None,
                media_title_name=media.title if media else None,
                role_name=row.role_name,
                role_type=row.role_type,
                actor_name=row.actor_name,
                seasons_appeared=row.seasons_appeared or [],
                notes=row.notes,
                created_at=row.created_at,
                character_image_url=getattr(char, "image_url", None) if char else None,
                character_status=getattr(char, "status", None) if char else None,
                media_type=getattr(media, "media_type", None) if media else None,
                media_year=getattr(media, "year", None) if media else None,
                media_poster_url=getattr(media, "poster_url", None) if media else None,
                media_franchise=getattr(media, "franchise", None) if media else None,
                media_universe=getattr(media, "universe", None) if media else None,
            ))
        return links

    # -----------------------------------------------------------------------
    # Research Pipeline
    # -----------------------------------------------------------------------

    async def research_media_title(self, media_title_id: str) -> MediaTitle:
        """Run the research pipeline for a media title."""
        async with get_session() as session:
            row = await session.get(MediaTitleModel, media_title_id)
            if not row:
                raise ValueError(f"Media title {media_title_id} not found")

            row.research_status = "researching"
            await session.commit()

        try:
            fragments = await self._research_service.research_title(
                title=row.title,
                media_type=row.media_type,
                year=row.year,
                franchise=row.franchise,
                tmdb_id=row.tmdb_id,
            )

            # Synthesize facts from fragments using LLM
            fact_bank = await self._synthesize_facts(row.title, row.media_type, fragments)

            # Source images
            images = []
            if row.tmdb_id:
                images = await self._research_service.get_tmdb_images(row.tmdb_id, row.media_type)

            async with get_session() as session:
                row = await session.get(MediaTitleModel, media_title_id)
                row.fact_bank = fact_bank
                row.research_data = {
                    "fragments_count": len(fragments),
                    "sources": list(set(f.source for f in fragments)),
                    "researched_at": datetime.now(timezone.utc).isoformat(),
                }
                row.research_sources = list(set(f.source for f in fragments))
                row.research_status = "completed"
                row.research_depth_score = min(len(fact_bank) / 30 * 100, 100)
                row.last_researched = datetime.now(timezone.utc)

                # Save research fragments
                for frag in fragments[:50]:
                    frag_row = MediaResearchFragmentModel(
                        id=generate_id("mrf"),
                        media_title_id=media_title_id,
                        source=frag.source,
                        content=frag.content,
                        url=frag.url,
                        relevance_score=frag.relevance_score,
                        fragment_type=frag.fragment_type,
                    )
                    session.add(frag_row)

                # Save images
                for img_data in images[:15]:
                    try:
                        img_row = MediaImageModel(
                            id=generate_id("mi"),
                            media_title_id=media_title_id,
                            url=img_data["url"],
                            source="tmdb",
                            width=img_data.get("width"),
                            height=img_data.get("height"),
                        )
                        session.add(img_row)
                    except Exception:
                        pass  # Skip duplicate URLs

                # Set poster/backdrop from TMDB images
                posters = [i for i in images if i.get("type") == "poster"]
                backdrops = [i for i in images if i.get("type") == "backdrop"]
                if posters and not row.poster_url:
                    row.poster_url = posters[0]["url"]
                if backdrops and not row.backdrop_url:
                    row.backdrop_url = backdrops[0]["url"]

                await session.commit()
                await session.refresh(row)
                pydantic_result = media_title_to_pydantic(row)

            # Fire-and-forget cast sync so research return latency stays low.
            try:
                from app.services.media_cast_sync_service import (
                    get_media_cast_sync_service,
                )
                cast_svc = get_media_cast_sync_service()
                if cast_svc.is_configured:
                    asyncio.create_task(
                        cast_svc.sync_cast_for_title(media_title_id)
                    )
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "cast_sync_dispatch_failed",
                    media_title_id=media_title_id, error=str(e)[:200],
                )

            return pydantic_result

        except Exception as e:
            logger.error("media_research_failed", media_title_id=media_title_id, error=str(e))
            async with get_session() as session:
                row = await session.get(MediaTitleModel, media_title_id)
                if row:
                    row.research_status = "failed"
                    row.research_data = {"error": str(e)}
                    await session.commit()
            raise

    async def _synthesize_facts(
        self,
        title: str,
        media_type: str,
        fragments: list,
    ) -> List[Dict[str, Any]]:
        """Use LLM to synthesize research fragments into structured facts."""
        if not fragments:
            return []

        # Combine fragment contents
        combined = "\n\n".join([
            f"[{f.source} - {f.fragment_type}] {f.content}"
            for f in fragments[:30]
        ])

        media_label = "TV show" if media_type == "tv_show" else "movie"

        prompt = f"""Analyze these research fragments about the {media_label} "{title}" and extract 15-25 structured facts.

Each fact should be:
- Specific, surprising, and verifiable
- NOT obvious plot summary (fans already know the plot)
- Behind-the-scenes info, production details, cast facts, or little-known trivia preferred
- Suitable for viral TikTok carousel content

Return ONLY valid JSON array:
[
  {{
    "fact": "the actual fact text",
    "category": "production|cast|trivia|behind_scenes|plot|review|fan_theory|cultural_impact",
    "surprise_score": 0.1-1.0,
    "source": "which source this came from"
  }}
]

Research fragments:
{combined}

/no_think"""

        try:
            from app.infrastructure.ollama_client import get_llm_client
            ollama = get_llm_client()
            content = await ollama.chat(
                prompt=prompt,
                system="You are a research analyst specializing in TV and movie trivia. Extract structured facts from research data. Return ONLY valid JSON array, no explanation.",
                task_type="media_research_synthesis",
                temperature=0.2,
                num_predict=16384,
                timeout=900,
                max_retries=1,
            )

            facts = parse_json_response(content or "", context="media_fact_synthesis")
            if isinstance(facts, list):
                return facts[:25]
        except Exception as e:
            logger.warning("media_fact_synthesis_error", error=str(e), title=title)

        return []

    # -----------------------------------------------------------------------
    # Carousel Generation
    # -----------------------------------------------------------------------

    async def generate_carousel(self, data: MediaCarouselCreate) -> CharacterCarousel:
        """Generate a carousel for a media title."""
        async with get_session() as session:
            media = await session.get(MediaTitleModel, data.media_title_id)
            if not media:
                raise ValueError(f"Media title {data.media_title_id} not found")

            # Get facts filtered by angle categories
            fact_bank = media.fact_bank or []
            angle_value = data.angle.value if hasattr(data.angle, "value") else data.angle
            categories = MEDIA_ANGLE_CATEGORIES.get(angle_value, [])
            if categories:
                relevant_facts = [
                    f for f in fact_bank
                    if f.get("category") in categories or f.get("surprise_score", 0) > 0.7
                ]
            else:
                relevant_facts = fact_bank

            # Use top facts by surprise score
            relevant_facts.sort(key=lambda f: f.get("surprise_score", 0), reverse=True)
            top_facts = relevant_facts[:15] if relevant_facts else fact_bank[:15]

            if not top_facts:
                raise ValueError(f"No facts available for {media.title}. Research first.")

            # Get linked character context if specified
            char_context = ""
            if data.character_id:
                char = await session.get(CharacterModel, data.character_id)
                if char:
                    char_context = f"\nFocus on the character: {char.name}"
                    if char.fact_bank:
                        char_facts = [f.get("fact", "") for f in (char.fact_bank or [])[:5]]
                        char_context += f"\nCharacter facts: {'; '.join(char_facts)}"

            # Get media images for slide assignment
            img_result = await session.execute(
                select(MediaImageModel)
                .where(MediaImageModel.media_title_id == data.media_title_id)
                .where(MediaImageModel.is_valid == True)
                .order_by(MediaImageModel.usage_count.asc())
                .limit(20)
            )
            available_images = img_result.scalars().all()

        # Build generation prompt
        media_label = "TV show" if media.media_type == "tv_show" else "movie"
        facts_text = "\n".join([
            f"- {f.get('fact', '')} (category: {f.get('category', 'unknown')}, surprise: {f.get('surprise_score', 0):.1f})"
            for f in top_facts
        ])

        hook_instruction = ""
        if data.hook_style:
            hook_instruction = f"\nUse hook style: {data.hook_style}"

        format_instruction = ""
        if data.content_format:
            format_instruction = f"\nContent format: {data.content_format}"

        prompt = f"""Create a viral TikTok carousel about the {media_label} "{media.title}" ({media.year or 'N/A'}).

Angle: {angle_value.replace('_', ' ').title()}
Slide count: {data.slide_count}
{hook_instruction}
{format_instruction}
{char_context}

Available facts:
{facts_text}

Generate a {data.slide_count}-slide carousel that would go viral on TikTok.
The hook must be specific to this {media_label} and create an immediate curiosity gap.
Use the most surprising facts. Each slide should reveal something most viewers don't know."""

        try:
            from app.infrastructure.unified_llm_client import get_unified_llm_client
            llm = get_unified_llm_client()
            # ``UnifiedLLMClient.chat`` accepts ``system=``, NOT ``system_prompt=``.
            # The previous kwarg was silently swallowed by ``**kwargs``, which
            # meant the JSON-output instructions in MEDIA_CAROUSEL_SYSTEM_PROMPT
            # never reached the model — so every mc-* carousel produced the
            # generic "What if I told you..." template hook with zero slides.
            response = await llm.chat(
                messages=[{"role": "user", "content": prompt}],
                task_type="media_carousel_generation",
                system=MEDIA_CAROUSEL_SYSTEM_PROMPT,
                json_mode=True,
            )

            content = response.get("content", "") if isinstance(response, dict) else str(response)
            carousel_data = parse_json_response(content, context="media_carousel_gen")

            if not isinstance(carousel_data, dict):
                raise ValueError("LLM did not return valid carousel JSON")

            if not carousel_data.get("slides"):
                # Defense in depth — even with the system prompt restored, an
                # LLM hiccup could return a dict without slides. Don't save a
                # row that would render as the broken-template hook the user
                # has been seeing.
                raise ValueError(
                    f"LLM returned no slides for '{media.title}' "
                    f"(angle={angle_value}). Refusing to save empty carousel."
                )

        except Exception as e:
            logger.error("media_carousel_generation_failed", error=str(e), title=media.title)
            raise

        # Assign images to slides
        slides = carousel_data.get("slides", [])
        for slide in slides:
            if slide.get("text"):
                slide["text"] = sanitize_text(slide["text"], preserve_emphasis=True)
        for i, slide in enumerate(slides):
            if available_images and i < len(available_images):
                img = available_images[i]
                slide["image_url"] = img.url
                # Increment usage count
                async with get_session() as session:
                    db_img = await session.get(MediaImageModel, img.id)
                    if db_img:
                        db_img.usage_count = (db_img.usage_count or 0) + 1
                        await session.commit()

        # Save carousel
        carousel_id = generate_id("mc")
        async with get_session() as session:
            carousel_row = CharacterCarouselModel(
                id=carousel_id,
                character_id=data.character_id,  # nullable
                content_type="media",
                media_title_id=data.media_title_id,
                angle=angle_value,
                title=sanitize_text(carousel_data.get("title", "")),
                hook_text=sanitize_text(carousel_data.get("hook_text", ""), preserve_emphasis=True),
                slides=slides,
                caption=sanitize_text(carousel_data.get("caption", "")),
                hashtags=carousel_data.get("hashtags", []),
                music_mood=carousel_data.get("music_mood", "dramatic"),
                status="draft",
                story_template=data.story_template,
                hook_style=data.hook_style,
                content_format=data.content_format,
                generation_metadata={
                    "media_title": media.title,
                    "media_type": media.media_type,
                    "angle": angle_value,
                    "facts_used": len(top_facts),
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            session.add(carousel_row)

            # Increment carousel count on media title
            media_row = await session.get(MediaTitleModel, data.media_title_id)
            if media_row:
                media_row.carousels_created = (media_row.carousels_created or 0) + 1

            await session.commit()
            await session.refresh(carousel_row)

            carousel = carousel_to_pydantic(carousel_row)
            carousel.media_title_name = media.title
            return carousel

    # -----------------------------------------------------------------------
    # Carousel Listing
    # -----------------------------------------------------------------------

    async def list_carousels(
        self,
        media_title_id: Optional[str] = None,
        status: Optional[str] = None,
        angle: Optional[str] = None,
        limit: int = 50,
    ) -> List[CharacterCarousel]:
        """List carousels for media content."""
        async with get_session() as session:
            query = (
                select(CharacterCarouselModel)
                .where(CharacterCarouselModel.content_type == "media")
                .order_by(CharacterCarouselModel.created_at.desc())
                .limit(limit)
            )
            if media_title_id:
                query = query.where(CharacterCarouselModel.media_title_id == media_title_id)
            if status:
                query = query.where(CharacterCarouselModel.status == status)
            if angle:
                query = query.where(CharacterCarouselModel.angle == angle)

            result = await session.execute(query)
            carousels = []
            for row in result.scalars().all():
                char_name = None
                if row.character_id:
                    char = await session.get(CharacterModel, row.character_id)
                    char_name = char.name if char else None

                carousel = carousel_to_pydantic(row, char_name)

                # Populate media title name
                if row.media_title_id:
                    media = await session.get(MediaTitleModel, row.media_title_id)
                    if media:
                        carousel.media_title_name = media.title

                carousels.append(carousel)
            return carousels

    # -----------------------------------------------------------------------
    # Stats
    # -----------------------------------------------------------------------

    async def get_stats(self) -> MediaStats:
        """Get media content statistics."""
        async with get_session() as session:
            # Total counts
            total = await session.execute(
                select(sql_func.count(MediaTitleModel.id))
            )
            total_count = total.scalar() or 0

            tv_count_r = await session.execute(
                select(sql_func.count(MediaTitleModel.id))
                .where(MediaTitleModel.media_type == "tv_show")
            )
            tv_count = tv_count_r.scalar() or 0

            movie_count_r = await session.execute(
                select(sql_func.count(MediaTitleModel.id))
                .where(MediaTitleModel.media_type == "movie")
            )
            movie_count = movie_count_r.scalar() or 0

            researched_r = await session.execute(
                select(sql_func.count(MediaTitleModel.id))
                .where(MediaTitleModel.research_status == "completed")
            )
            researched = researched_r.scalar() or 0

            # Carousel stats
            carousel_total = await session.execute(
                select(sql_func.count(CharacterCarouselModel.id))
                .where(CharacterCarouselModel.content_type == "media")
            )
            total_carousels = carousel_total.scalar() or 0

            # Status breakdown
            status_result = await session.execute(
                select(
                    CharacterCarouselModel.status,
                    sql_func.count(CharacterCarouselModel.id),
                )
                .where(CharacterCarouselModel.content_type == "media")
                .group_by(CharacterCarouselModel.status)
            )
            carousels_by_status = {s: c for s, c in status_result.all()}

            return MediaStats(
                total_titles=total_count,
                tv_shows=tv_count,
                movies=movie_count,
                titles_researched=researched,
                total_carousels=total_carousels,
                carousels_by_status=carousels_by_status,
            )

    # -----------------------------------------------------------------------
    # TMDB Search
    # -----------------------------------------------------------------------

    async def search_tmdb(self, query: str, media_type: Optional[str] = None) -> List[TMDBSearchResult]:
        """Search TMDB for titles to import."""
        results = await self._research_service.search_tmdb_titles(query, media_type)

        # Check which are already imported
        tmdb_ids = [r["tmdb_id"] for r in results if r.get("tmdb_id")]
        already_imported = set()
        if tmdb_ids:
            async with get_session() as session:
                existing = await session.execute(
                    select(MediaTitleModel.tmdb_id)
                    .where(MediaTitleModel.tmdb_id.in_(tmdb_ids))
                )
                already_imported = {r for r in existing.scalars().all()}

        return [
            TMDBSearchResult(
                tmdb_id=r["tmdb_id"],
                title=r["title"],
                media_type=r["media_type"],
                year=r.get("year"),
                overview=r.get("overview"),
                poster_url=r.get("poster_url"),
                vote_average=r.get("vote_average"),
                already_imported=r["tmdb_id"] in already_imported,
            )
            for r in results
        ]

    # -----------------------------------------------------------------------
    # Image Management
    # -----------------------------------------------------------------------

    async def list_images(self, media_title_id: str) -> List[MediaImage]:
        """List images for a media title."""
        async with get_session() as session:
            result = await session.execute(
                select(MediaImageModel)
                .where(MediaImageModel.media_title_id == media_title_id)
                .order_by(MediaImageModel.created_at.desc())
            )
            return [media_image_to_pydantic(row) for row in result.scalars().all()]

    async def add_image(self, data: MediaImageCreate) -> MediaImage:
        """Add an image to a media title."""
        img_id = generate_id("mi")
        async with get_session() as session:
            row = MediaImageModel(
                id=img_id,
                media_title_id=data.media_title_id,
                url=data.url,
                source=data.source,
                is_primary=data.is_primary,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return media_image_to_pydantic(row)

    async def delete_image(self, media_title_id: str, image_id: str) -> None:
        """Delete an image."""
        async with get_session() as session:
            row = await session.get(MediaImageModel, image_id)
            if not row or row.media_title_id != media_title_id:
                raise ValueError("Image not found")
            await session.delete(row)
            await session.commit()

    # -----------------------------------------------------------------------
    # Seed (import from TMDB trending/popular)
    # -----------------------------------------------------------------------

    async def seed_from_tmdb(self, count: int = 10, media_type: str = "movie") -> List[MediaTitle]:
        """Import popular titles from TMDB."""
        api_key = getattr(self._settings, "TMDB_API_KEY", None) or getattr(self._settings, "ZERO_TMDB_API_KEY", None)
        if not api_key:
            raise ValueError("TMDB_API_KEY not configured")

        import aiohttp
        base_url = "https://api.themoviedb.org/3"
        headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}

        titles = []
        try:
            async with aiohttp.ClientSession() as session:
                endpoint = "tv/popular" if media_type == "tv_show" else "movie/popular"
                async with session.get(f"{base_url}/{endpoint}", headers=headers, params={"language": "en-US", "page": 1}, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        for item in (data.get("results") or [])[:count]:
                            title_key = "name" if media_type == "tv_show" else "title"
                            date_key = "first_air_date" if media_type == "tv_show" else "release_date"
                            poster = item.get("poster_path", "")

                            try:
                                created = await self.create_media_title(MediaTitleCreate(
                                    title=item.get(title_key, ""),
                                    media_type=media_type,
                                    year=int(item.get(date_key, "0000")[:4]) if item.get(date_key) else None,
                                    synopsis=item.get("overview", ""),
                                    tmdb_id=item.get("id"),
                                ))
                                # Set poster URL
                                if poster:
                                    await self.update_media_title(created.id, MediaTitleUpdate(
                                        # Can't set poster_url via update, so do it directly
                                    ))
                                    async with get_session() as db_session:
                                        row = await db_session.get(MediaTitleModel, created.id)
                                        if row:
                                            row.poster_url = f"https://image.tmdb.org/t/p/w500{poster}"
                                            await db_session.commit()
                                            created.poster_url = row.poster_url

                                titles.append(created)
                            except ValueError:
                                pass  # Already exists
        except Exception as e:
            logger.warning("tmdb_seed_error", error=str(e))

        return titles


def _guard_content_production_method(method_name: str):
    original = getattr(MediaContentService, method_name, None)
    if original is None:
        return

    @wraps(original)
    async def guarded(self, *args, **kwargs):
        from app.services.content_production_control_service import (
            ensure_content_production_allowed,
        )

        await ensure_content_production_allowed(f"media_content.{method_name}")
        return await original(self, *args, **kwargs)

    setattr(MediaContentService, method_name, guarded)


for _method_name in (
    "create_media_title",
    "update_media_title",
    "delete_media_title",
    "research_media_title",
    "generate_carousel",
    "link_character",
    "unlink_character",
    "add_image",
    "delete_image",
    "seed_from_tmdb",
):
    _guard_content_production_method(_method_name)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

@lru_cache()
def get_media_content_service() -> MediaContentService:
    return MediaContentService()
