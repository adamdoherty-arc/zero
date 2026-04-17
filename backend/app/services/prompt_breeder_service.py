"""Prompt Breeder Service (Phase 3a of Content Brain v2).

Genetic-algorithm-style evolution of prompt_variants:
  1. Per task_type, pick top-3 active variants by avg_score (min 20 runs each)
  2. Ask Kimi to produce 2 mutations per parent (structural + tone variation)
  3. Mark children generation=parent.generation+1, is_active=true, total_uses=0
  4. Retire bottom-3 active variants (is_active=false, never delete)

Inspired by PromptBreeder (https://arxiv.org/abs/2309.16797) mutator pattern.
"""

from __future__ import annotations

import json
import re
import uuid
from functools import lru_cache
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import select, and_

from app.db.models import PromptVariantModel
from app.infrastructure.database import get_session
from app.infrastructure.unified_llm_client import get_unified_llm_client

logger = structlog.get_logger(__name__)


MIN_RUNS_TO_RETIRE = 20
TOP_K_TO_BREED = 3
BOTTOM_K_TO_RETIRE = 3
MUTATIONS_PER_PARENT = 2


MUTATION_INSTRUCTIONS = [
    "Rewrite this prompt with sharper, more specific directives. Tighten each sentence. "
    "Replace vague phrases with concrete criteria. Keep the same variables and format.",
    "Rewrite this prompt with a bolder, more opinionated tone. Push for creative risk-taking. "
    "Encourage surprising angles. Keep the same variables and format.",
    "Rewrite this prompt with tighter structure: add numbered steps for the model to follow. "
    "Make output format explicit. Keep the same variables and format.",
    "Rewrite this prompt with more audience-aware language focused on 18-25 pop-culture fans. "
    "Emphasize hooks, payoffs, and emotional specificity. Keep the same variables and format.",
]


class PromptBreederService:
    def __init__(self) -> None:
        self._llm = get_unified_llm_client()

    async def _mutate(self, parent_template: str, style_hint: str) -> Optional[str]:
        try:
            raw = await self._llm.chat(
                prompt=(
                    f"{style_hint}\n\n"
                    f"Original prompt:\n---\n{parent_template[:4000]}\n---\n\n"
                    "Return ONLY the rewritten prompt — no explanations, no headers. "
                    "Preserve any {variable} placeholders exactly."
                ),
                system="You are a prompt engineer. Return only the rewritten prompt, no commentary.",
                task_type="classification",
                temperature=0.7,
                max_tokens=1800,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("prompt_mutation_failed", error=str(e)[:200])
            return None

        cleaned = raw.strip()
        # Strip any wrapping code fences
        cleaned = re.sub(r"^```[a-z]*\n", "", cleaned)
        cleaned = re.sub(r"\n```$", "", cleaned)
        if len(cleaned) < 50:
            return None
        return cleaned[:8000]

    async def breed_task_type(self, task_type: str) -> Dict[str, Any]:
        """Breed the top performers + retire the bottom. Returns summary."""
        async with get_session() as session:
            top_res = await session.execute(
                select(PromptVariantModel)
                .where(
                    PromptVariantModel.task_type == task_type,
                    PromptVariantModel.is_active.is_(True),
                )
                .order_by(PromptVariantModel.avg_score.desc())
                .limit(TOP_K_TO_BREED)
            )
            parents = list(top_res.scalars().all())

            bottom_res = await session.execute(
                select(PromptVariantModel)
                .where(
                    PromptVariantModel.task_type == task_type,
                    PromptVariantModel.is_active.is_(True),
                    PromptVariantModel.total_uses >= MIN_RUNS_TO_RETIRE,
                )
                .order_by(PromptVariantModel.avg_score.asc())
                .limit(BOTTOM_K_TO_RETIRE)
            )
            to_retire = list(bottom_res.scalars().all())

        if not parents:
            return {"task_type": task_type, "children_created": 0, "retired": 0, "reason": "no_parents"}

        children_created = 0
        for parent in parents:
            for i in range(MUTATIONS_PER_PARENT):
                hint = MUTATION_INSTRUCTIONS[i % len(MUTATION_INSTRUCTIONS)]
                mutated = await self._mutate(parent.prompt_template, hint)
                if mutated is None or mutated.strip() == parent.prompt_template.strip():
                    continue
                child_id = f"var-{uuid.uuid4().hex[:12]}"
                async with get_session() as session:
                    child = PromptVariantModel(
                        id=child_id,
                        task_type=task_type,
                        variant_name=f"{parent.variant_name[:60]}#gen{(parent.generation or 1)+1}.{i+1}",
                        prompt_template=mutated,
                        parameters=dict(parent.parameters or {}),
                        success_count=0,
                        failure_count=0,
                        total_uses=0,
                        avg_score=50.0,
                        is_active=True,
                        is_baseline=False,
                        parent_id=parent.id,
                        generation=(parent.generation or 1) + 1,
                    )
                    session.add(child)
                    await session.commit()
                children_created += 1

        # Retire bottom (do not include the parents we just bred from)
        retired = 0
        parent_ids = {p.id for p in parents}
        async with get_session() as session:
            for row in to_retire:
                if row.id in parent_ids:
                    continue
                # re-read fresh from this session so we can mutate safely
                fresh = await session.get(PromptVariantModel, row.id)
                if fresh is None or not fresh.is_active:
                    continue
                fresh.is_active = False
                retired += 1
            await session.commit()

        logger.info(
            "prompt_breeder_done",
            task_type=task_type,
            children_created=children_created,
            retired=retired,
            parents=[p.id for p in parents],
        )
        return {
            "task_type": task_type,
            "children_created": children_created,
            "retired": retired,
            "parents": [p.id for p in parents],
        }

    async def breed_all(self, task_types: Optional[List[str]] = None) -> Dict[str, Any]:
        if task_types is None:
            async with get_session() as session:
                res = await session.execute(
                    select(PromptVariantModel.task_type).distinct()
                )
                task_types = [r[0] for r in res.all()]
        results = []
        for tt in task_types:
            results.append(await self.breed_task_type(tt))
        return {"results": results}


@lru_cache()
def get_prompt_breeder_service() -> PromptBreederService:
    return PromptBreederService()
