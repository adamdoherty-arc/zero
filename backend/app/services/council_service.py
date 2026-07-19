"""
Council of Agents Service.
Multi-agent debate and voting: four role lenses (strategic / technical /
financial / risk) over a 2-round protocol — independent positions → informed
revision → final vote.

NOTE (RSN-A3): this docstring used to claim "diverse LLM providers for genuine
reasoning diversity". All four lanes currently resolve to the same model, so the
diversity today is one of PROMPT LENS, not provider. See the comment above
COUNCIL_ROLES before relying on the tally as independent judgment.
"""

import uuid
from datetime import datetime, timezone
from functools import lru_cache
from typing import List, Dict, Any, Optional

import structlog
from sqlalchemy import select

from app.infrastructure.database import get_session
from app.infrastructure.unified_llm_client import get_unified_llm_client, StructuredOutputError
from app.db.models import CouncilDecisionModel
from app.models.agent_company import CouncilDecision, CouncilProposal

logger = structlog.get_logger()

# Council voting roles.
#
# RSN-A3 (supervise zero 6a8c5562): this comment used to read "intentionally
# diverse providers", and the service docstring promised "genuine reasoning
# diversity". Neither is true today — all four assignments in
# app/models/llm.py resolve to the SAME model (bifrost/vllm-local/qwen3-chat);
# only council_ceo and council_researcher even carry a distinct fallback. The
# per-role temperatures (0.3 / 0.7 / 0.3 / 0.3) were the last remaining source
# of variance, and conduct_vote then overrode them with a hardcoded 0.5 and 0.3
# at the two call sites — so the "council" was one model at one temperature
# sampled four times, differing only by the system-prompt lens. A majority vote
# over correlated samples is not the independent judgment the tally implies.
#
# Fixed here: each role's ASSIGNED temperature is passed through instead of
# being overridden, restoring per-lens variance. Making the providers genuinely
# diverse is a separate call with real cost/latency consequences (it means
# routing some lanes off the local vLLM to paid or rate-limited lanes) — that
# assignment change is left to the operator rather than made silently here.
# Router task types: council_ceo, council_researcher, council_analyst, council_validator.
_ROLE_FALLBACK_TEMPERATURE = 0.5

COUNCIL_ROLES = {
    "ceo": {
        "task_type": "council_ceo",
        "lens": "strategic",
        "prompt": "You are the CEO. Evaluate from a strategic business perspective. Consider ROI, strategic alignment, and long-term impact.",
    },
    "researcher": {
        "task_type": "council_researcher",
        "lens": "technical",
        "prompt": "You are the Researcher. Evaluate from a technical and data perspective. Consider evidence quality, technical feasibility, and information gaps.",
    },
    "analyst": {
        "task_type": "council_analyst",
        "lens": "financial",
        "prompt": "You are the Analyst. Evaluate from a financial and market perspective. Consider costs, market dynamics, and quantitative evidence.",
    },
    "validator": {
        "task_type": "council_validator",
        "lens": "risk",
        "prompt": "You are the Validator. Evaluate from a risk and feasibility perspective. Consider failure modes, assumptions, and potential downsides.",
    },
}


def _role_temperature(task_type: str) -> float:
    """The temperature the router ASSIGNED to this council lane.

    RSN-A3: conduct_vote used to hardcode 0.5 (round 1) and 0.3 (round 2) at the
    call sites, silently discarding the per-role temperatures that are the only
    thing distinguishing the four lanes while they all point at one model.

    Read through the LIVE router (resolve_with_params), not the class defaults,
    so an operator edit to the persisted router_config.json actually takes
    effect here.
    """
    try:
        from app.infrastructure.llm_router import get_llm_router

        _model, assignment = get_llm_router().resolve_with_params(task_type)
        t = getattr(assignment, "temperature", None)
        if isinstance(t, (int, float)):
            return float(t)
    except Exception as e:  # noqa: BLE001 - a router hiccup must not kill a vote
        logger.warning("council_role_temperature_lookup_failed",
                       task_type=task_type, error=str(e))
    return _ROLE_FALLBACK_TEMPERATURE


def _orm_to_decision(row: CouncilDecisionModel) -> CouncilDecision:
    return CouncilDecision(
        id=row.id,
        topic=row.topic,
        context=row.context or {},
        proposer_role=row.proposer_role,
        rounds=row.rounds or [],
        votes=row.votes or {},
        decision=row.decision,
        confidence_score=row.confidence_score,
        created_at=row.created_at,
        decided_at=row.decided_at,
    )


class CouncilService:
    def __init__(self):
        self._llm = get_unified_llm_client()

    async def propose(self, req: CouncilProposal) -> CouncilDecision:
        """Create a council decision proposal."""
        decision_id = f"council-{uuid.uuid4().hex[:12]}"
        async with get_session() as session:
            row = CouncilDecisionModel(
                id=decision_id,
                topic=req.topic,
                context=req.context,
                proposer_role=req.proposer_role,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
        logger.info("council_proposed", decision_id=decision_id, topic=req.topic[:100])
        return _orm_to_decision(row)

    # RSN-A5 (supervise zero 6a8c5562): declared `-> CouncilDecision` while the
    # RSN-3 bail path below returns None. The lie is what hid the missing guard
    # from readers and type-checkers at the orchestration_graph call site.
    async def conduct_vote(self, decision_id: str) -> Optional[CouncilDecision]:
        """Run 2-round debate + vote protocol."""
        async with get_session() as session:
            row = await session.get(CouncilDecisionModel, decision_id)
            if not row:
                raise ValueError(f"Decision {decision_id} not found")

        topic = row.topic
        context_str = str(row.context or {})[:2000]
        rounds = []

        # Round 1: Independent positions
        round1 = {}
        for role_id, config in COUNCIL_ROLES.items():
            prompt = (
                f"Topic for council vote: {topic}\n"
                f"Context: {context_str}\n\n"
                f"{config['prompt']}\n\n"
                "State your position. Return JSON:\n"
                '{"position": "approve|reject|needs_revision", '
                '"reasoning": "your detailed reasoning", '
                '"confidence": 0-100, '
                '"key_concern": "your biggest concern or none"}'
            )
            try:
                vote = await self._llm.structured_chat(
                    prompt=prompt,
                    system=f"You are evaluating a proposal from the {config['lens']} perspective.",
                    task_type=config["task_type"],
                    temperature=_role_temperature(config["task_type"]),
                    max_tokens=1024,
                )
                round1[role_id] = vote if isinstance(vote, dict) else {"position": "abstain", "reasoning": str(vote), "confidence": 50}
            except StructuredOutputError:
                round1[role_id] = {"position": "abstain", "reasoning": "Failed to evaluate", "confidence": 30}
            except Exception as e:
                # F7 (mirrors RSN-8 in experiment_service.design_experiment): a
                # raw provider/network/timeout exception is not a
                # StructuredOutputError and was previously uncaught here,
                # aborting the whole conduct_vote call and losing every
                # already-computed Round-1 vote. Degrade this role to abstain
                # like the StructuredOutputError path, rather than raising.
                logger.warning("council_vote_provider_error", role=role_id, round=1, error=str(e))
                round1[role_id] = {"position": "abstain", "reasoning": "Provider error during evaluation", "confidence": 30}

        rounds.append({"round": 1, "votes": round1})

        # Round 2: Informed revision (each role sees Round 1)
        round1_summary = "\n".join(
            f"- {role}: {v.get('position', '?')} (confidence: {v.get('confidence', '?')}) — {v.get('reasoning', '')[:150]}"
            for role, v in round1.items()
        )

        round2 = {}
        for role_id, config in COUNCIL_ROLES.items():
            prompt = (
                f"Topic: {topic}\n\n"
                f"Round 1 positions from all council members:\n{round1_summary}\n\n"
                f"Your Round 1 position was: {round1[role_id].get('position', 'unknown')}\n\n"
                f"{config['prompt']}\n\n"
                "Having seen other positions, provide your FINAL vote. Return JSON:\n"
                '{"position": "approve|reject|needs_revision", '
                '"reasoning": "your final reasoning after considering others", '
                '"confidence": 0-100}'
            )
            try:
                vote = await self._llm.structured_chat(
                    prompt=prompt,
                    system=f"You are making your final vote from the {config['lens']} perspective.",
                    task_type=config["task_type"],
                    temperature=_role_temperature(config["task_type"]),
                    max_tokens=1024,
                )
                round2[role_id] = vote if isinstance(vote, dict) else {"position": "abstain", "reasoning": str(vote), "confidence": 50}
            except StructuredOutputError:
                round2[role_id] = round1[role_id]  # Keep round 1 vote
            except Exception as e:
                # F7 (same class as round 1 above): degrade to the round-1
                # vote rather than raising and losing the whole decision.
                logger.warning("council_vote_provider_error", role=role_id, round=2, error=str(e))
                round2[role_id] = round1[role_id]

        rounds.append({"round": 2, "votes": round2})

        # Tally votes from Round 2
        position_counts = {"approve": 0, "reject": 0, "needs_revision": 0}
        total_confidence = 0.0
        counted_votes = 0
        for role_id, vote in round2.items():
            # RSN-A4 (supervise zero 6a8c5562): `position` arrives as raw LLM
            # JSON, so "Approve", "approve ", and "needs revision" are all
            # routine outputs — and every one of them failed the `in
            # position_counts` test and was silently swallowed as a non-vote.
            # Two live consequences: four "Approve" votes tallied to zero and
            # forced needs_revision at confidence 0.0, and a casing split let a
            # decision finalize on half the council. The sibling `confidence`
            # field was already hardened for exactly this reason (RSN-1 below);
            # `position` — the field the entire tally rests on — was not.
            pos = str(vote.get("position", "abstain")).strip().lower()
            pos = pos.replace(" ", "_").replace("-", "_")
            if pos not in position_counts and pos != "abstain":
                logger.warning(
                    "council_vote_unrecognized_position",
                    role=role_id, position=vote.get("position"),
                )
            if pos in position_counts:
                position_counts[pos] += 1
                # Fix-115: only roles that cast a real vote contribute to the
                # confidence metric. Previously abstain/structured-output-failed
                # roles' default confidence (50) were summed but the average
                # still divided by the full role count, polluting the stored
                # confidence_score with non-voters.
                # RSN-1: the `confidence` field comes straight from LLM JSON and
                # is NOT guaranteed numeric — a model can emit null, "high", or
                # "85%". A bare float() then raised TypeError/ValueError out of
                # conduct_vote(), aborting the whole tally and leaving the
                # decision permanently unsaved. Coerce defensively; an
                # unparseable confidence falls back to the neutral 50.
                raw_conf = vote.get("confidence", 50)
                try:
                    conf = float(raw_conf)
                except (TypeError, ValueError):
                    conf = 50.0
                if conf != conf:  # NaN guard
                    conf = 50.0
                total_confidence += conf
                counted_votes += 1

        # Decision = majority vote. If every role abstained or failed
        # structured output in both rounds, all counts are 0 and max() would
        # return the first key ("approve") by dict-insertion order — a
        # degenerate deliberation must NOT silently auto-approve.
        if sum(position_counts.values()) == 0:
            final_decision = "needs_revision"
        else:
            _max_count = max(position_counts.values())
            _leaders = [p for p, c in position_counts.items() if c == _max_count]
            # A tie (e.g. 2 approve / 2 reject) must NOT silently auto-approve
            # via dict-insertion order (max() returns the first key). A
            # deadlocked council needs human revision, not an auto-pass.
            final_decision = _leaders[0] if len(_leaders) == 1 else "needs_revision"
        avg_confidence = total_confidence / max(counted_votes, 1)

        # Save
        async with get_session() as session:
            row = await session.get(CouncilDecisionModel, decision_id)
            if row is None:
                # RSN-3 (supervise f8574c6d): the row was read+guarded at the top
                # of conduct_vote (line ~87), but a concurrent delete between that
                # read and this write would make the bare `row.rounds = ...` below
                # raise AttributeError, aborting the tally with the decision
                # unsaved. Bail gracefully instead.
                logger.warning(
                    "council_decision_vanished_before_save", decision_id=decision_id
                )
                return None
            row.rounds = rounds
            row.votes = round2
            row.decision = final_decision
            row.confidence_score = round(avg_confidence, 1)
            row.decided_at = datetime.now(timezone.utc)
            await session.commit()

        logger.info(
            "council_decided",
            decision_id=decision_id,
            decision=final_decision,
            confidence=avg_confidence,
            votes=position_counts,
        )

        # Record to brain
        try:
            from app.services.zero_brain_service import get_zero_brain_service
            brain = get_zero_brain_service()
            await brain.record_interaction_outcome(
                domain="system", action_type="council_decision",
                action_id=decision_id, strategy_used="multi_role_debate",
                predicted_score=avg_confidence,
                metrics={"decision": final_decision, "votes": position_counts},
                text_for_memory=f"Council decided '{final_decision}' with {avg_confidence:.0f}% confidence. Votes: {position_counts}",
            )
        except Exception:
            pass

        return await self.get_decision(decision_id)

    async def get_decision(self, decision_id: str) -> Optional[CouncilDecision]:
        async with get_session() as session:
            row = await session.get(CouncilDecisionModel, decision_id)
            return _orm_to_decision(row) if row else None

    async def list_decisions(
        self, status: Optional[str] = None, pending_only: bool = False, limit: int = 20
    ) -> List[CouncilDecision]:
        async with get_session() as session:
            q = select(CouncilDecisionModel).order_by(CouncilDecisionModel.created_at.desc()).limit(limit)
            if pending_only:
                # A freshly proposed decision keeps `decision=None` until
                # conduct_vote() records an outcome (approve/reject/needs_revision).
                # The old caller passed status="proposed", which filtered the
                # `decision` column — a value it NEVER holds — so the voice/chat
                # "council vote" path matched nothing and was permanently dead.
                q = q.where(CouncilDecisionModel.decision.is_(None))
            elif status:
                q = q.where(CouncilDecisionModel.decision == status)
            result = await session.execute(q)
            return [_orm_to_decision(r) for r in result.scalars().all()]


@lru_cache()
def get_council_service() -> CouncilService:
    return CouncilService()
