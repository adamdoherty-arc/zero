"""Designer activity — drafts the carousel text from atomic facts + voice file.

Phase 4 implementation: calls the unified LLM router with the property's
voice-file system prompt + Tree-of-Thoughts hook generation (N=5 candidates,
hook judge picks top 1). Reflections from prior passes are injected.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import structlog
from temporalio import activity

logger = structlog.get_logger(__name__)


HOOK_SYSTEM = (
    "You write 8-second-stop carousel hooks. ≤12 words. Concrete subject. "
    "Curiosity gap or contradiction. No 'you won't believe...'. Return JSON."
)

DESIGNER_SYSTEM = (
    "You write a carousel as a JSON array of slides. Each slide has fields: "
    "slide_num, role (hook|setup|build|pivot|reveal|payoff|connection|cta), "
    "text (≤22 words), transition_to_next (cliffhanger phrase), cited_fact_ids "
    "(list of fact ids referenced). Every claim ends with [fact_id:N]. "
    "Strict adherence to the property voice file is mandatory."
)


async def _generate_hook_candidates(*, topic: str, franchise: str | None, voice_prompt: str, n: int = 5) -> list[str]:
    from app.infrastructure.unified_llm_client import UnifiedLLMClient

    client = UnifiedLLMClient()

    async def _one() -> str | None:
        try:
            result = await client.structured_chat(
                f"Topic: {topic}\nFranchise: {franchise or 'general'}\nReturn JSON: {{\"hook\": string ≤12 words}}",
                system=f"{HOOK_SYSTEM}\n\n{voice_prompt}",
                output_schema={"hook": "string"},
                task_type="hook_writer",
                temperature=0.9,
                max_tokens=120,
            )
            if isinstance(result, dict) and result.get("hook"):
                return str(result["hook"]).strip()
        except Exception as exc:  # noqa: BLE001
            logger.debug("hook_candidate_failed", error=str(exc))
        return None

    raw = await asyncio.gather(*(_one() for _ in range(n)))
    return [h for h in raw if h]


async def _pick_hook(candidates: list[str], *, topic: str) -> str:
    if not candidates:
        return f"7 things you missed about {topic}"
    if len(candidates) == 1:
        return candidates[0]
    from app.infrastructure.unified_llm_client import UnifiedLLMClient
    try:
        client = UnifiedLLMClient()
        bullets = "\n".join(f"{i+1}. {h}" for i, h in enumerate(candidates))
        result = await client.structured_chat(
            f"Pick the strongest hook for '{topic}'. Score curiosity gap, specificity, scroll-stop power.\n\n{bullets}",
            output_schema={"index": 1},
            task_type="hook_judge",
            temperature=0.0,
            max_tokens=80,
        )
        idx = int(result.get("index", 1)) - 1 if isinstance(result, dict) else 0
        idx = max(0, min(idx, len(candidates) - 1))
        return candidates[idx]
    except Exception:  # noqa: BLE001
        return candidates[0]


@activity.defn
async def design_carousel(ctx: dict[str, Any]) -> dict[str, Any]:
    activity.heartbeat({"stage": "design", "generation_id": ctx["generation_id"]})

    from app.infrastructure.unified_llm_client import UnifiedLLMClient
    from app.services.carousel_v2.atomic_facts_service import lookup_ids
    from app.services.carousel_v2.reflexion_service import render_for_designer
    from app.services.carousel_v2.voice_loader import compose_system_prompt

    voice_key = ctx.get("voice_file") or (ctx.get("franchise") or "mcu").lower().replace(" ", "_")
    voice_prompt = compose_system_prompt(voice_key)

    fact_ids = ctx.get("atomic_fact_ids", []) or []
    facts = await lookup_ids(fact_ids[:30])
    fact_block = "\n".join(
        f"  fact_id:{f.id} (tier {int(f.trust_tier)}) {f.subject} {f.predicate} {f.object[:200]}"
        for f in facts
    ) or "  (no atomic facts retrieved — be conservative)"

    # Hook ToT
    hook_candidates = await _generate_hook_candidates(
        topic=ctx["topic"], franchise=ctx.get("franchise"), voice_prompt=voice_prompt
    )
    hook = await _pick_hook(hook_candidates, topic=ctx["topic"])

    reflections = ctx.get("reflections", []) or []
    reflection_block = render_for_designer(reflections)

    slides_prompt = (
        f"TOPIC: {ctx['topic']}\n"
        f"FRANCHISE: {ctx.get('franchise') or 'general'}\n"
        f"HOOK (use as slide 1 verbatim): {hook}\n"
        f"FACT LEDGER:\n{fact_block}\n\n"
        f"{reflection_block}\n\n"
        f"Write {ctx.get('input', {}).get('slide_count', 8)} slides. "
        "Slide 1 is the hook (already written). Every other slide has exactly one claim "
        "ending with [fact_id:N]. End each slide except the last with a cliffhanger transition."
    )

    try:
        client = UnifiedLLMClient()
        result = await client.structured_chat(
            slides_prompt,
            system=f"{DESIGNER_SYSTEM}\n\n{voice_prompt}",
            output_schema=[{
                "slide_num": 1,
                "role": "hook|setup|build|pivot|reveal|payoff|connection|cta",
                "text": "string",
                "transition_to_next": "string|null",
                "cited_fact_ids": ["string"],
            }],
            task_type="designer",
            temperature=0.4,
            max_tokens=2048,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("designer_call_failed", error=str(exc))
        result = []

    slides = result if isinstance(result, list) else result.get("slides", []) if isinstance(result, dict) else []
    # Ensure slide 1 carries the hook verbatim.
    if slides and isinstance(slides[0], dict):
        slides[0]["text"] = hook
        slides[0]["role"] = "hook"

    ctx["slides"] = slides
    ctx["hook_candidates"] = hook_candidates
    ctx["chosen_hook"] = hook
    ctx["voice_prompt"] = voice_prompt
    if "designer_prompt_id" not in ctx:
        ctx["designer_prompt_id"] = uuid.uuid4().hex
    return ctx
