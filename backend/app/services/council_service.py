"""
Council of Agents Service.
Multi-agent debate and voting using diverse LLM providers for genuine reasoning diversity.
2-round protocol: independent positions → informed revision → final vote.
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

# Council voting roles with intentionally diverse providers.
# Provider diversity is configured via the central LLM router
# (router task types: council_ceo, council_researcher, council_analyst, council_validator).
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

    async def conduct_vote(self, decision_id: str) -> CouncilDecision:
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
                    temperature=0.5,
                    max_tokens=1024,
                )
                round1[role_id] = vote if isinstance(vote, dict) else {"position": "abstain", "reasoning": str(vote), "confidence": 50}
            except StructuredOutputError:
                round1[role_id] = {"position": "abstain", "reasoning": "Failed to evaluate", "confidence": 30}

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
                    temperature=0.3,
                    max_tokens=1024,
                )
                round2[role_id] = vote if isinstance(vote, dict) else {"position": "abstain", "reasoning": str(vote), "confidence": 50}
            except StructuredOutputError:
                round2[role_id] = round1[role_id]  # Keep round 1 vote

        rounds.append({"round": 2, "votes": round2})

        # Tally votes from Round 2
        position_counts = {"approve": 0, "reject": 0, "needs_revision": 0}
        total_confidence = 0.0
        for role_id, vote in round2.items():
            pos = vote.get("position", "abstain")
            if pos in position_counts:
                position_counts[pos] += 1
            total_confidence += float(vote.get("confidence", 50))

        # Decision = majority vote
        final_decision = max(position_counts, key=position_counts.get)
        avg_confidence = total_confidence / max(len(round2), 1)

        # Save
        async with get_session() as session:
            row = await session.get(CouncilDecisionModel, decision_id)
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

    async def list_decisions(self, status: Optional[str] = None, limit: int = 20) -> List[CouncilDecision]:
        async with get_session() as session:
            q = select(CouncilDecisionModel).order_by(CouncilDecisionModel.created_at.desc()).limit(limit)
            if status:
                q = q.where(CouncilDecisionModel.decision == status)
            result = await session.execute(q)
            return [_orm_to_decision(r) for r in result.scalars().all()]


@lru_cache()
def get_council_service() -> CouncilService:
    return CouncilService()
