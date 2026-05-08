"""3-judge rubric panel with Bradley-Terry weighted aggregation.

Per carosel.txt §5 'Cross-family judge jury':

  Kimi K2.6     → fact_accuracy, narrative_arc        (strong reasoning)
  MiniMax M2.7  → hook_strength, design_polish        (cheap, fast)
  Qwen3-32B     → image_relevance, voice, novelty     (Prometheus-Eval)

Self-consistency: n=3 samples per judge at temp=0.3, take median.
Bradley-Terry weighted aggregation by per-judge reliability tracked over time
(``trust_weight`` column on ``judge_scores``).

Phase 4 ships with stub trust weights all = 1.0; Phase 6 fills them from
Cohen's κ vs the golden set.
"""

from __future__ import annotations

import asyncio
import statistics
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog

from app.models.carousel import (
    AUTO_PUBLISH_NOVELTY_FLOOR,
    AUTO_PUBLISH_THRESHOLD,
    AUTO_PUBLISH_VOICE_FLOOR,
    CarouselRubric,
    CarouselV2,
    JudgeAxisScore,
    JudgeName,
    RUBRIC_WEIGHTS,
    RubricAxis,
)

logger = structlog.get_logger(__name__)


# Each judge owns a subset of axes — keeps cost down and lets each model
# specialize. The aggregate covers all 7 axes once joined.
JUDGE_AXIS_OWNERSHIP: dict[JudgeName, list[RubricAxis]] = {
    JudgeName.KIMI_K2_6: [RubricAxis.FACT_ACCURACY, RubricAxis.NARRATIVE_ARC],
    JudgeName.MINIMAX_M2_7: [RubricAxis.HOOK_STRENGTH, RubricAxis.DESIGN_POLISH],
    JudgeName.QWEN3_32B_LOCAL: [RubricAxis.IMAGE_RELEVANCE, RubricAxis.VOICE_CONSISTENCY, RubricAxis.NOVELTY],
}

JUDGE_TASK_TYPE: dict[JudgeName, str] = {
    JudgeName.KIMI_K2_6: "judge_kimi",
    JudgeName.MINIMAX_M2_7: "judge_minimax",
    JudgeName.QWEN3_32B_LOCAL: "judge_local",
}

# Static trust weights — Phase 6 replaces these with rolling Cohen's κ.
DEFAULT_TRUST_WEIGHTS: dict[JudgeName, float] = {
    JudgeName.KIMI_K2_6: 1.0,
    JudgeName.MINIMAX_M2_7: 1.0,
    JudgeName.QWEN3_32B_LOCAL: 1.0,
}


# Anchored 1-10 rubric (Prometheus-Vision pattern).
AXIS_RUBRICS: dict[RubricAxis, str] = {
    RubricAxis.HOOK_STRENGTH: (
        "1=generic, 4=competent, 7=stops the scroll, 10=viral-tier contradiction or specificity"
    ),
    RubricAxis.FACT_ACCURACY: (
        "1=multiple errors, 4=mostly OK with one weak claim, 7=every claim verifiable, 10=every claim has Tier-1/2 source"
    ),
    RubricAxis.IMAGE_RELEVANCE: (
        "1=wrong character/era, 4=adjacent property, 7=correct character + context, 10=peak likeness + on-brand"
    ),
    RubricAxis.NARRATIVE_ARC: (
        "1=random list, 4=loose order, 7=hook→build→pivot→reveal→payoff, 10=cliffhanger transitions every slide"
    ),
    RubricAxis.DESIGN_POLISH: (
        "1=raw output, 4=basic typography, 7=brand-graded with film treatment, 10=cinematic still"
    ),
    RubricAxis.VOICE_CONSISTENCY: (
        "1=off-brand voice, 4=neutral, 7=on-brand lexicon present, 10=tone, lexicon, register all match the property"
    ),
    RubricAxis.NOVELTY: (
        "1=identical to last 30 carousels, 4=overlapping angle, 7=fresh angle, 10=unseen + non-obvious"
    ),
}


def _judge_prompt(carousel: CarouselV2, axis: RubricAxis) -> str:
    rubric = AXIS_RUBRICS[axis]
    slide_block = "\n".join(
        f"  Slide {s.slide_num} ({s.role}): {s.text[:240]}"
        for s in carousel.slides
    )
    return (
        f"AXIS: {axis.value}\n"
        f"RUBRIC: {rubric}\n\n"
        f"CAROUSEL: {carousel.topic}"
        + (f" / {carousel.franchise}" if carousel.franchise else "")
        + f"\nSLIDES:\n{slide_block}\n\n"
        + "Return JSON: {\"score\": float in 1-10, \"rationale\": string ≤220 chars}.\n"
        + "Score against the rubric anchors. Be calibrated, not generous."
    )


async def _score_axis(
    judge: JudgeName,
    axis: RubricAxis,
    carousel: CarouselV2,
    *,
    samples: int = 3,
) -> JudgeAxisScore:
    """Self-consistency: n=3 samples at temp=0.3, take median."""
    from app.infrastructure.unified_llm_client import UnifiedLLMClient

    client = UnifiedLLMClient()
    scores: list[float] = []
    rationales: list[str] = []
    task_type = JUDGE_TASK_TYPE[judge]

    async def _one() -> tuple[Optional[float], str]:
        try:
            result = await client.structured_chat(
                _judge_prompt(carousel, axis),
                output_schema={"score": 7.0, "rationale": "string"},
                task_type=task_type,
                temperature=0.3,
                max_tokens=300,
            )
            if isinstance(result, dict):
                return float(result.get("score", 0.0) or 0.0), str(result.get("rationale", ""))
        except Exception as exc:  # noqa: BLE001
            logger.warning("judge_call_failed", judge=judge.value, axis=axis.value, error=str(exc))
        return None, ""

    samples_run = await asyncio.gather(*(_one() for _ in range(max(1, samples))))
    for score, rationale in samples_run:
        if score is not None:
            scores.append(max(0.0, min(10.0, score)))
            rationales.append(rationale)

    median = statistics.median(scores) if scores else 0.0
    return JudgeAxisScore(
        judge=judge,
        axis=axis,
        score=median,
        rationale="; ".join(r for r in rationales if r)[:500] or None,
        samples_n=len(scores),
        trust_weight=DEFAULT_TRUST_WEIGHTS[judge],
    )


async def score_carousel(
    carousel: CarouselV2,
    *,
    samples_per_judge: int = 3,
) -> CarouselRubric:
    """Run all 3 judges, aggregate via Bradley-Terry-weighted mean per axis."""
    tasks = []
    for judge, axes in JUDGE_AXIS_OWNERSHIP.items():
        for axis in axes:
            tasks.append(_score_axis(judge, axis, carousel, samples=samples_per_judge))

    per_axis_per_judge = await asyncio.gather(*tasks)

    # Aggregate per axis (currently one judge per axis — extend to multi-judge
    # consensus when judge ownership overlaps in future iterations).
    by_axis: dict[RubricAxis, list[JudgeAxisScore]] = {}
    for j in per_axis_per_judge:
        by_axis.setdefault(j.axis, []).append(j)

    aggregated: dict[RubricAxis, float] = {}
    for axis, judges in by_axis.items():
        # Bradley-Terry weight aggregation: weighted mean by trust_weight.
        total_w = sum(j.trust_weight for j in judges) or 1.0
        aggregated[axis] = sum(j.score * j.trust_weight for j in judges) / total_w

    composite = sum(
        aggregated.get(axis, 0.0) * weight for axis, weight in RUBRIC_WEIGHTS.items()
    )

    voice_floor_met = aggregated.get(RubricAxis.VOICE_CONSISTENCY, 10.0) >= AUTO_PUBLISH_VOICE_FLOOR
    novelty_floor_met = aggregated.get(RubricAxis.NOVELTY, 10.0) >= AUTO_PUBLISH_NOVELTY_FLOOR
    passes = (
        composite >= AUTO_PUBLISH_THRESHOLD
        and voice_floor_met
        and novelty_floor_met
    )

    return CarouselRubric(
        per_axis_per_judge=per_axis_per_judge,
        aggregated=aggregated,
        composite=composite,
        passes_auto_publish=passes,
        voice_floor_met=voice_floor_met,
        novelty_floor_met=novelty_floor_met,
    )


async def persist_rubric(
    *,
    generation_id: str,
    carousel_id: Optional[str],
    rubric: CarouselRubric,
) -> None:
    """Write per-judge per-axis rows to ``judge_scores`` for replay + drift."""
    from app.db.models import JudgeScoreModel
    from app.infrastructure.database import get_session

    async with get_session() as session:
        for j in rubric.per_axis_per_judge:
            session.add(
                JudgeScoreModel(
                    id=uuid.uuid4().hex,
                    generation_id=generation_id,
                    carousel_id=carousel_id,
                    judge_name=j.judge.value,
                    axis=j.axis.value,
                    score=j.score,
                    rationale=j.rationale,
                    samples_n=j.samples_n,
                    trust_weight=j.trust_weight,
                    sampled_at=datetime.now(timezone.utc),
                )
            )
        await session.flush()
