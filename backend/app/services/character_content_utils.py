"""
Shared utilities for the character content pipeline.

Extracted from character_content_service.py to reduce single-file LOC.
Contains: text sanitization, JSON parsing/repair, ID generation, hook
diversity checking, and ORM-to-Pydantic converters.
"""

import json
import re
import uuid
from typing import Any, Dict, List, Optional

import structlog

from app.db.models import (
    CharacterModel, CharacterCarouselModel, CharacterImageModel,
    CharacterCarouselVersionModel,
)
from app.models.character_content import (
    Character, CharacterCarousel, CharacterImage, CarouselVersion,
)

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# ID generation
# ---------------------------------------------------------------------------

def generate_id(prefix: str = "ch") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Text sanitization
# ---------------------------------------------------------------------------

def sanitize_text(text: str) -> str:
    """Strip AI-generated formatting: em dashes, markdown asterisks, en dashes."""
    if not text:
        return text
    text = text.replace("\u2014", ". ")   # em dash
    text = text.replace("\u2013", "-")    # en dash -> hyphen
    text = re.sub(r'\*{1,3}([^*]+)\*{1,3}', r'\1', text)
    text = re.sub(r'\.\s*\.', '.', text)
    text = re.sub(r'\s{2,}', ' ', text)
    return text.strip()


# ---------------------------------------------------------------------------
# JSON parsing and repair
# ---------------------------------------------------------------------------

def parse_json_response(raw: str, context: str = "") -> Any:
    """Extract and parse JSON from LLM response text, handling truncation."""
    raw = raw.strip()
    # Strip <think>...</think> tags (qwen reasoning output)
    raw = re.sub(r'<think>[\s\S]*?</think>', '', raw).strip()

    # Try direct parse
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Markdown code fence
    json_match = re.search(r'```(?:json)?\s*\n?([\s\S]*?)\n?```', raw)
    if json_match:
        try:
            return json.loads(json_match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Find JSON object or array
    for pattern in [r'\{[\s\S]*\}', r'\[[\s\S]*\]']:
        match = re.search(pattern, raw)
        if match:
            candidate = match.group(0)
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass
            cleaned = re.sub(r',\s*([}\]])', r'\1', candidate)
            try:
                return json.loads(cleaned)
            except json.JSONDecodeError:
                pass

    # Truncated JSON repair
    json_start = -1
    for i, ch in enumerate(raw):
        if ch in ('{', '['):
            json_start = i
            break

    if json_start >= 0:
        json_str = raw[json_start:]
        result = repair_truncated_json(json_str)
        if result is not None:
            logger.info("json_repair_success", context=context)
            return result

    logger.warning("json_parse_failed", context=context, raw_length=len(raw), raw_preview=raw[:200])
    return {}


def repair_truncated_json(json_str: str) -> Any:
    """Attempt to repair truncated JSON by closing open brackets/braces."""
    in_string = False
    escape_next = False
    stack: List[str] = []

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
        elif ch == ']':
            if stack and stack[-1] == '[':
                stack.pop()

    if not stack:
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            pass

    trimmed = json_str.rstrip()
    if in_string:
        trimmed = trimmed + '"'

    trimmed = trimmed.rstrip(',').rstrip()
    closers = ""
    for bracket in reversed(stack):
        closers += '}' if bracket == '{' else ']'

    repair_attempt = trimmed + closers
    try:
        return json.loads(repair_attempt)
    except json.JSONDecodeError:
        pass
    return None


# ---------------------------------------------------------------------------
# Hook diversity
# ---------------------------------------------------------------------------

_BANNED_HOOK_PATTERNS = (
    r"^the hammer lie\b",
    r"^nobody talks about\b",
    r"^what they (don't|do not|never) (tell|told|want) you\b",
    r"^the truth (about|they hide)\b",
    r"^you (probably )?didn'?t know\b",
    r"^7 secrets? (about|they hide)\b",
)


def is_generic_hook(hook: str, character_name: Optional[str]) -> bool:
    """Return True if the hook is a reused template or fails the swap test."""
    if not hook:
        return True
    lowered = hook.strip().lower()
    normalized = re.sub(r'^[^a-z0-9]+', '', lowered)
    normalized = re.sub(r'\s{2,}', ' ', normalized).strip()
    for pat in _BANNED_HOOK_PATTERNS:
        if re.search(pat, lowered) or re.search(pat, normalized):
            return True
    if character_name:
        if character_name.lower() in lowered:
            return False
        first_name = character_name.split()[0].lower() if character_name else ""
        if first_name and first_name in lowered:
            return False
    words = hook.split()
    has_proper_noun = any(
        len(w) > 2 and w[0].isupper() and not w.isupper() for w in words[1:]
    )
    return not has_proper_noun


def rewrite_generic_hook(hook: str, character_name: str, result: dict) -> str:
    """Rewrite a banned/generic hook into something character-specific."""
    cleaned = hook.strip()
    for pat in _BANNED_HOOK_PATTERNS:
        cleaned = re.sub(pat, "", cleaned, flags=re.IGNORECASE).strip(" :.,-")
    if cleaned and len(cleaned) > 12:
        return f"{character_name}: {cleaned[0].upper() + cleaned[1:]}".rstrip(".")

    for slide in result.get("slides", [])[1:]:
        text = (slide.get("text") or "").strip()
        text = re.sub(r"^\d+\.\s*", "", text)
        if text and not is_generic_hook(text, character_name) and len(text) < 140:
            return text

    return f"{character_name}: the detail everyone misses."


def sanitize_carousel(result: dict, character_name: Optional[str] = None) -> dict:
    """Sanitize all text fields in a carousel result and rewrite generic hooks."""
    if result.get("title"):
        result["title"] = sanitize_text(result["title"])
    if result.get("hook_text"):
        result["hook_text"] = sanitize_text(result["hook_text"])
    if result.get("caption"):
        result["caption"] = sanitize_text(result["caption"])
    for slide in result.get("slides", []):
        if slide.get("text"):
            slide["text"] = sanitize_text(slide["text"])

    hook = result.get("hook_text") or ""
    if character_name and is_generic_hook(hook, character_name):
        rewritten = rewrite_generic_hook(hook, character_name, result)
        if rewritten and rewritten != hook:
            logger.info(
                "hook_rewritten_generic",
                character=character_name,
                old_hook=hook[:80],
                new_hook=rewritten[:80],
            )
            result["hook_text"] = rewritten
            slides = result.get("slides", [])
            if slides and is_generic_hook(slides[0].get("text", ""), character_name):
                slides[0]["text"] = rewritten
    return result


# ---------------------------------------------------------------------------
# ORM to Pydantic converters
# ---------------------------------------------------------------------------

def character_to_pydantic(row: CharacterModel, carousels_created: int = 0) -> Character:
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
        carousels_created=carousels_created,
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
        blocked_image_urls=row.blocked_image_urls or [],
    )


def carousel_to_pydantic(row: CharacterCarouselModel, character_name: Optional[str] = None) -> CharacterCarousel:
    slides = row.slides or []
    for slide in slides:
        if slide.get("text"):
            slide["text"] = sanitize_text(slide["text"])

    raw_hook = sanitize_text(row.hook_text) if row.hook_text else row.hook_text
    if raw_hook and character_name and is_generic_hook(raw_hook, character_name):
        rewritten = rewrite_generic_hook(raw_hook, character_name, {"slides": slides})
        if rewritten and rewritten != raw_hook:
            raw_hook = rewritten

    return CharacterCarousel(
        id=row.id,
        character_id=row.character_id,
        character_name=character_name,
        angle=row.angle,
        title=sanitize_text(row.title) if row.title else row.title,
        hook_text=raw_hook,
        slides=slides,
        caption=sanitize_text(row.caption) if row.caption else row.caption,
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
        hook_style=getattr(row, "hook_style", None),
        content_format=getattr(row, "content_format", None),
        publish_status=row.publish_status,
        publish_platform=row.publish_platform,
        download_urls=row.download_urls,
        watermark_applied=row.watermark_applied if row.watermark_applied is not None else False,
        final_review=row.final_review,
        final_review_score=row.final_review_score,
        final_review_model=row.final_review_model,
        auto_approved=getattr(row, "auto_approved", None),
        auto_approved_at=getattr(row, "auto_approved_at", None),
        auto_approve_reason=getattr(row, "auto_approve_reason", None),
        current_version_id=getattr(row, "current_version_id", None),
    )


def image_to_pydantic(row: CharacterImageModel) -> CharacterImage:
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
        quality_score=getattr(row, "quality_score", None) or 0.0,
        content_type=getattr(row, "content_type", None),
        file_size=getattr(row, "file_size", None),
        is_approved=getattr(row, "is_approved", None),
        feedback_reason=getattr(row, "feedback_reason", None),
        validated_at=getattr(row, "validated_at", None),
        created_at=row.created_at,
    )


def version_to_pydantic(row: CharacterCarouselVersionModel) -> CarouselVersion:
    return CarouselVersion(
        id=row.id,
        carousel_id=row.carousel_id,
        version_number=row.version_number,
        parent_version_id=row.parent_version_id,
        title=row.title,
        hook_text=row.hook_text,
        slides=row.slides or [],
        caption=row.caption,
        hashtags=row.hashtags or [],
        human_notes=row.human_notes,
        music_track=row.music_track,
        text_overlay_specs=row.text_overlay_specs or [],
        source=row.source,
        source_metadata=row.source_metadata or {},
        created_by=row.created_by,
        created_at=row.created_at,
    )
