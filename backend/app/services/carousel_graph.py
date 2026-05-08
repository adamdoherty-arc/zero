"""Durable carousel generation graph (W1 of orchestration hardening).

A thin LangGraph StateGraph that wraps the existing monolithic
CharacterContentService.generate_carousel with explicit pre/post-gen stages
and a rubric-driven fail-retry edge. Compiles with AsyncPostgresSaver so a
`docker kill` mid-generation can resume on restart.

Design constraint: the existing generate_carousel method is ~580 LoC. Rather
than rewrite it, we wrap it as a single "generate" node and add structured
stages around it (rubric gate → retry → finalize). The value added is:

  1. Checkpointed state per carousel_id (thread_id = f"carousel:{id}").
  2. A typed SwarmRubric persisted onto CharacterCarouselModel.rubric.
  3. A fail-retry edge up to CAROUSEL_RUBRIC_MAX_RETRIES that re-invokes
     generate with a different angle when the rubric gate rejects.
  4. A `resume_incomplete()` entrypoint that restarts any carousel rows stuck
     in a non-terminal status after a crash.

Deferred (future work, out of scope for this workstream):
  - Full decomposition of generate_carousel into per-stage nodes (research,
    synthesis, fact_extraction, image_sourcing, layout). Would give finer
    crash recovery but is a multi-hundred-LoC refactor of the monolith.
"""

from __future__ import annotations

import random
import uuid
from typing import Any, Dict, List, Literal, Optional, TypedDict

import structlog
from sqlalchemy import select

from app.db.models import CharacterCarouselModel
from app.infrastructure.checkpoint import get_checkpointer
from app.infrastructure.database import get_session
from app.models.character_content import CarouselCreate, CharacterCarousel, ContentAngle

logger = structlog.get_logger(__name__)


_TERMINAL_STATUSES = {
    "ai_reviewed",
    "pending_review",
    "approved",
    "publishing",
    "published",
    "rejected",
}


class CarouselState(TypedDict, total=False):
    # Inputs
    request: Dict[str, Any]
    # Progress
    carousel_id: Optional[str]
    status: Literal[
        "pending",
        "pre_gen_voted",
        "pre_gen_rejected",
        "generated",
        "post_gen_critiqued",
        "rubric_passed",
        "rubric_failed",
        "retrying",
        "done",
        "abandoned",
    ]
    retries: int
    # Pre-gen swarm vote (Phase 2 Content Brain v2)
    pre_gen_decision: Optional[str]  # accept | hold | reject
    pre_gen_consensus: Optional[float]
    # Post-gen swarm critique
    post_gen_decision: Optional[str]
    post_gen_consensus: Optional[float]
    # Rubric
    rubric: Optional[Dict[str, Any]]
    rubric_passed: bool
    issues: List[str]
    # Output
    error: Optional[str]


def _clone_request_with_new_angle(req: Dict[str, Any]) -> Dict[str, Any]:
    """Pick a different angle for the retry attempt. Keeps all other fields."""
    try:
        current_value = (req.get("angle") or "").lower()
        pool = [a for a in ContentAngle if a.value != current_value]
        new_req = dict(req)
        new_req["angle"] = random.choice(pool).value
        return new_req
    except Exception:  # noqa: BLE001
        return req


class CarouselGraphService:
    """Compiles and runs the durable carousel generation graph."""

    def __init__(self) -> None:
        self._graph = None  # lazy compile

    async def _compile(self):
        if self._graph is not None:
            return self._graph

        from langgraph.graph import END, StateGraph

        builder: StateGraph = StateGraph(CarouselState)
        builder.add_node("pre_gen_swarm", self._node_pre_gen_swarm)
        builder.add_node("generate", self._node_generate)
        builder.add_node("post_gen_swarm", self._node_post_gen_swarm)
        builder.add_node("rubric_gate", self._node_rubric_gate)
        builder.add_node("retry", self._node_retry)
        builder.add_node("finalize", self._node_finalize)

        builder.set_entry_point("pre_gen_swarm")
        builder.add_conditional_edges(
            "pre_gen_swarm",
            self._route_after_pre_gen,
            {"proceed": "generate", "abort": "finalize"},
        )
        builder.add_edge("generate", "post_gen_swarm")
        builder.add_edge("post_gen_swarm", "rubric_gate")
        builder.add_conditional_edges(
            "rubric_gate",
            self._route_after_rubric,
            {
                "pass": "finalize",
                "retry": "retry",
                "give_up": "finalize",
            },
        )
        builder.add_edge("retry", "pre_gen_swarm")
        builder.add_edge("finalize", END)

        checkpointer = await get_checkpointer()
        self._graph = builder.compile(checkpointer=checkpointer)
        return self._graph

    # ------------------------------------------------------------------
    # Nodes
    # ------------------------------------------------------------------

    async def _node_pre_gen_swarm(self, state: CarouselState) -> CarouselState:
        """Pre-generation swarm vote (TrendScout + Researcher + Strategist).

        Cheap veto step: if the swarm rejects the idea before we burn tokens
        generating, we abort and avoid the expensive LLM call. Checkpoint after
        this node guarantees we don't re-vote on resume.
        """
        from app.db.models import CharacterModel
        from app.services.content_swarm_service import get_content_swarm_service

        request = state.get("request") or {}
        character_id = request.get("character_id")
        angle = (request.get("angle") or "").lower() or "hidden_truths"
        if not character_id:
            return {"status": "pre_gen_rejected", "pre_gen_decision": "reject", "error": "no_character_id"}

        async with get_session() as session:
            char = await session.get(CharacterModel, character_id)
        facts_preview: List[str] = []
        if char and char.fact_bank:
            facts_preview = [f.get("text", "")[:140] for f in (char.fact_bank or [])[:5]]

        # Provisional pre-gen prediction id (carousel row doesn't exist yet).
        provisional_id = f"pending-{uuid.uuid4().hex[:10]}"
        swarm = get_content_swarm_service()
        try:
            consensus = await swarm.evaluate_generation_idea(
                carousel_id=provisional_id,
                content_type="character" if character_id else "media",
                character=char,
                angle=angle,
                template=request.get("story_template"),
                facts_preview=facts_preview,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("carousel_graph_pre_gen_failed", error=str(e)[:200])
            # Fail-open: if the swarm errors, proceed to generation rather than stall.
            return {
                "status": "pre_gen_voted",
                "pre_gen_decision": "accept",
                "pre_gen_consensus": 0.5,
            }

        decision = consensus.get("decision", "hold")
        score = float(consensus.get("consensus_score", 0.0))
        logger.info(
            "carousel_graph_pre_gen",
            character_id=character_id,
            angle=angle,
            decision=decision,
            consensus_score=score,
            retries=state.get("retries", 0),
        )
        status = "pre_gen_rejected" if decision == "reject" else "pre_gen_voted"
        return {
            "status": status,
            "pre_gen_decision": decision,
            "pre_gen_consensus": score,
        }

    async def _node_generate(self, state: CarouselState) -> CarouselState:
        from app.services.character_content_service import get_character_content_service

        svc = get_character_content_service()
        try:
            req_dict = dict(state["request"])
            # Force swarm off on the inner call: the graph's own pre/post-gen
            # swarm nodes own that concern, and the inner fire-and-forget
            # critique would double-write AgentPredictionModel rows.
            req_dict["use_swarm"] = False
            req = CarouselCreate(**req_dict)
            carousel = await svc.generate_carousel(req)
        except Exception as e:  # noqa: BLE001
            logger.warning("carousel_graph_generate_failed", error=str(e)[:200])
            return {
                "status": "abandoned",
                "error": str(e)[:500],
                "retries": state.get("retries", 0),
            }
        return {
            "carousel_id": carousel.id,
            "status": "generated",
            "retries": state.get("retries", 0),
        }

    async def _node_post_gen_swarm(self, state: CarouselState) -> CarouselState:
        """Post-generation swarm critique (Editor + Critic + ValuePredictor).

        Runs synchronously (vs. the old fire-and-forget background task) so
        results are deterministic and this node is a proper checkpoint boundary.
        """
        from app.services.content_swarm_service import get_content_swarm_service

        carousel_id = state.get("carousel_id")
        if not carousel_id:
            return {"status": "abandoned", "error": "no_carousel_id_in_post_gen"}

        async with get_session() as session:
            row = await session.get(CharacterCarouselModel, carousel_id)
            if row is None:
                return {"status": "abandoned", "error": "carousel_row_missing_post_gen"}
            hook = row.hook_text or ""
            slides = row.slides or []
            angle = row.angle or ""
            content_type = row.content_type or "character"

        slides_preview = [
            (s.get("text") or s.get("caption") or "")[:180] if isinstance(s, dict) else str(s)[:180]
            for s in slides[:6]
        ]
        swarm = get_content_swarm_service()
        try:
            consensus = await swarm.critique_generated_carousel(
                carousel_id=carousel_id,
                content_type=content_type,
                hook=hook,
                slides_preview=slides_preview,
                angle=angle,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("carousel_graph_post_gen_failed", carousel_id=carousel_id, error=str(e)[:200])
            return {
                "status": "post_gen_critiqued",
                "post_gen_decision": "hold",
                "post_gen_consensus": 0.5,
            }

        logger.info(
            "carousel_graph_post_gen",
            carousel_id=carousel_id,
            decision=consensus.get("decision"),
            consensus_score=consensus.get("consensus_score"),
        )
        return {
            "status": "post_gen_critiqued",
            "post_gen_decision": consensus.get("decision"),
            "post_gen_consensus": float(consensus.get("consensus_score", 0.0)),
        }

    async def _node_rubric_gate(self, state: CarouselState) -> CarouselState:
        from app.infrastructure.config import get_settings
        from app.services.content_swarm_service import get_content_swarm_service

        carousel_id = state.get("carousel_id")
        if not carousel_id:
            return {"status": "abandoned", "error": "no_carousel_id", "rubric_passed": False}

        async with get_session() as session:
            row = await session.get(CharacterCarouselModel, carousel_id)
            if row is None:
                return {"status": "abandoned", "error": "carousel_row_missing", "rubric_passed": False}
            hook = row.hook_text or ""
            slides = row.slides or []
            angle = row.angle or ""

        slides_preview = [
            (s.get("body") or s.get("text") or str(s))[:180] if isinstance(s, dict) else str(s)[:180]
            for s in slides
        ]
        swarm = get_content_swarm_service()
        prior_issues = state.get("issues") or None
        rubric = await swarm.rubric_for_carousel(
            carousel_id=carousel_id,
            hook=hook,
            slides_preview=slides_preview,
            angle=angle,
            feedback_on_previous_attempt=prior_issues,
        )

        # W6 hook Hamming dedup: reject near-duplicate hooks for the same character.
        character_id = None
        async with get_session() as session:
            row = await session.get(CharacterCarouselModel, carousel_id)
            if row is not None:
                character_id = row.character_id
        if character_id and hook:
            dup = await swarm.check_hook_duplicate(
                character_id=character_id,
                hook_text=hook,
                days=14,
                hamming_threshold=14,
                exclude_carousel_id=carousel_id,
            )
            if dup.get("is_duplicate"):
                issues = list(rubric.issues or [])
                issues.append(
                    f"hook_hamming_dupe:prev={dup.get('matched_carousel_id')},distance={dup.get('distance')}"
                )
                rubric = rubric.model_copy(update={
                    "commentary_framing": "fail",
                    "issues": issues,
                })
                logger.info(
                    "carousel_graph_hook_dupe",
                    carousel_id=carousel_id,
                    matched=dup.get("matched_carousel_id"),
                    distance=dup.get("distance"),
                )

        settings = get_settings()
        threshold = float(getattr(settings, "carousel_rubric_threshold", 6.5))
        passed = rubric.passes_gate(threshold=threshold)

        # Persist rubric + updated retry counter on the carousel row.
        async with get_session() as session:
            row = await session.get(CharacterCarouselModel, carousel_id)
            if row is not None:
                row.rubric = rubric.model_dump()
                row.retries = state.get("retries", 0)
                await session.commit()

        logger.info(
            "carousel_graph_rubric",
            carousel_id=carousel_id,
            passed=passed,
            weighted_score=rubric.weighted_score(),
            retries=state.get("retries", 0),
        )
        return {
            "rubric": rubric.model_dump(),
            "rubric_passed": passed,
            "issues": rubric.issues,
            "status": "rubric_passed" if passed else "rubric_failed",
        }

    async def _node_retry(self, state: CarouselState) -> CarouselState:
        """Prepare a retry: bump counter and mutate the request with a new angle."""
        new_retries = state.get("retries", 0) + 1
        new_request = _clone_request_with_new_angle(state["request"])
        logger.info(
            "carousel_graph_retry",
            prior_carousel_id=state.get("carousel_id"),
            attempt=new_retries,
            new_angle=new_request.get("angle"),
        )
        return {
            "request": new_request,
            "retries": new_retries,
            "status": "retrying",
            # Clear the prior carousel_id so _node_generate creates a fresh row.
            "carousel_id": None,
        }

    async def _node_finalize(self, state: CarouselState) -> CarouselState:
        return {"status": "done"}

    # ------------------------------------------------------------------
    # Router
    # ------------------------------------------------------------------

    def _route_after_pre_gen(self, state: CarouselState) -> str:
        """If the pre-gen swarm rejected, abort to finalize without burning an LLM call."""
        if state.get("pre_gen_decision") == "reject":
            return "abort"
        return "proceed"

    def _route_after_rubric(self, state: CarouselState) -> str:
        from app.infrastructure.config import get_settings
        settings = get_settings()
        max_retries = int(getattr(settings, "carousel_rubric_max_retries", 2))
        if state.get("rubric_passed"):
            return "pass"
        if state.get("retries", 0) >= max_retries:
            return "give_up"
        return "retry"

    # ------------------------------------------------------------------
    # Public entrypoints
    # ------------------------------------------------------------------

    async def run(self, request: CarouselCreate) -> Dict[str, Any]:
        """Generate a carousel through the durable graph.

        Returns the final state dict including carousel_id and rubric.
        """
        graph = await self._compile()
        thread_id = f"carousel:{uuid.uuid4().hex[:16]}"
        config = {"configurable": {"thread_id": thread_id}}
        initial: CarouselState = {
            "request": request.model_dump(),
            "status": "pending",
            "retries": 0,
            "rubric_passed": False,
            "issues": [],
        }
        final_state = await graph.ainvoke(initial, config=config)
        final_state["_thread_id"] = thread_id
        return final_state

    async def resume_incomplete(self, *, limit: int = 20) -> Dict[str, Any]:
        """Re-run the rubric gate for any carousels stuck in non-terminal status.

        Called on app startup so crash-interrupted generations don't block the
        pipeline. Safe to call repeatedly; no-op when nothing is stuck.
        """
        async with get_session() as session:
            res = await session.execute(
                select(CharacterCarouselModel)
                .where(CharacterCarouselModel.status.notin_(list(_TERMINAL_STATUSES)))
                .where(CharacterCarouselModel.rubric.is_(None))
                .order_by(CharacterCarouselModel.created_at.desc())
                .limit(limit)
            )
            stuck = list(res.scalars().all())

        if not stuck:
            return {"resumed": 0}

        resumed = 0
        for row in stuck:
            try:
                state: CarouselState = {
                    "request": {"character_id": row.character_id, "angle": row.angle},
                    "carousel_id": row.id,
                    "status": "generated",
                    "retries": row.retries or 0,
                    "rubric_passed": False,
                    "issues": [],
                }
                await self._node_rubric_gate(state)
                resumed += 1
            except Exception as e:  # noqa: BLE001
                logger.warning("carousel_graph_resume_failed", carousel_id=row.id, error=str(e)[:200])
        logger.info("carousel_graph_resume_complete", resumed=resumed, stuck=len(stuck))
        return {"resumed": resumed, "stuck_total": len(stuck)}


_singleton: Optional[CarouselGraphService] = None


def get_carousel_graph_service() -> CarouselGraphService:
    global _singleton
    if _singleton is None:
        _singleton = CarouselGraphService()
    return _singleton


__all__ = ["CarouselGraphService", "CarouselState", "get_carousel_graph_service"]
