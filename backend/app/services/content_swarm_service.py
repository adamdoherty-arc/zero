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

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta as _timedelta, timezone
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

import structlog
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select

from app.db.models import (
    AgentPredictionModel,
    CharacterCarouselModel,
    CharacterModel,
    SwarmRoleWeightModel,
    TrendingSignalModel,
)
from app.infrastructure.database import get_session
from app.infrastructure.unified_llm_client import get_unified_llm_client


class SwarmRubric(BaseModel):
    """Structured post-generation quality rubric.

    Emitted by critique_generated_carousel. Drives the W3 fail-retry edge in the
    carousel graph: if any pass/fail field fails or the weighted score dips
    below threshold, the graph routes back to synthesis with `issues` as feedback.
    """

    canon_accuracy: float = Field(default=5.0, ge=0.0, le=10.0)
    hook_strength: float = Field(default=5.0, ge=0.0, le=10.0)
    pacing: float = Field(default=5.0, ge=0.0, le=10.0)
    visual_consistency: float = Field(default=5.0, ge=0.0, le=10.0)
    platform_compliance: float = Field(default=5.0, ge=0.0, le=10.0)
    safety: str = Field(default="pass")  # "pass" | "fail"
    commentary_framing: str = Field(default="pass")  # "pass" | "fail"
    issues: List[str] = Field(default_factory=list)

    def weighted_score(self) -> float:
        """Average of the numeric dimensions, 0-10."""
        return round(
            (
                self.canon_accuracy
                + self.hook_strength
                + self.pacing
                + self.visual_consistency
                + self.platform_compliance
            )
            / 5.0,
            2,
        )

    def passes_gate(self, threshold: float = 6.5) -> bool:
        """Rubric passes if numeric score clears threshold AND no pass/fail fails."""
        if self.safety != "pass" or self.commentary_framing != "pass":
            return False
        return self.weighted_score() >= threshold

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


RUBRIC_SYSTEM = (
    "You are the Critic. Score the carousel on five dimensions from 0 to 10 "
    "(canon_accuracy, hook_strength, pacing, visual_consistency, platform_compliance) "
    "and emit two pass/fail gates (safety, commentary_framing). commentary_framing is "
    "pass when the carousel reads as commentary/analysis about the character (e.g. "
    "'Why Batman never uses guns'), not as in-universe entertainment featuring the "
    "character — commentary framing is the load-bearing fair-use defense. Return ONLY JSON: "
    '{"canon_accuracy":0-10,"hook_strength":0-10,"pacing":0-10,"visual_consistency":0-10,'
    '"platform_compliance":0-10,"safety":"pass|fail","commentary_framing":"pass|fail",'
    '"issues":["short string",...]}.'
)


def _timedelta_days(days: int) -> _timedelta:
    return _timedelta(days=days)


_TOKEN_RE = re.compile(r"[A-Za-z0-9']+")


def _tokenize_for_simhash(text: str) -> List[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text or "") if len(t) > 1]


def hook_simhash(text: str, bits: int = 64) -> int:
    """Compute a 64-bit simhash over token-shingled text.

    Near-duplicate hooks have small Hamming distance between their simhashes.
    Simple, dependency-free implementation. Good enough to catch "Batman never
    uses guns" vs "Why Batman never uses guns" at Hamming <= 8.
    """
    tokens = _tokenize_for_simhash(text)
    if not tokens:
        return 0
    # 2-gram shingles for more structure; falls back to 1-gram if too short.
    shingles: List[str] = []
    if len(tokens) >= 2:
        shingles.extend(f"{a} {b}" for a, b in zip(tokens, tokens[1:]))
    shingles.extend(tokens)
    counter: Dict[int, int] = {}
    for sh in shingles:
        counter[sh] = counter.get(sh, 0) + 1  # type: ignore[index]
    v = [0] * bits
    for shingle, weight in counter.items():
        digest = int.from_bytes(
            hashlib.sha1(shingle.encode("utf-8")).digest()[: (bits // 8)], "big"
        )
        for i in range(bits):
            if digest & (1 << i):
                v[i] += weight
            else:
                v[i] -= weight
    h = 0
    for i in range(bits):
        if v[i] > 0:
            h |= (1 << i)
    return h


def hamming_distance(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def _pearson(xs: List[float], ys: List[float]) -> float:
    """Simple Pearson correlation; returns 0.0 on degenerate input."""
    n = len(xs)
    if n < 2 or n != len(ys):
        return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    denom_x = sum((x - mx) ** 2 for x in xs) ** 0.5
    denom_y = sum((y - my) ** 2 for y in ys) ** 0.5
    if denom_x == 0 or denom_y == 0:
        return 0.0
    return num / (denom_x * denom_y)


def _parse_rubric(raw: str) -> Optional[SwarmRubric]:
    """Pull the last JSON object out of `raw` and try to coerce to SwarmRubric.

    _extract_json screens for vote-style keys. The rubric format uses different
    keys (canon_accuracy, etc.) so we scan for any `{...}` blob that parses and
    contains at least one of the expected rubric fields.
    """
    if not raw:
        return None
    # Fast path: whole body is a JSON object.
    try:
        obj = json.loads(raw.strip())
        if isinstance(obj, dict):
            try:
                return SwarmRubric(**obj)
            except (ValidationError, TypeError):
                pass
    except (json.JSONDecodeError, ValueError):
        pass

    # Fallback: scan all single-level JSON objects, prefer the last one that
    # carries at least one rubric key.
    rubric_keys = {
        "canon_accuracy", "hook_strength", "pacing",
        "visual_consistency", "platform_compliance", "safety",
        "commentary_framing",
    }
    candidates = re.findall(r"\{[^{}]*\}", raw, re.DOTALL)
    for match in reversed(candidates):
        try:
            obj = json.loads(match)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(obj, dict):
            continue
        if not (rubric_keys & set(obj.keys())):
            continue
        try:
            return SwarmRubric(**obj)
        except (ValidationError, TypeError):
            continue
    return None


class ContentSwarmService:
    """Orchestrates a weighted vote across content roles."""

    def __init__(self) -> None:
        self._llm = get_unified_llm_client()
        # In-memory cache of calibrated role weights (reloaded from DB each vote cycle
        # via refresh_role_weights()). Falls back to VOTING_ROLES static weights.
        self._role_weight_overrides: Dict[str, float] = {}
        self._weights_loaded_at: Optional[datetime] = None

    # ------------------------------------------------------------------
    # Calibrated role weights (W4)
    # ------------------------------------------------------------------

    async def refresh_role_weights(self, max_age_seconds: int = 600) -> Dict[str, float]:
        """Load calibrated per-role weights from swarm_role_weights.

        Cached for `max_age_seconds` to avoid a DB hit on every vote.
        Returns the effective weight map (role_name -> weight).
        """
        now = datetime.now(timezone.utc)
        if (
            self._weights_loaded_at is not None
            and (now - self._weights_loaded_at).total_seconds() < max_age_seconds
        ):
            return self._effective_weights()

        async with get_session() as session:
            res = await session.execute(select(SwarmRoleWeightModel))
            rows = list(res.scalars().all())
        self._role_weight_overrides = {row.role_name: float(row.weight) for row in rows}
        self._weights_loaded_at = now
        return self._effective_weights()

    def _effective_weights(self) -> Dict[str, float]:
        """Merge static VOTING_ROLES weights with calibrated overrides, normalized to sum 1."""
        merged = {
            name: self._role_weight_overrides.get(name, role.weight)
            for name, role in VOTING_ROLES.items()
        }
        total = sum(merged.values()) or 1.0
        return {k: v / total for k, v in merged.items()}

    def _weighted_role(self, role: SwarmRole, weights: Dict[str, float]) -> SwarmRole:
        """Return a copy of `role` with its weight overridden from `weights`."""
        effective = weights.get(role.name, role.weight)
        if effective == role.weight:
            return role
        return SwarmRole(
            name=role.name,
            weight=effective,
            system=role.system,
            has_veto=role.has_veto,
            task_type=role.task_type,
        )

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

        weights = await self.refresh_role_weights()
        pre_gen_roles = ["trend_scout", "researcher", "strategist"]
        votes: List[Dict[str, Any]] = []
        for role_name in pre_gen_roles:
            role = self._weighted_role(VOTING_ROLES[role_name], weights)
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

        weights = await self.refresh_role_weights()
        post_gen_roles = ["editor", "critic", "value_predictor"]
        votes: List[Dict[str, Any]] = []
        for role_name in post_gen_roles:
            role = self._weighted_role(VOTING_ROLES[role_name], weights)
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
    # Hook dedup (W6) — simhash Hamming distance against recent hooks
    # ------------------------------------------------------------------

    async def check_hook_duplicate(
        self,
        *,
        character_id: str,
        hook_text: str,
        days: int = 14,
        hamming_threshold: int = 14,
        exclude_carousel_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Return {is_duplicate, matched_carousel_id, distance} over recent hooks.

        A hook is "duplicate" when its simhash is within Hamming `hamming_threshold`
        (default 14 bits out of 64 ~= 22% bit divergence) of any carousel shipped
        for this character in the last `days` days. Threshold tuned empirically
        for this simhash implementation: near-identical hooks score ~10-12 bits,
        unrelated hooks score ~30+ bits. Used by the carousel graph to reject
        overly-similar hooks and route back to retry with a different angle.
        """
        if not hook_text.strip():
            return {"is_duplicate": False, "matched_carousel_id": None, "distance": None}

        candidate_hash = hook_simhash(hook_text)
        cutoff = datetime.now(timezone.utc) - _timedelta_days(days)
        async with get_session() as session:
            stmt = (
                select(CharacterCarouselModel.id, CharacterCarouselModel.hook_text)
                .where(CharacterCarouselModel.character_id == character_id)
                .where(CharacterCarouselModel.created_at >= cutoff)
                .where(CharacterCarouselModel.hook_text.isnot(None))
            )
            if exclude_carousel_id:
                stmt = stmt.where(CharacterCarouselModel.id != exclude_carousel_id)
            res = await session.execute(stmt)
            rows = list(res.all())

        best_distance: Optional[int] = None
        best_carousel: Optional[str] = None
        for row_id, prev_hook in rows:
            if not prev_hook:
                continue
            d = hamming_distance(candidate_hash, hook_simhash(prev_hook))
            if best_distance is None or d < best_distance:
                best_distance = d
                best_carousel = row_id
            if d <= hamming_threshold:
                return {
                    "is_duplicate": True,
                    "matched_carousel_id": row_id,
                    "distance": d,
                }
        return {
            "is_duplicate": False,
            "matched_carousel_id": best_carousel,
            "distance": best_distance,
        }

    # ------------------------------------------------------------------
    # Rubric (W3) — structured post-generation QC with pass/fail gates
    # ------------------------------------------------------------------

    async def rubric_for_carousel(
        self,
        *,
        carousel_id: str,
        hook: str,
        slides_preview: List[str],
        angle: str,
        feedback_on_previous_attempt: Optional[List[str]] = None,
    ) -> SwarmRubric:
        """Emit a structured SwarmRubric for a drafted carousel.

        Does not persist (the carousel graph persists via CharacterCarouselModel.rubric).
        Falls back to a permissive default-pass rubric with a flag in `issues` on
        any LLM/parse failure so the pipeline can still progress.
        """
        slides_line = "\n".join(f"- {s[:180]}" for s in slides_preview[:6])
        feedback_line = ""
        if feedback_on_previous_attempt:
            feedback_line = (
                "Previous attempt was rejected with issues: "
                + "; ".join(feedback_on_previous_attempt[:6])
                + ". Be explicit about whether those issues are now resolved.\n"
            )
        user_prompt = (
            f"{feedback_line}"
            f"Angle: {angle}\n"
            f"Hook: {hook}\n"
            f"Slides:\n{slides_line}\n\n"
            "Score the rubric. Return JSON only."
        )
        try:
            raw = await self._llm.chat(
                prompt=user_prompt,
                system=RUBRIC_SYSTEM,
                task_type="council_ceo",
                temperature=0.3,
                max_tokens=1200,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("rubric_call_failed", carousel_id=carousel_id, error=str(e)[:200])
            return SwarmRubric(issues=[f"rubric_llm_failed: {str(e)[:100]}"])

        parsed = _parse_rubric(raw)
        if parsed is None:
            logger.warning("rubric_parse_failed", carousel_id=carousel_id, raw_preview=raw[:200])
            return SwarmRubric(issues=["rubric_parse_failed"])
        return parsed

    # ------------------------------------------------------------------
    # Outcome calibration (back-fills actual engagement onto predictions)
    # ------------------------------------------------------------------

    async def run_calibration(self, lookback_days: int = 30) -> Dict[str, Any]:
        """Recompute per-role weights from recent prediction outcomes.

        For each role with outcome-recorded predictions in the window:
          - brier = mean((predicted_engagement/100 - actual/100)^2)
          - rank_correlation = Pearson between predicted and actual (simple approximation)
          - raw_skill = max(0, 1 - brier) * max(0, (rank_correlation + 1) / 2)

        Weights across roles are normalized so they sum to 1.0. Roles with fewer
        than 5 samples retain their static VOTING_ROLES weight.

        Persists to swarm_role_weights. Returns a summary dict.
        """
        since = datetime.now(timezone.utc) - _timedelta_days(lookback_days)
        async with get_session() as session:
            res = await session.execute(
                select(AgentPredictionModel)
                .where(AgentPredictionModel.outcome_engagement.isnot(None))
                .where(AgentPredictionModel.created_at >= since)
            )
            rows = list(res.scalars().all())

        by_role: Dict[str, List[AgentPredictionModel]] = {}
        for row in rows:
            by_role.setdefault(row.role_name, []).append(row)

        raw_skill: Dict[str, float] = {}
        diagnostics: Dict[str, Dict[str, float]] = {}
        for role_name, role in VOTING_ROLES.items():
            samples = by_role.get(role_name, [])
            if len(samples) < 5:
                raw_skill[role_name] = role.weight  # keep static default
                diagnostics[role_name] = {"sample_size": len(samples), "kept_default": 1.0}
                continue
            preds = [s.predicted_engagement / 100.0 for s in samples]
            actuals = [float(s.outcome_engagement) / 100.0 for s in samples]
            brier = sum((p - a) ** 2 for p, a in zip(preds, actuals)) / len(preds)
            rho = _pearson(preds, actuals)
            skill = max(0.01, (1.0 - brier)) * max(0.01, (rho + 1.0) / 2.0)
            raw_skill[role_name] = skill
            diagnostics[role_name] = {
                "sample_size": float(len(samples)),
                "brier_score": round(brier, 4),
                "rank_correlation": round(rho, 4),
                "raw_skill": round(skill, 4),
            }

        total = sum(raw_skill.values()) or 1.0
        new_weights = {k: v / total for k, v in raw_skill.items()}

        async with get_session() as session:
            for role_name, weight in new_weights.items():
                diag = diagnostics.get(role_name, {})
                existing = await session.get(SwarmRoleWeightModel, role_name)
                if existing is None:
                    row = SwarmRoleWeightModel(
                        role_name=role_name,
                        weight=weight,
                        brier_score=diag.get("brier_score"),
                        rank_correlation=diag.get("rank_correlation"),
                        sample_size=int(diag.get("sample_size", 0)),
                        updated_at=datetime.now(timezone.utc),
                        role_metadata={"raw_skill": diag.get("raw_skill")} if "raw_skill" in diag else {},
                    )
                    session.add(row)
                else:
                    existing.weight = weight
                    existing.brier_score = diag.get("brier_score")
                    existing.rank_correlation = diag.get("rank_correlation")
                    existing.sample_size = int(diag.get("sample_size", 0))
                    existing.updated_at = datetime.now(timezone.utc)
                    if "raw_skill" in diag:
                        existing.role_metadata = {"raw_skill": diag.get("raw_skill")}
            await session.commit()

        # Invalidate cache so next vote picks up new weights
        self._weights_loaded_at = None
        logger.info("swarm_calibration_complete", weights=new_weights, lookback_days=lookback_days)
        return {"weights": new_weights, "diagnostics": diagnostics, "samples_total": len(rows)}

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
