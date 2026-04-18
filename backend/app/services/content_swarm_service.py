"""Content Swarm Service (Phase 2 of Content Brain v2).

Replaces single-LLM carousel decisioning with a multi-role swarm.
Each voting role records a prediction (predicted engagement + confidence) that
feeds calibration tracking. Weighted consensus with veto power from CriticVoter.

Roles are intentionally lightweight wrappers around the shared LLM router —
the expensive execution step still runs through the existing character_content
pipeline. The swarm adds pre-generation decisioning + post-generation critique
so prompt variants, angles, and templates can be scored against the actual
outcome on each carousel.

Inspired by ADA's LangGraph swarm architecture (debate + consensus + veto).
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import select

from app.db.models import AgentPredictionModel, CharacterModel, TrendingSignalModel
from app.infrastructure.database import get_session
from app.infrastructure.unified_llm_client import get_unified_llm_client

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class SwarmRole:
    name: str
    weight: float
    system: str
    has_veto: bool
    task_type: str


# Voting roles. Weights sum to 1.0. CriticVoter holds a hard veto.
VOTING_ROLES: Dict[str, SwarmRole] = {
    "trend_scout": SwarmRole(
        name="trend_scout",
        weight=0.15,
        system=(
            "You are TrendScout. Evaluate cultural relevance and decay window. "
            "Ask: is this character/trend still viral, peaking, or fading? "
            "Return ONLY JSON: {\"predicted_engagement\": 0-100, \"confidence\": 0-1, "
            "\"vote\": \"accept|hold|reject\", \"reasoning\": \"one sentence\"}."
        ),
        has_veto=False,
        task_type="council_researcher",
    ),
    "researcher": SwarmRole(
        name="researcher",
        weight=0.20,
        system=(
            "You are the Researcher. Evaluate fact depth and source credibility. "
            "Weigh: enough verified facts, no fabrications, sources cited. "
            "Return ONLY JSON: {\"predicted_engagement\": 0-100, \"confidence\": 0-1, "
            "\"vote\": \"accept|hold|reject\", \"reasoning\": \"one sentence\"}."
        ),
        has_veto=False,
        task_type="council_researcher",
    ),
    "strategist": SwarmRole(
        name="strategist",
        weight=0.20,
        system=(
            "You are the Strategist. Evaluate angle + hook style + template fit for the audience. "
            "Consider: is this angle fresh or overused, will hook land in first 2s. "
            "Return ONLY JSON: {\"predicted_engagement\": 0-100, \"confidence\": 0-1, "
            "\"vote\": \"accept|hold|reject\", \"reasoning\": \"one sentence\"}."
        ),
        has_veto=False,
        task_type="council_ceo",
    ),
    "editor": SwarmRole(
        name="editor",
        weight=0.15,
        system=(
            "You are the Editor. Evaluate copy polish, grammar, flow, slide pacing. "
            "Return ONLY JSON: {\"predicted_engagement\": 0-100, \"confidence\": 0-1, "
            "\"vote\": \"accept|hold|reject\", \"reasoning\": \"one sentence\"}."
        ),
        has_veto=False,
        task_type="council_researcher",
    ),
    "critic": SwarmRole(
        name="critic",
        weight=0.15,
        system=(
            "You are the Critic. You hold VETO. Evaluate brand fit, safety, factual accuracy, "
            "compliance risk. Reject any content with fabricated claims, unsafe framing, or brand-off tone. "
            "Return ONLY JSON: {\"predicted_engagement\": 0-100, \"confidence\": 0-1, "
            "\"vote\": \"accept|hold|reject\", \"reasoning\": \"one sentence\"}."
        ),
        has_veto=True,
        task_type="council_ceo",
    ),
    "value_predictor": SwarmRole(
        name="value_predictor",
        weight=0.15,
        system=(
            "You are the ValuePredictor. Give the sharpest possible calibrated prediction of 24h engagement. "
            "Return ONLY JSON: {\"predicted_engagement\": 0-100, \"confidence\": 0-1, "
            "\"vote\": \"accept|hold|reject\", \"reasoning\": \"one sentence\"}."
        ),
        has_veto=False,
        task_type="council_ceo",
    ),
}


ACCEPT_THRESHOLD = 0.65
MIN_CONFIDENCE = 0.2


def _extract_json(raw: str) -> Optional[Dict[str, Any]]:
    """Find the LAST parseable JSON object in the text.

    Kimi k2-thinking returns <thinking>…</thinking> blocks that often contain
    the JSON format *specification* (with literal 0-100 or accept|hold|reject)
    which is not valid JSON. The actual answer appears after the thinking, so
    we scan all `{...}` candidates and return the last one that has concrete
    numeric/string values for predicted_engagement.
    """
    if not raw:
        return None
    candidates = re.findall(r"\{[^{}]*\}", raw, re.DOTALL)
    for match in reversed(candidates):
        try:
            obj = json.loads(match)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(obj, dict):
            continue
        # Must have at least a numeric predicted_engagement to count as "real"
        pe = obj.get("predicted_engagement")
        if isinstance(pe, (int, float)):
            return obj
        # Fallback: if it's the only candidate and has some expected keys
        if any(k in obj for k in ("confidence", "vote", "reasoning")):
            return obj
    return None


class ContentSwarmService:
    """Orchestrates a weighted vote across content roles."""

    def __init__(self) -> None:
        self._llm = get_unified_llm_client()

    # ------------------------------------------------------------------
    # Vote collection
    # ------------------------------------------------------------------

    async def _collect_vote(self, role: SwarmRole, user_prompt: str) -> Dict[str, Any]:
        """Ask a single role to vote. Fallback to neutral vote on parse failure."""
        try:
            raw = await self._llm.chat(
                prompt=user_prompt,
                system=role.system,
                task_type=role.task_type,
                temperature=0.3,
                max_tokens=1200,  # Kimi k2-thinking needs headroom for its reasoning + final JSON
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("swarm_role_call_failed", role=role.name, error=str(e)[:200])
            return {
                "predicted_engagement": 50.0,
                "confidence": 0.1,
                "vote": "hold",
                "reasoning": f"llm_call_failed: {str(e)[:100]}",
            }
        parsed = _extract_json(raw)
        if parsed is None:
            return {
                "predicted_engagement": 50.0,
                "confidence": 0.1,
                "vote": "hold",
                "reasoning": "parse_failed",
            }
        return {
            "predicted_engagement": max(0.0, min(100.0, float(parsed.get("predicted_engagement", 50)))),
            "confidence": max(0.0, min(1.0, float(parsed.get("confidence", 0.5)))),
            "vote": str(parsed.get("vote", "hold")).lower(),
            "reasoning": str(parsed.get("reasoning", ""))[:500],
        }

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def _record_prediction(
        self,
        *,
        carousel_id: str,
        content_type: str,
        role: SwarmRole,
        phase: str,
        predicted_engagement: float,
        confidence: float,
        vote: str,
        reasoning: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        pred_id = f"pred-{uuid.uuid4().hex[:12]}"
        async with get_session() as session:
            row = AgentPredictionModel(
                id=pred_id,
                carousel_id=carousel_id,
                content_type=content_type,
                role_name=role.name,
                phase=phase,
                predicted_engagement=predicted_engagement,
                confidence=confidence,
                vote=vote,
                reasoning=reasoning,
                weight=role.weight,
                prediction_metadata=metadata or {},
            )
            session.add(row)
            await session.commit()
        return pred_id

    # ------------------------------------------------------------------
    # Consensus math
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_consensus(votes: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Return {decision, consensus_score, weighted_engagement, vetoed_by}.

        decision: accept | hold | reject
        consensus_score: sum(weight * confidence * accept_signal) in [0,1]
                         accept_signal = 1 for accept, 0.5 for hold, 0 for reject.
        weighted_engagement: weighted average of predicted_engagement.
        """
        if not votes:
            return {"decision": "hold", "consensus_score": 0.0, "weighted_engagement": 0.0, "vetoed_by": None}

        accept_signal_map = {"accept": 1.0, "hold": 0.5, "reject": 0.0}
        total_weight = sum(v.get("weight", 0.0) for v in votes) or 1.0
        consensus = 0.0
        weighted_engagement = 0.0
        vetoed_by = None
        for v in votes:
            signal = accept_signal_map.get(v.get("vote", "hold"), 0.5)
            confidence = max(MIN_CONFIDENCE, float(v.get("confidence", 0.5)))
            w = float(v.get("weight", 0.0))
            consensus += (w * confidence * signal) / total_weight
            weighted_engagement += (w * float(v.get("predicted_engagement", 50.0))) / total_weight
            if v.get("has_veto") and v.get("vote") == "reject" and vetoed_by is None:
                vetoed_by = v.get("role")

        if vetoed_by:
            decision = "reject"
        elif consensus >= ACCEPT_THRESHOLD:
            decision = "accept"
        elif consensus <= 0.3:
            decision = "reject"
        else:
            decision = "hold"

        return {
            "decision": decision,
            "consensus_score": round(consensus, 4),
            "weighted_engagement": round(weighted_engagement, 2),
            "vetoed_by": vetoed_by,
        }

    # ------------------------------------------------------------------
    # Public: pre-generation evaluation
    # ------------------------------------------------------------------

    async def evaluate_generation_idea(
        self,
        *,
        carousel_id: str,
        content_type: str,
        character: Optional[CharacterModel],
        angle: str,
        template: Optional[str],
        facts_preview: List[str],
    ) -> Dict[str, Any]:
        """Pre-generation vote from TrendScout + Researcher + Strategist.

        Returns consensus dict. Persists one AgentPrediction per role.
        """
        # Pull active trending signal context for trend_scout
        trend_hint = ""
        if character is not None and character.franchise:
            async with get_session() as session:
                sres = await session.execute(
                    select(TrendingSignalModel)
                    .where(TrendingSignalModel.franchise == character.franchise)
                    .where(TrendingSignalModel.expires_at.is_(None) | (TrendingSignalModel.expires_at > datetime.now(timezone.utc)))
                    .order_by(TrendingSignalModel.signal_strength.desc())
                    .limit(1)
                )
                sig = sres.scalars().first()
            if sig is not None:
                trend_hint = (
                    f"Active trend: source={sig.source}, strength={sig.signal_strength:.0f}, "
                    f"release_date={sig.release_date}, reason={sig.score_reasoning or 'n/a'}"
                )

        facts_line = "; ".join(facts_preview[:5]) if facts_preview else "(no facts available)"
        character_line = (
            f"Character: {character.name} (franchise: {character.franchise or 'unknown'})"
            if character is not None
            else "(no character context — media carousel)"
        )

        user_prompt = (
            f"{character_line}\n"
            f"Angle: {angle}\n"
            f"Template: {template or '(default)'}\n"
            f"Facts preview: {facts_line}\n"
            f"{trend_hint}\n\n"
            "Evaluate whether to proceed generating this carousel. Return JSON only."
        )

        pre_gen_roles = ["trend_scout", "researcher", "strategist"]
        votes: List[Dict[str, Any]] = []
        for role_name in pre_gen_roles:
            role = VOTING_ROLES[role_name]
            result = await self._collect_vote(role, user_prompt)
            await self._record_prediction(
                carousel_id=carousel_id,
                content_type=content_type,
                role=role,
                phase="pre_gen",
                predicted_engagement=result["predicted_engagement"],
                confidence=result["confidence"],
                vote=result["vote"],
                reasoning=result["reasoning"],
                metadata={"angle": angle, "template": template},
            )
            votes.append({
                "role": role_name,
                "weight": role.weight,
                "has_veto": role.has_veto,
                **result,
            })

        consensus = self._compute_consensus(votes)
        consensus["phase"] = "pre_gen"
        consensus["votes"] = votes
        return consensus

    # ------------------------------------------------------------------
    # Public: post-generation critique
    # ------------------------------------------------------------------

    async def critique_generated_carousel(
        self,
        *,
        carousel_id: str,
        content_type: str,
        hook: str,
        slides_preview: List[str],
        angle: str,
    ) -> Dict[str, Any]:
        """Editor + Critic + ValuePredictor vote on the finished carousel."""
        slides_line = "\n".join(f"- {s[:180]}" for s in slides_preview[:6])
        user_prompt = (
            f"Angle: {angle}\n"
            f"Hook: {hook}\n"
            f"Slides:\n{slides_line}\n\n"
            "Evaluate this finished carousel. Return JSON only."
        )

        post_gen_roles = ["editor", "critic", "value_predictor"]
        votes: List[Dict[str, Any]] = []
        for role_name in post_gen_roles:
            role = VOTING_ROLES[role_name]
            result = await self._collect_vote(role, user_prompt)
            await self._record_prediction(
                carousel_id=carousel_id,
                content_type=content_type,
                role=role,
                phase="post_gen",
                predicted_engagement=result["predicted_engagement"],
                confidence=result["confidence"],
                vote=result["vote"],
                reasoning=result["reasoning"],
                metadata={"angle": angle, "hook": hook[:200]},
            )
            votes.append({
                "role": role_name,
                "weight": role.weight,
                "has_veto": role.has_veto,
                **result,
            })

        consensus = self._compute_consensus(votes)
        consensus["phase"] = "post_gen"
        consensus["votes"] = votes
        return consensus

    # ------------------------------------------------------------------
    # Outcome calibration (back-fills actual engagement onto predictions)
    # ------------------------------------------------------------------

    async def record_outcome(self, carousel_id: str, actual_engagement: float) -> Dict[str, Any]:
        """Write outcome_engagement onto every prediction for this carousel,
        compute calibration_error = |predicted - actual|."""
        updated = 0
        async with get_session() as session:
            res = await session.execute(
                select(AgentPredictionModel).where(AgentPredictionModel.carousel_id == carousel_id)
            )
            rows = list(res.scalars().all())
            for row in rows:
                row.outcome_engagement = actual_engagement
                row.outcome_recorded_at = datetime.now(timezone.utc)
                row.calibration_error = abs(row.predicted_engagement - actual_engagement)
                updated += 1
            await session.commit()
        return {"carousel_id": carousel_id, "updated": updated}


@lru_cache()
def get_content_swarm_service() -> ContentSwarmService:
    return ContentSwarmService()
