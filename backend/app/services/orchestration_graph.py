"""
LangGraph Orchestration Gateway for Zero.
Sprint 53 Task 115: Create Zero supervisor StateGraph for request routing.

This module implements a LangGraph supervisor StateGraph that routes user
messages to specialized subgraphs: email, calendar, sprint management,
and enhancement scanning. It serves as the central intelligence router
for Zero's personal assistant capabilities.
"""

from typing import TypedDict, Literal, Annotated, Optional, Any
from datetime import datetime
from functools import lru_cache

from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

import structlog

logger = structlog.get_logger()


# =============================================================================
# State Definition
# =============================================================================

class OrchestratorState(TypedDict):
    """State for the orchestration supervisor graph."""
    messages: Annotated[list, add_messages]
    route: Optional[str]
    context: dict
    result: Optional[str]


# =============================================================================
# Route Classification
# =============================================================================

ROUTE_KEYWORDS = {
    "sprint": ["sprint", "task", "project", "legion", "backlog", "blocked", "progress", "velocity"],
    "email": ["email", "gmail", "inbox", "unread", "digest", "mail", "message", "send"],
    "calendar": ["calendar", "schedule", "meeting", "event", "free", "busy", "appointment", "today"],
    "enhancement": ["enhance", "scan", "todo", "fixme", "hack", "improve", "optimize", "code quality"],
    "briefing": ["briefing", "summary", "daily", "morning", "overview", "status", "health"],
    "research": ["research", "discover", "finding", "knowledge base", "trends", "new tools", "new projects", "what others building"],
}


def classify_route(message: str) -> str:
    """Classify user message to determine routing."""
    msg_lower = message.lower()

    scores = {}
    for route, keywords in ROUTE_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in msg_lower)
        if score > 0:
            scores[route] = score

    if not scores:
        return "general"

    return max(scores, key=scores.get)


# =============================================================================
# Graph Nodes
# =============================================================================

async def router_node(state: OrchestratorState) -> dict:
    """Supervisor node that classifies the user's intent and routes accordingly."""
    messages = state.get("messages", [])
    if not messages:
        return {"route": "general", "context": {"reason": "no messages"}}

    last_message = messages[-1]
    content = last_message.content if hasattr(last_message, "content") else str(last_message)

    route = classify_route(content)
    logger.info("orchestrator_routed", route=route, message_preview=content[:80])

    return {
        "route": route,
        "context": {
            "classified_at": datetime.utcnow().isoformat(),
            "route": route,
            "message_length": len(content),
        },
    }


async def sprint_node(state: OrchestratorState) -> dict:
    """Handle sprint/task/project management queries via Legion tools."""
    from app.services.legion_tools import (
        query_sprints, get_sprint_details, get_project_health, get_daily_summary
    )

    messages = state.get("messages", [])
    content = messages[-1].content if messages else ""
    msg_lower = content.lower()

    try:
        if any(kw in msg_lower for kw in ["detail", "tasks", "specific"]):
            # Try to extract sprint ID
            import re
            match = re.search(r's(?:print)?\s*(\d+)', msg_lower)
            if match:
                result = await get_sprint_details.ainvoke({"sprint_id": int(match.group(1))})
            else:
                result = await query_sprints.ainvoke({"status": "active", "limit": 10})
        elif any(kw in msg_lower for kw in ["health", "project", "status"]):
            result = await get_project_health.ainvoke({})
        elif any(kw in msg_lower for kw in ["summary", "daily", "overview"]):
            result = await get_daily_summary.ainvoke({})
        else:
            result = await query_sprints.ainvoke({"status": "active", "limit": 10})

        return {
            "result": result,
            "messages": [AIMessage(content=result)],
        }
    except Exception as e:
        error_msg = f"Sprint query failed: {e}"
        logger.error("sprint_node_error", error=str(e))
        return {
            "result": error_msg,
            "messages": [AIMessage(content=error_msg)],
        }


async def email_node(state: OrchestratorState) -> dict:
    """Handle email queries via Gmail tools."""
    from app.services.google_tools import fetch_emails, get_email_digest

    messages = state.get("messages", [])
    content = messages[-1].content if messages else ""
    msg_lower = content.lower()

    try:
        if any(kw in msg_lower for kw in ["digest", "summary", "overview"]):
            result = await get_email_digest.ainvoke({})
        else:
            result = await fetch_emails.ainvoke({"limit": 10})

        return {
            "result": result,
            "messages": [AIMessage(content=result)],
        }
    except Exception as e:
        error_msg = f"Email query failed: {e}"
        logger.error("email_node_error", error=str(e))
        return {
            "result": error_msg,
            "messages": [AIMessage(content=error_msg)],
        }


async def calendar_node(state: OrchestratorState) -> dict:
    """Handle calendar queries via Calendar tools."""
    from app.services.google_tools import get_calendar_events, get_today_schedule, find_free_slots

    messages = state.get("messages", [])
    content = messages[-1].content if messages else ""
    msg_lower = content.lower()

    try:
        if any(kw in msg_lower for kw in ["today", "schedule", "now"]):
            result = await get_today_schedule.ainvoke({})
        elif any(kw in msg_lower for kw in ["free", "available", "slot", "open"]):
            result = await find_free_slots.ainvoke({"duration_minutes": 30})
        else:
            result = await get_calendar_events.ainvoke({"days_ahead": 7})

        return {
            "result": result,
            "messages": [AIMessage(content=result)],
        }
    except Exception as e:
        error_msg = f"Calendar query failed: {e}"
        logger.error("calendar_node_error", error=str(e))
        return {
            "result": error_msg,
            "messages": [AIMessage(content=error_msg)],
        }


async def enhancement_node(state: OrchestratorState) -> dict:
    """Handle enhancement scanning and code quality queries."""
    try:
        from app.services.enhancement_service import get_enhancement_service
        service = get_enhancement_service()
        result = await service.scan_for_signals()

        if isinstance(result, dict):
            signals = result.get("signals", [])
            summary = f"Enhancement scan complete: {len(signals)} signals found.\n"
            for sig in signals[:10]:
                summary += f"  [{sig.get('severity', '?')}] {sig.get('type', '?')}: {sig.get('message', '')[:80]}\n"
            text = summary
        else:
            text = str(result)

        return {
            "result": text,
            "messages": [AIMessage(content=text)],
        }
    except Exception as e:
        error_msg = f"Enhancement scan failed: {e}"
        logger.error("enhancement_node_error", error=str(e))
        return {
            "result": error_msg,
            "messages": [AIMessage(content=error_msg)],
        }


async def briefing_node(state: OrchestratorState) -> dict:
    """Generate a comprehensive briefing combining all sources."""
    from app.services.legion_tools import get_daily_summary, query_sprints

    try:
        parts = []

        # Sprint summary from Legion
        sprint_summary = await get_daily_summary.ainvoke({})
        parts.append(sprint_summary)

        # Active sprints
        active = await query_sprints.ainvoke({"status": "active", "limit": 5})
        if active:
            parts.append(f"\nActive Sprints:\n{active}")

        result = "\n".join(parts)
        return {
            "result": result,
            "messages": [AIMessage(content=result)],
        }
    except Exception as e:
        error_msg = f"Briefing generation failed: {e}"
        logger.error("briefing_node_error", error=str(e))
        return {
            "result": error_msg,
            "messages": [AIMessage(content=error_msg)],
        }


async def research_node(state: OrchestratorState) -> dict:
    """Handle research queries - findings, knowledge base, stats."""
    from app.services.research_service import get_research_service

    messages = state.get("messages", [])
    content = messages[-1].content if messages else ""
    msg_lower = content.lower()

    try:
        svc = get_research_service()

        if any(kw in msg_lower for kw in ["stat", "how many", "overview", "pipeline"]):
            stats = await svc.get_stats()
            result = (
                f"Research Stats:\n"
                f"Topics: {stats.total_topics} ({stats.active_topics} active)\n"
                f"Total findings: {stats.total_findings}\n"
                f"This week: {stats.findings_this_week} findings, "
                f"{stats.tasks_created_this_week} tasks created\n"
                f"Avg relevance: {stats.avg_relevance_score:.1f}"
            )
        elif any(kw in msg_lower for kw in ["top", "best", "high", "discover"]):
            findings = await svc.list_findings(min_score=60, limit=5)
            lines = ["Top Research Findings:"]
            for f in findings:
                lines.append(f"- [{f.composite_score:.0f}] {f.title}")
                if f.llm_summary:
                    lines.append(f"  {f.llm_summary}")
            result = "\n".join(lines) if len(lines) > 1 else "No high-value findings yet."
        else:
            summary = await svc.get_knowledge_summary()
            result = summary

        return {
            "result": result,
            "messages": [AIMessage(content=result)],
        }
    except Exception as e:
        error_msg = f"Research query failed: {e}"
        logger.error("research_node_error", error=str(e))
        return {"result": error_msg, "messages": [AIMessage(content=error_msg)]}


async def general_node(state: OrchestratorState) -> dict:
    """Handle general queries that don't match specific routes."""
    messages = state.get("messages", [])
    content = messages[-1].content if messages else ""

    result = (
        f"I received your message: '{content[:100]}...'\n"
        "I can help with:\n"
        "- Sprint/task management (via Legion)\n"
        "- Email (Gmail inbox, digest)\n"
        "- Calendar (schedule, events, free slots)\n"
        "- Code enhancement scanning\n"
        "- Research (discoveries, trends, knowledge base)\n"
        "- Daily briefings\n"
        "Please be more specific about what you'd like me to do."
    )
    return {
        "result": result,
        "messages": [AIMessage(content=result)],
    }


# =============================================================================
# Conditional Edge Router
# =============================================================================

def route_by_classification(state: OrchestratorState) -> str:
    """Route to the appropriate node based on classification."""
    route = state.get("route", "general")
    valid_routes = {"sprint", "email", "calendar", "enhancement", "briefing", "research", "general"}
    return route if route in valid_routes else "general"


# =============================================================================
# Graph Builder
# =============================================================================

def build_orchestration_graph(checkpointer=None) -> Any:
    """Build and compile the orchestration supervisor StateGraph.

    Args:
        checkpointer: Optional LangGraph checkpointer for persistence.
                      If None, graph runs without persistence.

    Returns:
        Compiled StateGraph ready for invocation.
    """
    graph = StateGraph(OrchestratorState)

    # Add nodes
    graph.add_node("router", router_node)
    graph.add_node("sprint", sprint_node)
    graph.add_node("email", email_node)
    graph.add_node("calendar", calendar_node)
    graph.add_node("enhancement", enhancement_node)
    graph.add_node("briefing", briefing_node)
    graph.add_node("research", research_node)
    graph.add_node("general", general_node)

    # Entry: always start at router
    graph.add_edge(START, "router")

    # Conditional routing from router to specialized nodes
    graph.add_conditional_edges(
        "router",
        route_by_classification,
        {
            "sprint": "sprint",
            "email": "email",
            "calendar": "calendar",
            "enhancement": "enhancement",
            "briefing": "briefing",
            "research": "research",
            "general": "general",
        },
    )

    # All specialized nodes end the graph
    graph.add_edge("sprint", END)
    graph.add_edge("email", END)
    graph.add_edge("calendar", END)
    graph.add_edge("enhancement", END)
    graph.add_edge("briefing", END)
    graph.add_edge("research", END)
    graph.add_edge("general", END)

    # Compile with optional checkpointer
    compile_kwargs = {}
    if checkpointer:
        compile_kwargs["checkpointer"] = checkpointer

    compiled = graph.compile(**compile_kwargs)
    logger.info("orchestration_graph_compiled", checkpointer=type(checkpointer).__name__ if checkpointer else "none")
    return compiled


# =============================================================================
# Singleton with Optional Checkpointing
# =============================================================================

_compiled_graph = None


async def get_orchestration_graph():
    """Get the compiled orchestration graph, with optional PostgreSQL checkpointing.

    Attempts to use PostgreSQL-backed persistence for crash recovery.
    Falls back to in-memory (no persistence) if unavailable.
    """
    global _compiled_graph
    if _compiled_graph is not None:
        return _compiled_graph

    from app.infrastructure.checkpoint import get_checkpointer
    checkpointer = get_checkpointer()

    _compiled_graph = build_orchestration_graph(checkpointer=checkpointer)
    return _compiled_graph


async def invoke_orchestration(message: str, thread_id: str = "default") -> dict:
    """Invoke the orchestration graph with a user message.

    Args:
        message: The user's message text
        thread_id: Thread ID for conversation persistence

    Returns:
        Dict with 'result' key containing the response text
    """
    graph = await get_orchestration_graph()

    config = {"configurable": {"thread_id": thread_id}}
    input_state = {
        "messages": [HumanMessage(content=message)],
        "route": None,
        "context": {},
        "result": None,
    }

    result = await graph.ainvoke(input_state, config=config)

    return {
        "result": result.get("result", "No result generated."),
        "route": result.get("route", "unknown"),
        "thread_id": thread_id,
    }
