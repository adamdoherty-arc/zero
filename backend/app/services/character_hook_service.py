"""Character Hook Service (Phase 024 Character Autopilot).

Scores hooks and regenerates weak ones (hook_strength < 6) before auto-approval
has a chance to evaluate.

Strategies:
  - pattern_interrupt: "What if I told you..."
  - specific_stat: "0.03 seconds. That's how long..."
  - contrarian: "Everyone's wrong about Batman's greatest fear..."
  - question: "Why does Thanos snap with his left hand? The answer will shock you."
  - list_tease: "#3 will change how you see Spider-Man forever."
"""

from __future__ import annotations

import asyncio
import json
import re
from functools import lru_cache
from typing import Any, Dict, List, Optional

import aiohttp
import structlog
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.db.models import CharacterCarouselModel, CharacterModel
from app.infrastructure.database import get_session

logger = structlog.get_logger(__name__)


HOOK_STRATEGIES = [
    "pattern_interrupt",
    "specific_stat",
    "contrarian",
    "question",
    "list_tease",
]


class CharacterHookService:
    """Score and regenerate weak hooks for character carousels."""

    async def score_hook(
        self,
        hook_text: str,
        slides: List[Dict[str, Any]],
        character_name: str,
    ) -> Dict[str, Any]:
        """Score a hook on 3 dimensions. Uses Ollama (free)."""
        from app.infrastructure.unified_llm_client import get_unified_llm_client
        client = get_unified_llm_client()

        slides_preview = "\n".join(
            f"  Slide {s.get('slide_num', i+1)}: {s.get('text', '')[:120]}"
            for i, s in enumerate(slides[:5])
        )
        prompt = f"""Score this TikTok carousel hook on 3 dimensions (1-10 each).

Character: {character_name}
Hook: "{hook_text}"

First 5 slides:
{slides_preview}

Return JSON:
{{
  "strength": <1-10>,
  "issues": [<list of specific problems>],
  "style_match": <1-10, does hook match slide content>,
  "why": "<one-sentence reason>"
}}
"""
        try:
            raw = await client.chat(
                prompt=prompt,
                system="You are a social media hook critic. Return only JSON.",
                task_type="character_hook_regen",
                temperature=0.1,
                max_tokens=400,
            )
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if not match:
                return {"strength": 5, "issues": ["parse_failed"], "style_match": 5}
            parsed = json.loads(match.group(0))
            return parsed
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, AttributeError, RuntimeError, TypeError, SQLAlchemyError) as e:
            logger.warning("hook_score_failed", error=str(e))
            return {"strength": 5, "issues": ["score_error"], "style_match": 5}

    async def regenerate_hook(
        self,
        carousel_id: str,
        strategy: str = "pattern_interrupt",
    ) -> Optional[str]:
        """Generate 5 candidates, rank, pick best, update carousel, re-run Stage 1 review."""
        from app.infrastructure.unified_llm_client import get_unified_llm_client
        from app.services.character_content_service import get_character_content_service

        async with get_session() as session:
            row = await session.get(CharacterCarouselModel, carousel_id)
            if not row:
                return None
            char = await session.get(CharacterModel, row.character_id)
            char_name = char.name if char else "this character"
            character_universe = char.universe if char else "unknown"
            slides = list(row.slides or [])
            old_hook = row.hook_text or ""
            angle = row.angle

        if strategy not in HOOK_STRATEGIES:
            strategy = "pattern_interrupt"

        slides_preview = "\n".join(
            f"  Slide {s.get('slide_num', i+1)}: {s.get('text', '')[:120]}"
            for i, s in enumerate(slides[:5])
        )
        strategy_guides = {
            "pattern_interrupt": 'Break expectations: "What if I told you..." or "Everything you know about X is wrong."',
            "specific_stat": "Lead with an oddly-specific number or time: '0.03 seconds', '37 appearances', '$1.2M'.",
            "contrarian": "Take the opposite of the common opinion. Challenge fandom consensus directly.",
            "question": "Ask a question whose answer is in the carousel. The question must feel urgent.",
            "list_tease": "Hint at a numbered list and tease a specific number: '#3 will change how you see X forever'.",
        }
        prompt = f"""Generate 5 TikTok carousel hook variants for a {character_universe} character.

Character: {char_name}
Angle: {angle}
Current (weak) hook: "{old_hook}"
Strategy: {strategy}. {strategy_guides[strategy]}

First 5 slides for context:
{slides_preview}

Rules:
- Max 12 words each.
- No emojis. No hashtags.
- Must pay off within the carousel (don't lie).
- Must work as on-screen text for TikTok.

Return JSON array of 5 strings only.
"""
        client = get_unified_llm_client()
        try:
            raw = await client.chat(
                prompt=prompt,
                system="You are a top-1% TikTok hook writer. Return only a JSON array of 5 strings.",
                task_type="character_hook_regen",
                temperature=0.9,
                max_tokens=600,
            )
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, AttributeError, RuntimeError, TypeError, SQLAlchemyError) as e:
            logger.warning("hook_regen_chat_failed", carousel_id=carousel_id, error=str(e))
            return None

        match = re.search(r"\[.*\]", raw, re.DOTALL)
        if not match:
            return None
        try:
            candidates = json.loads(match.group(0))
        except (ValueError, KeyError, AttributeError, TypeError):
            return None
        candidates = [c.strip() for c in candidates if isinstance(c, str) and c.strip()]
        if not candidates:
            return None

        # Score all candidates, pick best
        best_hook = candidates[0]
        best_score = 0.0
        best_meta: Dict[str, Any] = {}
        for cand in candidates[:5]:
            score = await self.score_hook(cand, slides, char_name)
            total = float(score.get("strength", 0)) + float(score.get("style_match", 0))
            if total > best_score:
                best_score = total
                best_hook = cand
                best_meta = score

        # Persist
        async with get_session() as session:
            row = await session.get(CharacterCarouselModel, carousel_id)
            if not row:
                return None
            metadata = dict(row.generation_metadata or {})
            prev_hooks = list(metadata.get("previous_hooks", []))
            prev_hooks.append({"text": old_hook, "replaced_by_strategy": strategy})
            metadata["previous_hooks"] = prev_hooks[-10:]  # cap history
            metadata["hook_regen_candidates"] = candidates
            metadata["hook_regen_score"] = best_meta
            row.hook_text = best_hook
            row.generation_metadata = metadata
            await session.commit()

        # Re-run Stage 1 AI review so hook_strength reflects the new hook
        try:
            svc = get_character_content_service()
            await svc.ai_review_carousel(carousel_id)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, AttributeError, RuntimeError, TypeError, SQLAlchemyError) as e:
            logger.warning("hook_regen_review_failed", carousel_id=carousel_id, error=str(e))

        logger.info(
            "hook_regenerated",
            carousel_id=carousel_id,
            strategy=strategy,
            old_hook=old_hook[:60],
            new_hook=best_hook[:60],
            score=best_score,
        )
        return best_hook

    async def audit_weak_hooks(
        self,
        threshold: float = 6.0,
        limit: int = 20,
    ) -> Dict[str, Any]:
        """Find draft/review carousels with weak hooks and regenerate them."""
        regenerated = 0
        scanned = 0
        async with get_session() as session:
            result = await session.execute(
                select(CharacterCarouselModel)
                .where(
                    CharacterCarouselModel.status.in_(["draft", "review", "pending_review", "ai_reviewed"]),
                    CharacterCarouselModel.ai_review.is_not(None),
                )
                .limit(limit * 3)
            )
            rows = list(result.scalars().all())

        weak_ids: List[str] = []
        for row in rows:
            scanned += 1
            review = row.ai_review or {}
            strength = review.get("hook_strength") if isinstance(review, dict) else None
            if isinstance(strength, (int, float)) and strength < threshold:
                weak_ids.append(row.id)
            if len(weak_ids) >= limit:
                break

        for cid in weak_ids:
            try:
                # Rotate strategies across runs using carousel id hash
                strategy = HOOK_STRATEGIES[hash(cid) % len(HOOK_STRATEGIES)]
                result = await self.regenerate_hook(cid, strategy=strategy)
                if result:
                    regenerated += 1
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, AttributeError, RuntimeError, TypeError, SQLAlchemyError) as e:
                logger.warning("hook_audit_regen_failed", carousel_id=cid, error=str(e))

        return {"scanned": scanned, "weak_found": len(weak_ids), "regenerated": regenerated}


@lru_cache()
def get_character_hook_service() -> CharacterHookService:
    return CharacterHookService()
