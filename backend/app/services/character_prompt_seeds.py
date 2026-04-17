"""Seed baseline prompt variants for the character content pipeline.

Registers the current hardcoded prompts as baseline PromptVariant rows so
that Thompson Sampling has a starting point and every subsequent call can
be tagged with a variant_id. Runs idempotently: only inserts when no
baseline variant exists for a given task_type.

The 4 seeded task types mirror the 4 LLM call sites in
character_content_service.py:
  - character_research_facts         (fact extraction from research)
  - character_carousel_generation    (carousel JSON generation)
  - character_content_review         (Stage 1 AI review)
  - character_content_review_final   (Stage 2 Minimax polish review)
"""

from __future__ import annotations

import structlog
from sqlalchemy.exc import SQLAlchemyError

from app.services.prompt_evolution_service import get_prompt_evolution_service

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Baseline prompt templates. These MUST match the text used in
# character_content_service.py on the day of seeding. When a template is
# mutated in code, add a NEW variant (is_baseline=False) rather than
# editing these strings in place, so history is preserved.
# ---------------------------------------------------------------------------

FACT_EXTRACTION_SYSTEM = (
    "You are a character research expert specializing in pop culture, comics, "
    "movies, and TV shows.\nAnalyze the provided search results and compile a "
    "comprehensive character profile.\nReturn ONLY valid JSON."
)

FACT_EXTRACTION_TEMPLATE = """Based on the research data below, compile a fact bank of 20-30 interesting facts about {name}.

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


CAROUSEL_SYSTEM = (
    "You are a viral TikTok content creator specializing in character "
    "development carousels.\nYour posts get 100K+ likes using this formula:\n"
    "- Slide 1: Provocative hook that stops the scroll\n"
    "- Slides 2-6: Numbered facts with bold, engaging text\n"
    "- Final slide: Engagement CTA\n- Caption: Emotional, debate-sparking, with emojis\n"
    "- Hashtags: character + franchise + niche tags\n\n"
    "CRITICAL: Never use em dashes, markdown asterisks, or any formatting markup. "
    "Plain text only.\n\nReturn ONLY valid JSON."
)

CAROUSEL_TEMPLATE = """Create a TikTok photo carousel about {name} ({universe}) with angle: {angle}.

Character facts available:
{facts_text}

Generate a {slide_count}-slide carousel. Return JSON:
{{
  "title": "Internal reference title",
  "hook_text": "Provocative hook for slide 1",
  "slides": [
    {{
      "slide_num": 1,
      "text": "Hook text displayed on the image",
      "image_query": "search query for the slide image"
    }}
  ],
  "caption": "TikTok caption with emojis, debate-sparking question",
  "hashtags": ["charactername", "franchise", "topicangle", "communitytag", "fyp", "viral", "didyouknow", "comicbooktok", "movietok", "learnontiktok", "geekculture", "nerdtok", "characteranalysis", "mindblown", "edutok"],
  "music_mood": "epic|dark|emotional|mysterious|dramatic"
}}

Style rules:
- Text overlays: Short punchy lines, 1-3 lines per slide. NO numbered lists.
- Use **word** to highlight 1-2 key words per slide (sparingly)
- Include dramatic pauses with "..."
- End text with impact words or emojis
- Caption should provoke comments

FORMATTING RULES (strict):
- NEVER use em dashes. Use periods, commas, or colons instead.
- Use **word** for emphasis on 1-2 key words per slide. Do NOT overuse.
- NEVER use parenthetical asides with dashes.
- Each slide: 1-3 SHORT lines. Never cram multiple facts into one slide."""


AI_REVIEW_SYSTEM = (
    "You are a TikTok content strategist reviewing carousel posts for viral potential.\n"
    "Score each dimension 1-10 and provide actionable feedback.\nReturn ONLY valid JSON."
)

AI_REVIEW_TEMPLATE = """Review this TikTok character carousel for viral potential:

Character: {name} ({universe})
Angle: {angle}
Hook: {hook_text}

Slides:
{slides_text}

Caption: {caption}
Hashtags: {hashtags}

Score each dimension 1-10:
{{
  "hook_strength": score,
  "fact_quality": score,
  "engagement_potential": score,
  "caption_quality": score,
  "overall_score": score,
  "suggestions": ["actionable improvement 1", "improvement 2"],
  "fact_check_flags": ["any facts that seem inaccurate"],
  "rewrite_hook": "optional: a better hook if score < 7",
  "rewrite_caption": "optional: a better caption if score < 7"
}}

CRITICAL: If you provide rewrite_hook or rewrite_caption, plain text only. No em dashes, no asterisks."""


FINAL_REVIEW_SYSTEM = (
    "You are a top-tier viral TikTok editor. You already know the carousel "
    "passed a first-pass review.\nYour job is the final polish: tighten the "
    "hook, sharpen the caption, validate fact sequencing, and protect the "
    "emotional arc.\nScore each viral-instinct dimension 1-10 with discipline. "
    "Be honest: a 10 is rare.\nReturn ONLY valid JSON. Never use em dashes, "
    "markdown asterisks, or formatting markup in polished text."
)

FINAL_REVIEW_TEMPLATE = """Final-stage viral review for this character carousel:

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
  "hook_tension": score,
  "fact_sequencing": score,
  "emotional_arc": score,
  "caption_cta": score,
  "overall_score": score,
  "verdict": "approve" | "revise" | "kill",
  "polish_suggestions": ["1-3 concrete fixes"],
  "final_hook": "optional: tightened hook only if clearly better",
  "final_caption": "optional: sharper caption only if clearly better"
}}

CRITICAL: final_hook and final_caption must be plain text. No em dashes, no asterisks."""


BASELINE_VARIANTS = [
    {
        "task_type": "character_research_facts",
        "variant_name": "baseline_v1",
        "prompt_template": FACT_EXTRACTION_TEMPLATE,
        "parameters": {
            "system_prompt": FACT_EXTRACTION_SYSTEM,
            "variables": ["name", "research_text"],
            "expected_output": "json_array_of_facts",
        },
    },
    {
        "task_type": "character_carousel_generation",
        "variant_name": "baseline_v1",
        "prompt_template": CAROUSEL_TEMPLATE,
        "parameters": {
            "system_prompt": CAROUSEL_SYSTEM,
            "variables": ["name", "universe", "angle", "facts_text", "slide_count"],
            "expected_output": "json_carousel_object",
        },
    },
    {
        "task_type": "character_content_review",
        "variant_name": "baseline_v1",
        "prompt_template": AI_REVIEW_TEMPLATE,
        "parameters": {
            "system_prompt": AI_REVIEW_SYSTEM,
            "variables": ["name", "universe", "angle", "hook_text", "slides_text", "caption", "hashtags"],
            "expected_output": "json_review_scores",
        },
    },
    {
        "task_type": "character_content_review_final",
        "variant_name": "baseline_v1",
        "prompt_template": FINAL_REVIEW_TEMPLATE,
        "parameters": {
            "system_prompt": FINAL_REVIEW_SYSTEM,
            "variables": ["name", "universe", "angle", "hook_text", "slides_text", "caption", "hashtags", "stage1_scores"],
            "expected_output": "json_final_review_scores",
        },
    },
]


async def seed_character_prompt_variants() -> dict:
    """Idempotently seed the 4 baseline variants. Returns a summary dict."""
    svc = get_prompt_evolution_service()
    inserted = 0
    skipped = 0
    errors = 0

    for spec in BASELINE_VARIANTS:
        task_type = spec["task_type"]
        try:
            existing = await svc.get_variants(task_type=task_type, active_only=False)
            has_baseline = any(v.is_baseline for v in existing)
            if has_baseline:
                skipped += 1
                continue

            await svc.register_variant(
                task_type=task_type,
                variant_name=spec["variant_name"],
                prompt_template=spec["prompt_template"],
                is_baseline=True,
                parameters=spec.get("parameters") or {},
            )
            inserted += 1
        except (SQLAlchemyError, ValueError, KeyError, AttributeError, TypeError, RuntimeError) as e:
            logger.warning("prompt_variant_seed_failed", task_type=task_type, error=str(e))
            errors += 1

    logger.info(
        "character_prompt_variants_seeded",
        inserted=inserted,
        skipped=skipped,
        errors=errors,
    )
    return {"inserted": inserted, "skipped": skipped, "errors": errors}
