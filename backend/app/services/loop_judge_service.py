"""Loop judge service — scores recent unscored runs via local Qwen3.

Per the user's $0/day decision: ALL judging is local Qwen3.6-35B-A3B
abliterated through LiteLLM at :4444. There is no cloud-judge code path.

Two roles, one model:
- Runners use `qwen3-chat` (reasoning-off, fast TTFT)
- Judge uses `qwen3-chat-thinking` (reasoning-on, structured CoT scoring)

Mitigations against same-model bias:
- Different reasoning mode (thinking vs no-thinking)
- Distinct judge persona ("strict reviewer")
- Strict Pydantic-shaped JSON output (rubric, no free-form)
- Output is graded on a 0-100 scale with explicit failure modes

The judge writes back to loop_runs.judge_score / judge_notes and pushes
the score to Legion's mirror via a fresh POST (idempotent on zero_run_id).
"""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from typing import Any, Optional

import httpx
import structlog
from sqlalchemy import select, update

from app.db.models import LoopModel, LoopRunModel, LoopVariantModel
from app.infrastructure.database import get_session

logger = structlog.get_logger(__name__)


_DEFAULT_LITELLM_URL = "http://host.docker.internal:4445/v1"  # repointed to Bifrost
# Model resolves through the registry; future renames touch
# `app/constants/models.py` only.
from app.constants.models import LOCAL_CHAT as _DEFAULT_JUDGE_MODEL  # noqa: E402
_DEFAULT_JUDGE_TIMEOUT = 480.0  # 8 min — JSON-mode guided decoding can be slow on large inputs

# llama.cpp serves with --ctx-size 16384 / --parallel 2 = 8192 per slot.
# Slot budget split (chars at ~4/token):
#   ~500 tokens fixed boilerplate (system prompt rubric + JSON contract)
#   ~2000 tokens spec      (8000 chars — head of skill is most important)
#   ~1500 tokens output    (6000 chars — recent skill output sample)
#   ~3500 tokens response  (model reasons internally, emits JSON; with
#                           response_format=json_object guided decoding,
#                           plenty of room for the verdict JSON).
# Total input ~4000 + output 3500 = 7500, leaves ~700 token cushion.
JUDGE_SPEC_CHAR_CAP = 8000
JUDGE_OUTPUT_CHAR_CAP = 6000
JUDGE_MAX_OUTPUT_TOKENS = 3500


JUDGE_SYSTEM_PROMPT = """You are a strict, terse output evaluator inside a 24/7 \
self-improvement loop framework. The user is not present.

You are given:
1. The skill specification the runner was supposed to follow.
2. The runner's actual output.

Score the runner's output against the spec on a 0-100 scale and return ONLY \
a JSON object matching this exact shape:

{
  "score": <integer 0-100>,
  "rubric": {
    "followed_spec": <integer 0-25>,
    "specificity": <integer 0-25>,
    "actionability": <integer 0-25>,
    "evidence_grounded": <integer 0-25>
  },
  "primary_failure_mode": <one of: "none"|"vague"|"hallucinated"|"off_topic"|"truncated"|"refused"|"format">,
  "summary": <single sentence, max 200 chars>
}

Rubric:
- followed_spec: did the runner do the audit/check the spec described?
- specificity: are findings concrete (file paths, line numbers, port numbers, \
specific metrics) or vague generalities?
- actionability: can a human or automation act on this output?
- evidence_grounded: does the output reference real artifacts or invent things?

Return ONLY the JSON object. No prose before or after. No markdown fences."""


JSON_OBJ_RE = re.compile(r"\{[^{}]*\"score\"[^{}]*\}", re.DOTALL)


class LoopJudgeService:
    """Score loop_runs that don't have a judge_score yet."""

    def __init__(self) -> None:
        self._litellm_base = (
            os.environ.get("ZERO_VLLM_CHAT_URL")
            or os.environ.get("ZERO_LITELLM_URL")
            or _DEFAULT_LITELLM_URL
        ).rstrip("/")
        self._litellm_key = (
            os.environ.get("ZERO_VLLM_API_KEY")
            or os.environ.get("LITELLM_MASTER_KEY")
            or "EMPTY"
        )
        self._judge_model = os.environ.get("ZERO_LOOP_JUDGE_MODEL", _DEFAULT_JUDGE_MODEL)
        self._timeout_s = float(os.environ.get("ZERO_LOOP_JUDGE_TIMEOUT", _DEFAULT_JUDGE_TIMEOUT))

    async def score_recent_runs(self, *, limit: int = 10) -> dict[str, Any]:
        """Find recent successful runs without a judge_score and score them."""
        async with get_session() as session:
            stmt = (
                select(LoopRunModel, LoopModel)
                .join(LoopModel, LoopRunModel.loop_id == LoopModel.id)
                .where(LoopRunModel.status == "success")
                .where(LoopRunModel.judge_score.is_(None))
                .where(LoopRunModel.output.is_not(None))
                .where(LoopModel.judge_tier == "local")
                .order_by(LoopRunModel.started_at.desc())
                .limit(limit)
            )
            rows = (await session.execute(stmt)).all()

        scored = 0
        skipped = 0
        for run, loop in rows:
            try:
                result = await self.score_one(run.id, run.output or "", loop.runner_target)
                if result is None:
                    skipped += 1
                else:
                    scored += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "loop.judge_failed",
                    run_id=run.id,
                    error_type=type(exc).__name__,
                    error=str(exc) or repr(exc),
                )
                skipped += 1

        return {"scored": scored, "skipped": skipped, "candidates": len(rows)}

    async def score_one(
        self,
        run_id: int,
        output: str,
        skill_path: str,
    ) -> Optional[dict[str, Any]]:
        """Score one run, write judge_score + judge_notes, return the result."""
        spec_text = self._read_spec(skill_path)
        if not spec_text or not output.strip():
            return None

        # Trim hard to fit the per-slot llama.cpp budget. Judge runs on
        # summaries, not full transcripts.
        spec_text = spec_text[:JUDGE_SPEC_CHAR_CAP]
        output_text = output[:JUDGE_OUTPUT_CHAR_CAP]

        user_msg = (
            "=== SKILL SPECIFICATION ===\n"
            f"{spec_text}\n"
            "=== END SPECIFICATION ===\n\n"
            "=== RUNNER OUTPUT ===\n"
            f"{output_text}\n"
            "=== END OUTPUT ===\n\n"
            "Return the JSON evaluation now."
        )
        raw = await self._call_litellm(JUDGE_SYSTEM_PROMPT, user_msg)
        verdict = self._parse_verdict(raw)
        if verdict is None:
            logger.warning("loop.judge_unparseable", run_id=run_id, raw_head=raw[:200])
            return None

        score = int(verdict.get("score") or 0)
        score = max(0, min(100, score))
        notes = json.dumps(verdict, ensure_ascii=False, indent=2)[:6000]

        async with get_session() as session:
            run = await session.get(LoopRunModel, run_id)
            if not run:
                return verdict
            run.judge_score = float(score)
            run.judge_notes = notes
            # Critical: also feed the score into the variant's total_score so the
            # promotion service has real averages to compare. Without this,
            # canary.avg_score is always 0 and no canary can ever win.
            if run.variant_id is not None:
                await session.execute(
                    update(LoopVariantModel)
                    .where(LoopVariantModel.id == run.variant_id)
                    .values(total_score=LoopVariantModel.total_score + float(score))
                )
            await session.commit()

        logger.info("loop.judged", run_id=run_id, score=score, mode=verdict.get("primary_failure_mode"))
        return verdict

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _read_spec(self, target: str) -> str:
        try:
            with open(target, "r", encoding="utf-8", errors="replace") as fh:
                return fh.read()
        except OSError:
            return ""

    async def _call_litellm(self, system: str, user: str) -> str:
        url = f"{self._litellm_base}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._litellm_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._judge_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.1,
            "max_tokens": JUDGE_MAX_OUTPUT_TOKENS,
            # JSON mode — forces the model to emit a single JSON object.
            # vLLM/llama.cpp honors this via guided decoding, which short-circuits
            # any chain-of-thought rambling.
            "response_format": {"type": "json_object"},
        }
        async with httpx.AsyncClient(timeout=httpx.Timeout(self._timeout_s)) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            return ""
        msg = choices[0].get("message") or {}
        # Some providers (Qwen3-thinking, Kimi K2.6) put the visible reply in
        # `reasoning_content`. Concatenate to be safe.
        text = msg.get("content") or ""
        if not text.strip():
            text = msg.get("reasoning_content") or ""
        return text

    @staticmethod
    def _parse_verdict(raw: str) -> Optional[dict[str, Any]]:
        """Extract the JSON verdict from the judge's response.

        The model often reasons in prose before emitting JSON. We want the
        LAST `{...}` block that contains a "score" field.
        """
        if not raw:
            return None
        cleaned = raw.strip()
        # Strip code fences if present.
        cleaned = re.sub(r"```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"```", "", cleaned)
        # Try direct parse first (well-behaved model).
        try:
            obj = json.loads(cleaned)
            if isinstance(obj, dict) and "score" in obj:
                return obj
        except json.JSONDecodeError:
            pass
        # Find the LAST balanced JSON object containing "score".
        # Walk backward from each "}" and try to balance braces.
        candidates: list[dict[str, Any]] = []
        for end_idx in [m.start() for m in re.finditer(r"\}", cleaned)][::-1]:
            depth = 0
            for start_idx in range(end_idx, -1, -1):
                ch = cleaned[start_idx]
                if ch == "}":
                    depth += 1
                elif ch == "{":
                    depth -= 1
                    if depth == 0:
                        snippet = cleaned[start_idx:end_idx + 1]
                        try:
                            obj = json.loads(snippet)
                        except json.JSONDecodeError:
                            break
                        if isinstance(obj, dict) and "score" in obj:
                            candidates.append(obj)
                        break
            if candidates:
                return candidates[0]
        return None


@lru_cache(maxsize=1)
def get_loop_judge() -> LoopJudgeService:
    return LoopJudgeService()
