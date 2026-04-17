"""Prompt Grader Service: LLM-as-judge for prompt runs.

Scores each prompt run 0-100 and detects common failure flags using
Kimi K2.5 as the judge (matches Legion's evaluation rubric so we can
compare across projects later). Runs as a scheduler job that batches
over ungraded prompt_runs rows.

Grading is intentionally cheap: one short judge call per run using
moonshot-v1-32k (~$0.024/1M tokens) by default, with K2.5 reserved for
the hardest task types.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from functools import lru_cache
from typing import Dict, List, Optional

import structlog

from app.infrastructure.llm_router import get_llm_router
from app.infrastructure.unified_llm_client import get_unified_llm_client
from app.models.brain import PromptRun, PromptRunGrade

logger = structlog.get_logger(__name__)


KNOWN_FLAGS = {
    "hallucination",
    "incomplete",
    "off_topic",
    "wrong_format",
    "low_effort",
    "fabricated_data",
    "unsafe",
    "rules_violation",
    "repetitive",
    "truncated",
}


JUDGE_SYSTEM_PROMPT = """You are a strict prompt quality judge.

Given a system prompt, a user prompt, and an LLM response, score the response
from 0 to 100 on how well it satisfies the user prompt's intent and constraints.

Scoring bands:
- 90-100: Excellent. Fully satisfies the prompt, accurate, correct format.
- 70-89:  Solid. Minor issues only.
- 50-69:  Mixed. Partially satisfies or has notable issues.
- 30-49:  Weak. Major gaps, wrong format, or likely inaccurate content.
- 0-29:   Fail. Off topic, hallucinated, empty, or format-broken.

Also return any failure flags that apply, chosen ONLY from this list:
hallucination, incomplete, off_topic, wrong_format, low_effort,
fabricated_data, unsafe, rules_violation, repetitive, truncated.

Write a concise summary (one sentence, no em dashes, no markdown) explaining
the score.

Return ONLY a JSON object with this exact shape:
{"score": 0-100, "flags": ["..."], "summary": "..."}
"""


def _truncate(text: Optional[str], limit: int) -> str:
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...(truncated)"


def _build_judge_prompt(run: PromptRun) -> str:
    system_part = _truncate(run.system_prompt, 1500)
    user_part = _truncate(run.user_prompt, 3500)
    resp_part = _truncate(run.response_text, 3500)
    return (
        f"TASK TYPE: {run.task_type}\n"
        f"SOURCE: {run.source}\n\n"
        f"--- SYSTEM PROMPT ---\n{system_part}\n\n"
        f"--- USER PROMPT ---\n{user_part}\n\n"
        f"--- LLM RESPONSE ---\n{resp_part}\n\n"
        f"Grade the response now."
    )


class PromptGraderService:
    """LLM-as-judge grader for prompt runs.

    Routes through the central LLM router by task type.
    - prompt_grading: cheap default judge (moonshot-v1-32k by default).
    - prompt_grading_heavy: reserved for tough task types (K2.5 by default).
    Actual model selection lives in the router config so swaps need no code edit.
    """

    HEAVY_TASK_TYPES = {
        "character_content_review_final",
    }

    def _pick_task_type(self, task_type: str) -> str:
        if task_type in self.HEAVY_TASK_TYPES:
            return "prompt_grading_heavy"
        return "prompt_grading"

    async def grade_run(self, run: PromptRun) -> Optional[PromptRunGrade]:
        """Grade a single prompt run. Returns None on hard failure."""
        if not run.response_text:
            return None
        if not run.success:
            return None

        grader_task_type = self._pick_task_type(run.task_type)
        grader_model = get_llm_router().resolve(grader_task_type)
        judge_prompt = _build_judge_prompt(run)

        client = get_unified_llm_client()
        # Heavy judge (typically K2.5) requires temperature=1; cheap judge takes 0.2.
        temperature = 1.0 if grader_task_type == "prompt_grading_heavy" else 0.2

        try:
            raw = await client.chat(
                prompt=judge_prompt,
                system=JUDGE_SYSTEM_PROMPT,
                task_type=grader_task_type,
                temperature=temperature,
                max_tokens=512,
            )
        except Exception as e:
            logger.warning("prompt_grade_llm_failed", run_id=run.id, error=str(e))
            return None

        parsed = self._parse_judge_response(raw)
        if not parsed:
            return None

        return PromptRunGrade(
            quality_score=parsed["score"],
            quality_flags=parsed["flags"],
            quality_summary=parsed["summary"],
            grader_model=grader_model,
        )

    def _parse_judge_response(self, raw: str) -> Optional[Dict]:
        """Parse a judge response, tolerating code fences and trailing text."""
        if not raw:
            return None
        text = raw.strip()
        # Strip code fences
        if text.startswith("```"):
            lines = text.split("\n")
            end = -1 if lines[-1].strip() == "```" else len(lines)
            text = "\n".join(lines[1:end]).strip()

        # Try direct parse; if not, find the first {...} block
        try:
            obj = json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start < 0 or end <= start:
                return None
            try:
                obj = json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                return None

        try:
            score = float(obj.get("score", 0))
        except (TypeError, ValueError):
            return None
        score = max(0.0, min(100.0, score))

        flags_raw = obj.get("flags") or []
        if not isinstance(flags_raw, list):
            flags_raw = []
        flags = [f for f in flags_raw if isinstance(f, str) and f in KNOWN_FLAGS]

        summary_raw = obj.get("summary") or ""
        summary = str(summary_raw).strip()[:500]

        return {"score": score, "flags": flags, "summary": summary}

    async def grade_pending(self, limit: int = 20) -> Dict[str, int]:
        """Grade up to `limit` ungraded runs. Called by the scheduler."""
        from app.services.prompt_evolution_service import get_prompt_evolution_service

        svc = get_prompt_evolution_service()
        pending = await svc.get_ungraded_runs(limit=limit)
        if not pending:
            return {"requested": limit, "graded": 0, "skipped": 0}

        graded = 0
        skipped = 0
        for run in pending:
            grade = await self.grade_run(run)
            if grade is None:
                skipped += 1
                continue
            ok = await svc.apply_grade(run.id, grade)
            if ok:
                graded += 1
            else:
                skipped += 1

        logger.info(
            "prompt_grade_batch_complete",
            requested=limit,
            graded=graded,
            skipped=skipped,
        )
        return {"requested": limit, "graded": graded, "skipped": skipped}


@lru_cache()
def get_prompt_grader_service() -> PromptGraderService:
    return PromptGraderService()
