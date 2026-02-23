"""
TikTok Shop Agent Graph.

A LangGraph StateGraph that orchestrates the full TikTok Shop pipeline:
research -> score -> approve -> plan content -> generate scripts -> queue generation -> track performance.

This is a separate graph from the main orchestration graph. The main graph's
tiktok_node delegates to this agent for pipeline operations.
"""

from datetime import datetime, timezone
from typing import TypedDict, List, Dict, Any, Optional, Literal
import structlog

from langgraph.graph import StateGraph, END

logger = structlog.get_logger()


# ============================================
# STATE
# ============================================

class TikTokAgentState(TypedDict, total=False):
    """State for the TikTok Shop agent pipeline."""
    mode: str  # full, research_only, content_only, performance_only
    phase: str  # current phase name
    cycle_id: str
    # Research
    products_discovered: int
    high_opportunity_ids: List[str]
    # Approval
    auto_approved_count: int
    pending_count: int
    # Content
    approved_product_ids: List[str]
    scripts_generated: List[str]
    generation_jobs: List[str]
    # Performance
    performance_synced: bool
    improvement_cycle_run: bool
    # Metadata
    errors: List[str]
    result_summary: str


# ============================================
# NODES
# ============================================

async def research_node(state: TikTokAgentState) -> dict:
    """Node 1: Run product discovery via SearXNG + heuristic scoring."""
    logger.info("tiktok_agent_research_start")
    errors = list(state.get("errors", []))

    try:
        from app.services.tiktok_shop_service import get_tiktok_shop_service
        service = get_tiktok_shop_service()
        result = await service.run_daily_research_cycle()

        return {
            "phase": "scoring",
            "products_discovered": result.products_discovered,
            "high_opportunity_ids": [],  # Will be populated by scoring node
            "errors": errors + result.errors,
        }
    except Exception as e:
        logger.error("tiktok_agent_research_failed", error=str(e))
        errors.append(f"Research failed: {e}")
        return {"phase": "scoring", "products_discovered": 0, "errors": errors}


async def scoring_node(state: TikTokAgentState) -> dict:
    """Node 2: Run LLM analysis on pending approval products."""
    logger.info("tiktok_agent_scoring_start")
    errors = list(state.get("errors", []))

    try:
        from app.services.tiktok_shop_service import get_tiktok_shop_service
        service = get_tiktok_shop_service()
        pending = await service.list_pending(limit=20)
        high_ids = [p.id for p in pending if p.opportunity_score >= 70]

        # Run LLM analysis on top products that haven't been analyzed
        analyzed = 0
        for product in pending[:10]:
            if not product.llm_analysis:
                try:
                    await service._llm_analyze_product(product.id)
                    analyzed += 1
                except Exception as e:
                    errors.append(f"LLM scoring failed for {product.id}: {e}")

        logger.info("tiktok_agent_scoring_complete", analyzed=analyzed, high_opp=len(high_ids))
        return {
            "phase": "approval_check",
            "high_opportunity_ids": high_ids,
            "errors": errors,
        }
    except Exception as e:
        logger.error("tiktok_agent_scoring_failed", error=str(e))
        errors.append(f"Scoring failed: {e}")
        return {"phase": "approval_check", "high_opportunity_ids": [], "errors": errors}


async def approval_check_node(state: TikTokAgentState) -> dict:
    """Node 3: Auto-approve high-confidence products (>= 85 score)."""
    logger.info("tiktok_agent_approval_check_start")
    errors = list(state.get("errors", []))

    try:
        from app.services.tiktok_shop_service import get_tiktok_shop_service
        service = get_tiktok_shop_service()

        # Auto-approve high confidence
        auto_approved = await service.auto_approve_high_confidence(threshold=85.0)

        # Count remaining pending
        pending = await service.list_pending()
        pending_count = len(pending)

        logger.info("tiktok_agent_approval_check_complete",
                     auto_approved=auto_approved, still_pending=pending_count)
        return {
            "phase": "content_planning",
            "auto_approved_count": auto_approved,
            "pending_count": pending_count,
            "errors": errors,
        }
    except Exception as e:
        logger.error("tiktok_agent_approval_failed", error=str(e))
        errors.append(f"Approval check failed: {e}")
        return {"phase": "content_planning", "auto_approved_count": 0, "pending_count": 0, "errors": errors}


async def content_planning_node(state: TikTokAgentState) -> dict:
    """Node 4: Create content topics for approved products that don't have them."""
    logger.info("tiktok_agent_content_planning_start")
    errors = list(state.get("errors", []))

    try:
        from app.services.tiktok_shop_service import get_tiktok_shop_service
        service = get_tiktok_shop_service()

        # Get approved products without content topics
        approved = await service.list_products(status="approved", limit=20)
        needs_topic = [p for p in approved if not p.linked_content_topic_id]

        approved_ids = []
        for product in needs_topic[:5]:
            try:
                # Auto-create content topics
                await service._auto_create_content_topics([{
                    "id": product.id,
                    "name": product.name,
                    "niche": product.niche or "general",
                }])
                approved_ids.append(product.id)
            except Exception as e:
                errors.append(f"Content planning failed for {product.name}: {e}")

        # Also include approved products that already have topics
        for p in approved:
            if p.linked_content_topic_id and p.id not in approved_ids:
                approved_ids.append(p.id)

        logger.info("tiktok_agent_content_planning_complete", planned=len(approved_ids))
        return {
            "phase": "script_generation",
            "approved_product_ids": approved_ids,
            "errors": errors,
        }
    except Exception as e:
        logger.error("tiktok_agent_content_planning_failed", error=str(e))
        errors.append(f"Content planning failed: {e}")
        return {"phase": "script_generation", "approved_product_ids": [], "errors": errors}


async def script_generation_node(state: TikTokAgentState) -> dict:
    """Node 5: Generate faceless video scripts for approved products."""
    logger.info("tiktok_agent_script_generation_start")
    errors = list(state.get("errors", []))
    approved_ids = state.get("approved_product_ids", [])

    scripts_generated = []
    try:
        from app.services.tiktok_video_service import get_tiktok_video_service
        from app.models.tiktok_content import VideoTemplateType
        video_service = get_tiktok_video_service()

        # Select template based on product (rotate through templates)
        templates = list(VideoTemplateType)
        for i, product_id in enumerate(approved_ids[:5]):
            try:
                template = templates[i % len(templates)]
                script = await video_service.generate_video_script(product_id, template)
                if script:
                    scripts_generated.append(script.id)
            except Exception as e:
                errors.append(f"Script generation failed for {product_id}: {e}")

        logger.info("tiktok_agent_script_generation_complete", scripts=len(scripts_generated))
    except Exception as e:
        logger.error("tiktok_agent_script_generation_failed", error=str(e))
        errors.append(f"Script generation failed: {e}")

    return {
        "phase": "content_generation",
        "scripts_generated": scripts_generated,
        "errors": errors,
    }


async def content_generation_node(state: TikTokAgentState) -> dict:
    """Node 6: Queue scripts for AIContentTools video generation."""
    logger.info("tiktok_agent_content_generation_start")
    errors = list(state.get("errors", []))
    script_ids = state.get("scripts_generated", [])

    generation_jobs = []
    try:
        from app.services.tiktok_video_service import get_tiktok_video_service
        video_service = get_tiktok_video_service()

        for script_id in script_ids:
            try:
                queue_item = await video_service.queue_for_generation(script_id)
                if queue_item:
                    generation_jobs.append(queue_item.id)
            except Exception as e:
                errors.append(f"Queue failed for script {script_id}: {e}")

        logger.info("tiktok_agent_content_generation_complete", queued=len(generation_jobs))
    except Exception as e:
        logger.error("tiktok_agent_content_generation_failed", error=str(e))
        errors.append(f"Content generation failed: {e}")

    return {
        "phase": "performance_tracking",
        "generation_jobs": generation_jobs,
        "errors": errors,
    }


async def performance_tracking_node(state: TikTokAgentState) -> dict:
    """Node 7: Sync performance metrics and run improvement cycle."""
    logger.info("tiktok_agent_performance_tracking_start")
    errors = list(state.get("errors", []))

    synced = False
    improved = False
    try:
        from app.services.content_agent_service import get_content_agent_service
        content_service = get_content_agent_service()

        # Sync performance
        try:
            await content_service.sync_performance_metrics()
            synced = True
        except Exception as e:
            errors.append(f"Performance sync failed: {e}")

        # Run improvement cycle
        try:
            await content_service.run_improvement_cycle()
            improved = True
        except Exception as e:
            errors.append(f"Improvement cycle failed: {e}")

    except Exception as e:
        errors.append(f"Performance tracking failed: {e}")

    # Build result summary
    summary_parts = []
    if state.get("products_discovered", 0) > 0:
        summary_parts.append(f"Discovered {state['products_discovered']} products")
    if state.get("auto_approved_count", 0) > 0:
        summary_parts.append(f"Auto-approved {state['auto_approved_count']}")
    if state.get("pending_count", 0) > 0:
        summary_parts.append(f"{state['pending_count']} pending your review")
    if state.get("scripts_generated"):
        summary_parts.append(f"Generated {len(state['scripts_generated'])} video scripts")
    if state.get("generation_jobs"):
        summary_parts.append(f"Queued {len(state['generation_jobs'])} videos for generation")
    if synced:
        summary_parts.append("Performance metrics synced")
    if errors:
        summary_parts.append(f"{len(errors)} errors encountered")

    result_summary = ". ".join(summary_parts) if summary_parts else "Pipeline completed with no actions taken."

    logger.info("tiktok_agent_pipeline_complete", summary=result_summary)
    return {
        "phase": "complete",
        "performance_synced": synced,
        "improvement_cycle_run": improved,
        "result_summary": result_summary,
        "errors": errors,
    }


# ============================================
# ROUTING
# ============================================

def route_by_mode(state: TikTokAgentState) -> str:
    """Route based on pipeline mode."""
    mode = state.get("mode", "full")
    if mode == "research_only":
        return "research"
    elif mode == "content_only":
        return "content_planning"
    elif mode == "performance_only":
        return "performance_tracking"
    return "research"  # full mode


def route_after_approval(state: TikTokAgentState) -> str:
    """After approval check, decide whether to continue to content or skip."""
    mode = state.get("mode", "full")
    approved_ids = state.get("approved_product_ids", [])

    if mode == "research_only":
        return END
    return "content_planning"


def route_after_performance(state: TikTokAgentState) -> str:
    """After performance tracking, always end."""
    return END


# ============================================
# GRAPH BUILDER
# ============================================

def build_tiktok_agent_graph(checkpointer=None) -> StateGraph:
    """Build the TikTok Shop agent pipeline graph."""
    graph = StateGraph(TikTokAgentState)

    # Add nodes
    graph.add_node("research", research_node)
    graph.add_node("scoring", scoring_node)
    graph.add_node("approval_check", approval_check_node)
    graph.add_node("content_planning", content_planning_node)
    graph.add_node("script_generation", script_generation_node)
    graph.add_node("content_generation", content_generation_node)
    graph.add_node("performance_tracking", performance_tracking_node)

    # Entry point routes by mode
    graph.set_conditional_entry_point(route_by_mode, {
        "research": "research",
        "content_planning": "content_planning",
        "performance_tracking": "performance_tracking",
    })

    # Linear flow for full pipeline
    graph.add_edge("research", "scoring")
    graph.add_edge("scoring", "approval_check")
    graph.add_edge("approval_check", "content_planning")
    graph.add_edge("content_planning", "script_generation")
    graph.add_edge("script_generation", "content_generation")
    graph.add_edge("content_generation", "performance_tracking")
    graph.add_edge("performance_tracking", END)

    compiled = graph.compile(checkpointer=checkpointer)
    return compiled


# ============================================
# CONVENIENCE FUNCTIONS
# ============================================

_compiled_graph = None


async def get_tiktok_agent_graph():
    """Get or create the compiled TikTok agent graph."""
    global _compiled_graph
    if _compiled_graph is None:
        try:
            from app.infrastructure.checkpoint import get_checkpointer
            checkpointer = await get_checkpointer()
        except Exception:
            checkpointer = None
        _compiled_graph = build_tiktok_agent_graph(checkpointer=checkpointer)
    return _compiled_graph


async def invoke_tiktok_pipeline(
    mode: str = "full",
    thread_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Invoke the TikTok Shop agent pipeline.

    Args:
        mode: Pipeline mode - "full", "research_only", "content_only", "performance_only"
        thread_id: Optional thread ID for state persistence

    Returns:
        Pipeline result dict with summary and stats
    """
    import uuid
    cycle_id = f"ttpl-{uuid.uuid4().hex[:8]}"
    if not thread_id:
        thread_id = cycle_id

    logger.info("tiktok_pipeline_invoke", mode=mode, cycle_id=cycle_id, thread_id=thread_id)

    graph = await get_tiktok_agent_graph()

    initial_state: TikTokAgentState = {
        "mode": mode,
        "phase": "starting",
        "cycle_id": cycle_id,
        "products_discovered": 0,
        "high_opportunity_ids": [],
        "auto_approved_count": 0,
        "pending_count": 0,
        "approved_product_ids": [],
        "scripts_generated": [],
        "generation_jobs": [],
        "performance_synced": False,
        "improvement_cycle_run": False,
        "errors": [],
        "result_summary": "",
    }

    config = {"configurable": {"thread_id": thread_id}}

    try:
        result = await graph.ainvoke(initial_state, config=config)
        return {
            "cycle_id": cycle_id,
            "mode": mode,
            "status": "completed",
            "summary": result.get("result_summary", ""),
            "products_discovered": result.get("products_discovered", 0),
            "auto_approved": result.get("auto_approved_count", 0),
            "pending_review": result.get("pending_count", 0),
            "scripts_generated": len(result.get("scripts_generated", [])),
            "generation_jobs": len(result.get("generation_jobs", [])),
            "errors": result.get("errors", []),
        }
    except Exception as e:
        logger.error("tiktok_pipeline_failed", error=str(e), cycle_id=cycle_id)
        return {
            "cycle_id": cycle_id,
            "mode": mode,
            "status": "failed",
            "summary": f"Pipeline failed: {e}",
            "errors": [str(e)],
        }
