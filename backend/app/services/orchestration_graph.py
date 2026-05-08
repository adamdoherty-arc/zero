"""
LangGraph Orchestration Gateway for Zero.

Two-tier intelligent routing: fast keyword matching for unambiguous requests,
LLM-based classification for ambiguous queries. Includes response synthesis
for natural conversational output.

Routes: sprint, email, calendar, enhancement, briefing, research, notion,
        money_maker, knowledge, task, workflow, system, general.
"""

from typing import TypedDict, Annotated, Optional, Any
from datetime import datetime, timezone
from functools import lru_cache
import re
import time as _time

from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langchain_core.messages import HumanMessage, AIMessage

import structlog

logger = structlog.get_logger()


# =============================================================================
# Tracing helpers (used by invoke_orchestration)
# =============================================================================

async def _trace_node(node_func, state, node_name: str, node_order: int):
    """Execute a node function with trace recording."""
    conv_id = state.get("context", {}).get("_trace_conversation_id")
    if not conv_id:
        return await node_func(state)

    from app.services.orchestrator_trace_service import record_trace_node, complete_trace_node

    # Prepare input preview
    messages = state.get("messages", [])
    input_preview = {}
    if messages:
        last = messages[-1]
        input_preview["message"] = (last.content if hasattr(last, "content") else str(last))[:300]
    input_preview["route"] = state.get("route")

    trace_id = await record_trace_node(
        conversation_id=conv_id,
        thread_id=state.get("context", {}).get("_trace_thread_id", "default"),
        node_name=node_name,
        node_order=node_order,
        input_data=input_preview,
    )

    start = _time.time()
    try:
        result = await node_func(state)
        duration_ms = (_time.time() - start) * 1000

        # Extract output preview
        output_preview = {}
        if isinstance(result, dict):
            if "result" in result:
                output_preview["result"] = str(result["result"])[:500]
            if "route" in result:
                output_preview["route"] = result["route"]

        await complete_trace_node(
            trace_id=trace_id,
            output_data=output_preview,
            duration_ms=round(duration_ms, 1),
            status="completed",
        )
        return result
    except Exception as e:
        duration_ms = (_time.time() - start) * 1000
        await complete_trace_node(
            trace_id=trace_id,
            duration_ms=round(duration_ms, 1),
            status="failed",
            error=str(e),
        )
        raise


# =============================================================================
# State Definition
# =============================================================================

class OrchestratorState(TypedDict):
    """State for the orchestration supervisor graph."""
    messages: Annotated[list, add_messages]
    route: Optional[str]
    context: dict
    result: Optional[str]
    memories: Optional[list]


# =============================================================================
# Route Classification - Two-Tier System
# =============================================================================

VALID_ROUTES = {
    "sprint", "email", "calendar", "enhancement", "briefing",
    "research", "notion", "money_maker", "knowledge", "task",
    "workflow", "system", "tiktok", "content", "prediction_market",
    "planner", "ai_company", "deep_research", "experiment", "council",
    "character_content", "brain", "general",
    # SecondBrain Phase 3 additions
    "pkm", "legion_ops",
}

ROUTE_KEYWORDS = {
    "sprint": ["sprint", "project", "legion", "backlog", "progress", "velocity", "tasks", "blocked"],
    "task": ["create task", "add task", "new task", "update task", "move task", "complete task", "block task", "mark task", "task done"],
    "email": ["email", "gmail", "inbox", "unread", "digest", "mail", "message", "send"],
    "calendar": ["calendar", "schedule", "meeting", "event", "free", "busy", "appointment", "today"],
    "enhancement": ["enhance", "scan", "todo", "fixme", "hack", "improve", "optimize", "code quality"],
    "briefing": ["briefing", "summary", "daily", "morning", "overview"],
    "research": ["research", "discover", "finding", "trends", "new tools", "new projects", "what others building"],
    "notion": ["notion", "workspace", "page", "database", "wiki"],
    "money_maker": ["money", "income", "monetize", "revenue", "business", "side hustle", "profit", "earn"],
    "knowledge": ["remember", "recall", "note", "save note", "learn", "fact", "know about me", "my profile", "my preferences"],
    "workflow": ["workflow", "trigger", "automate", "run workflow", "execute workflow", "automation"],
    "system": ["system", "health", "gpu", "vram", "model", "scheduler", "uptime", "backup", "status"],
    "tiktok": ["tiktok shop", "tiktok product", "trending product", "shop product",
               "dropship", "product research", "viral product", "best selling",
               "what to sell", "shop opportunity", "affiliate product",
               "run pipeline", "tiktok pipeline", "faceless video", "video script",
               "content queue", "pending approval", "approve product", "product catalog"],
    "content": ["content topic", "content rule", "content example", "content agent",
                "generate content", "content ideas", "caption", "script",
                "content performance", "content trend", "improvement cycle"],
    "prediction_market": ["prediction market", "prediction", "polymarket", "kalshi",
                          "bettor", "bettors", "odds", "prediction research",
                          "legion progress", "ada sprint", "market movers",
                          "winning bettor", "prediction quality"],
    "planner": ["plan", "break down", "step by step", "strategy for",
                "create a plan", "make a plan", "how should i approach",
                "deep analysis", "think through"],
    "ai_company": ["agent company", "ai company", "agent role", "agent task",
                   "ceo agent", "researcher agent", "analyst agent",
                   "delegate to", "company task", "role execution"],
    "deep_research": ["deep research", "comprehensive research", "research report",
                      "investigate thoroughly", "in-depth research", "storm research"],
    "experiment": ["experiment", "hypothesis", "run experiment", "test hypothesis",
                   "ab test", "benchmark", "prototype", "experiment lab"],
    "council": ["council", "council vote", "council decision", "agent debate",
                "multi-agent vote", "propose decision", "council review"],
    "character_content": ["character", "carousel", "character content", "tiktok character",
                          "character facts", "character research", "character carousel",
                          "marvel character", "dc character", "character post"],
    "brain": ["brain", "benchmark", "brain status", "self-improve", "employee score",
              "calibration", "prompt evolution", "episodic memory", "how am i doing",
              "improvement cycle", "learning velocity", "brain benchmark",
              "what have you learned", "zero brain", "brain dashboard"],
    # SecondBrain Phase 3 PKM (vault) routes
    "pkm": ["vault", "obsidian", "my notes", "daily note", "atomic note",
            "knowledge base", "find note", "search vault", "linked note",
            "pkm", "second brain", "zettelkasten"],
    "legion_ops": ["legion", "legion task", "delegate to legion", "legion sprint",
                   "ship code", "cross-project", "fix in legion", "legion build",
                   "legion deploy", "legion audit"],
}

CLASSIFICATION_SYSTEM_PROMPT = """You are an intent classifier for a personal AI assistant called Zero.
Classify the user message into exactly one of these categories:
- sprint: Sprint management, projects, backlogs, progress tracking
- task: Creating, updating, completing, or blocking specific tasks
- email: Gmail, inbox, messages, sending/reading emails, drafts
- calendar: Schedule, meetings, events, free time, appointments
- enhancement: Code quality, TODOs, FIXMEs, optimization suggestions
- briefing: Daily summaries, status overviews, morning/evening reports
- research: Discoveries, trends, new tools/projects
- notion: Notion workspace, pages, databases, wikis
- money_maker: Income ideas, monetization, business opportunities, side hustles
- knowledge: Notes, memory, remembering things, user preferences, recall
- workflow: Triggering automation workflows, listing automations
- system: System health, GPU/VRAM status, scheduler, backups
- tiktok: TikTok Shop product research, trending products, market opportunities, what to sell, affiliate/dropship, run pipeline, faceless videos, video scripts, approval queue, content generation, product catalog
- content: Content topics, rules, examples, content generation, captions, scripts, performance, improvement
- prediction_market: Prediction markets, Kalshi, Polymarket, bettors, odds, market movers, Legion sprint progress for prediction work
- planner: Complex multi-step planning requests, "create a plan for...", "break down...", strategy, deep analysis requiring step-by-step reasoning
- ai_company: Agent company tasks, role execution, delegation, CEO planning, agent role status
- deep_research: Deep comprehensive research reports, multi-perspective investigation, in-depth analysis
- experiment: Designing, running, viewing experiments, hypothesis testing, benchmarks, A/B tests
- council: Council of agents debate and voting, multi-agent decisions, consensus building
- brain: Brain status, benchmarks, self-improvement, learning velocity, calibration, episodic memory, prompt evolution, what has Zero learned
- general: Anything else, greetings, meta-questions

Respond with ONLY the category name, nothing else."""

# Confidence threshold: if keyword score >= this, skip LLM classification
KEYWORD_CONFIDENCE_THRESHOLD = 3

_HELP_MENU = (
    "here's what I can do:\n"
    "- **sprints** — active sprints, progress, project health\n"
    "- **tasks** — create, update, complete, block tasks\n"
    "- **email** — inbox, digest, unread count\n"
    "- **calendar** — today's schedule, events, free slots\n"
    "- **knowledge** — save notes, recall facts, search memory\n"
    "- **research** — findings, trends, discoveries\n"
    "- **notion** — search workspace, pages, databases\n"
    "- **money maker** — income ideas, side hustles\n"
    "- **workflows** — list and trigger automations\n"
    "- **enhancements** — code quality scan, TODOs\n"
    "- **briefing** — daily summary, morning briefing\n"
    "- **system** — health check, GPU status, scheduler\n"
    "- **tiktok shop** — product research, approval queue, faceless video pipeline, catalog\n"
    "- **content agent** — content topics, rules, examples, generation, performance\n"
    "- **prediction markets** — Kalshi/Polymarket data, bettor leaderboard, odds, Legion progress\n"
    "- **planner** — complex multi-step planning (uses Kimi for deep reasoning)\n"
    "- **ai company** — agent roles (CEO, Researcher, Analyst, Engineer, Validator), task delegation\n"
    "- **deep research** — comprehensive multi-perspective research reports\n"
    "- **experiment lab** — design and run experiments, hypothesis testing\n"
    "- **council** — multi-agent debate and voting on decisions\n\n"
    "just ask naturally and I'll figure out the rest"
)


def classify_route_keywords(message: str) -> tuple[str, int]:
    """Tier 1: Fast keyword-based classification. Returns (route, confidence_score)."""
    msg_lower = message.lower()

    scores = {}
    for route, keywords in ROUTE_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in msg_lower)
        if score > 0:
            scores[route] = score

    if not scores:
        return "general", 0

    best_route = max(scores, key=scores.get)
    return best_route, scores[best_route]


def classify_route(message: str) -> str:
    """Compatibility helper for callers that need synchronous keyword routing."""
    route, _confidence = classify_route_keywords(message)
    return route


async def classify_route_llm(message: str) -> str:
    """Tier 2: LLM-based intent classification for ambiguous queries (via Kimi)."""
    try:
        from app.infrastructure.unified_llm_client import get_unified_llm_client
        client = get_unified_llm_client()
        result = await client.chat(
            f"Classify this message: {message}",
            system=CLASSIFICATION_SYSTEM_PROMPT,
            task_type="classification",
            temperature=0.0,
            max_tokens=20,
        )
        route = result.strip().lower().split()[0] if result else "general"
        return route if route in VALID_ROUTES else "general"
    except Exception as e:
        logger.warning("llm_classification_failed", error=str(e))
        return "general"


# =============================================================================
# Graph Nodes
# =============================================================================

async def router_node(state: OrchestratorState) -> dict:
    """Two-tier supervisor: keyword fast path + LLM fallback for ambiguous queries."""
    messages = state.get("messages", [])
    if not messages:
        return {"route": "general", "context": {"reason": "no messages"}}

    last_message = messages[-1]
    content = last_message.content if hasattr(last_message, "content") else str(last_message)

    # Tier 1: Fast keyword match
    route, confidence = classify_route_keywords(content)
    method = "keyword"

    # Tier 2: LLM classification if keyword confidence is low
    if confidence < KEYWORD_CONFIDENCE_THRESHOLD:
        llm_route = await classify_route_llm(content)
        if llm_route != "general" or route == "general":
            route = llm_route
            method = "llm"
        else:
            method = "keyword_low_confidence"

    logger.info("orchestrator_routed", route=route, method=method,
                keyword_confidence=confidence, message_preview=content[:80])

    # Retrieve relevant memories from knowledge service (semantic search)
    memories = []
    try:
        from app.services.knowledge_service import get_knowledge_service
        ks = get_knowledge_service()
        memory_notes = await ks.semantic_search(content, limit=3, table="notes")
        for note in memory_notes:
            if hasattr(note, "content"):
                memories.append({"type": "note", "title": note.title, "content": note.content[:200]})
            elif isinstance(note, dict):
                memories.append(note)
    except Exception as e:
        logger.debug("memory_retrieval_skipped", error=str(e))

    return {
        "route": route,
        "memories": memories,
        "context": {
            "classified_at": datetime.utcnow().isoformat(),
            "route": route,
            "method": method,
            "keyword_confidence": confidence,
            "message_length": len(content),
            "original_message": content,
        },
    }


async def sprint_node(state: OrchestratorState) -> dict:
    """Handle sprint/project management queries via Legion tools."""
    from app.services.legion_tools import (
        query_sprints, get_sprint_details, get_project_health, get_daily_summary
    )

    messages = state.get("messages", [])
    content = messages[-1].content if messages else ""
    msg_lower = content.lower()

    try:
        if any(kw in msg_lower for kw in ["detail", "tasks", "specific"]):
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

        return {"result": result, "messages": [AIMessage(content=result)]}
    except Exception as e:
        error_msg = f"Sprint query failed: {e}"
        logger.error("sprint_node_error", error=str(e))
        return {"result": error_msg, "messages": [AIMessage(content=error_msg)]}


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

        return {"result": result, "messages": [AIMessage(content=result)]}
    except Exception as e:
        error_msg = f"Email query failed: {e}"
        logger.error("email_node_error", error=str(e))
        return {"result": error_msg, "messages": [AIMessage(content=error_msg)]}


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

        return {"result": result, "messages": [AIMessage(content=result)]}
    except Exception as e:
        error_msg = f"Calendar query failed: {e}"
        logger.error("calendar_node_error", error=str(e))
        return {"result": error_msg, "messages": [AIMessage(content=error_msg)]}


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

        return {"result": text, "messages": [AIMessage(content=text)]}
    except Exception as e:
        error_msg = f"Enhancement scan failed: {e}"
        logger.error("enhancement_node_error", error=str(e))
        return {"result": error_msg, "messages": [AIMessage(content=error_msg)]}


async def briefing_node(state: OrchestratorState) -> dict:
    """Generate a comprehensive briefing combining all sources."""
    from app.services.legion_tools import get_daily_summary, query_sprints

    try:
        parts = []
        sprint_summary = await get_daily_summary.ainvoke({})
        parts.append(sprint_summary)

        active = await query_sprints.ainvoke({"status": "active", "limit": 5})
        if active:
            parts.append(f"\nActive Sprints:\n{active}")

        result = "\n".join(parts)
        return {"result": result, "messages": [AIMessage(content=result)]}
    except Exception as e:
        error_msg = f"Briefing generation failed: {e}"
        logger.error("briefing_node_error", error=str(e))
        return {"result": error_msg, "messages": [AIMessage(content=error_msg)]}


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

        return {"result": result, "messages": [AIMessage(content=result)]}
    except Exception as e:
        error_msg = f"Research query failed: {e}"
        logger.error("research_node_error", error=str(e))
        return {"result": error_msg, "messages": [AIMessage(content=error_msg)]}


async def notion_node(state: OrchestratorState) -> dict:
    """Handle Notion workspace queries."""
    messages = state.get("messages", [])
    content = messages[-1].content if messages else ""

    try:
        from app.services.notion_service import get_notion_service
        svc = get_notion_service()
        result = await svc.search(content[:200])
        if isinstance(result, list):
            lines = ["Notion Results:"]
            for item in result[:10]:
                title = item.get("title", item.get("name", "Untitled"))
                lines.append(f"- {title}")
            text = "\n".join(lines) if len(lines) > 1 else "No Notion results found."
        else:
            text = str(result) if result else "No Notion results found."
        return {"result": text, "messages": [AIMessage(content=text)]}
    except Exception as e:
        error_msg = f"Notion query failed: {e}"
        logger.error("notion_node_error", error=str(e))
        return {"result": error_msg, "messages": [AIMessage(content=error_msg)]}


async def money_maker_node(state: OrchestratorState) -> dict:
    """Handle income/monetization queries via Money Maker service."""
    messages = state.get("messages", [])
    content = messages[-1].content if messages else ""
    msg_lower = content.lower()

    try:
        from app.services.money_maker_service import get_money_maker_service
        svc = get_money_maker_service()

        if any(kw in msg_lower for kw in ["generate", "new", "create"]):
            ideas = await svc.generate_ideas(count=3)
            lines = ["Generated Money-Making Ideas:"]
            for idea in ideas:
                lines.append(f"- {idea.get('title', 'Untitled')}: {idea.get('description', '')[:100]}")
            text = "\n".join(lines)
        else:
            ideas = await svc.list_ideas(limit=10)
            if ideas:
                lines = ["Money-Making Ideas:"]
                for idea in ideas:
                    score = idea.get("viability_score", 0)
                    lines.append(f"- [{score:.0f}] {idea.get('title', 'Untitled')} ({idea.get('status', 'unknown')})")
                text = "\n".join(lines)
            else:
                text = "No money-making ideas tracked yet. Ask me to generate some!"

        return {"result": text, "messages": [AIMessage(content=text)]}
    except Exception as e:
        error_msg = f"Money maker query failed: {e}"
        logger.error("money_maker_node_error", error=str(e))
        return {"result": error_msg, "messages": [AIMessage(content=error_msg)]}


async def knowledge_node(state: OrchestratorState) -> dict:
    """Handle knowledge management - notes, recall, user facts."""
    messages = state.get("messages", [])
    content = messages[-1].content if messages else ""
    msg_lower = content.lower()

    try:
        from app.services.knowledge_service import get_knowledge_service
        svc = get_knowledge_service()

        # Write: save a note or fact
        if any(kw in msg_lower for kw in ["remember", "save note", "note that", "learn that"]):
            # Extract the content to remember
            for prefix in ["remember that ", "remember ", "save note: ", "save note ", "note that ", "learn that "]:
                if msg_lower.startswith(prefix):
                    fact_text = content[len(prefix):].strip()
                    break
            else:
                fact_text = content.strip()

            fact = await svc.learn_fact(fact_text, category="chat", source="discord")
            result = f"Saved: \"{fact.fact}\""
        # Read: recall / search
        elif any(kw in msg_lower for kw in ["recall", "what do you know", "know about me", "my profile", "my preferences"]):
            from app.models.knowledge import RecallRequest
            recall_result = await svc.recall(RecallRequest(
                context=content, include_notes=True, include_facts=True, limit=10
            ))
            lines = []
            if recall_result.facts:
                lines.append("**Facts I know:**")
                for f in recall_result.facts[:10]:
                    lines.append(f"- {f.fact}")
            if recall_result.notes:
                lines.append("**Related notes:**")
                for n in recall_result.notes[:5]:
                    lines.append(f"- {n.title}: {n.content[:80]}")
            result = "\n".join(lines) if lines else "I don't have any saved knowledge yet. Tell me things to remember!"
        # Read: list notes
        elif any(kw in msg_lower for kw in ["notes", "list note", "my notes"]):
            notes = await svc.list_notes(limit=10)
            if notes:
                lines = ["Your notes:"]
                for n in notes:
                    lines.append(f"- [{n.id}] {n.title}")
                result = "\n".join(lines)
            else:
                result = "No notes saved yet."
        else:
            # Default: search notes by the query
            notes = await svc.search_notes(content, limit=5)
            if notes:
                lines = ["Found notes:"]
                for n in notes:
                    lines.append(f"- {n.title}: {n.content[:100]}")
                result = "\n".join(lines)
            else:
                result = "No matching notes found. You can say 'remember <something>' to save info."

        return {"result": result, "messages": [AIMessage(content=result)]}
    except Exception as e:
        error_msg = f"Knowledge query failed: {e}"
        logger.error("knowledge_node_error", error=str(e))
        return {"result": error_msg, "messages": [AIMessage(content=error_msg)]}


async def task_node(state: OrchestratorState) -> dict:
    """Handle task creation, updates, and queries."""
    messages = state.get("messages", [])
    content = messages[-1].content if messages else ""
    msg_lower = content.lower()

    try:
        # Write: create a task
        if any(kw in msg_lower for kw in ["create task", "add task", "new task"]):
            from app.services.legion_tools import create_task, query_sprints

            # Extract task title from the message
            for prefix in ["create task:", "create task ", "add task:", "add task ", "new task:", "new task "]:
                if msg_lower.startswith(prefix):
                    task_title = content[len(prefix):].strip()
                    break
            else:
                # Try to extract after the keyword
                match = re.search(r'(?:create|add|new)\s+task[:\s]+(.+)', content, re.IGNORECASE)
                task_title = match.group(1).strip() if match else content

            # Find the active sprint to add the task to
            sprints_text = await query_sprints.ainvoke({"status": "active", "limit": 1})
            sprint_match = re.search(r'S(\d+)', sprints_text)
            sprint_id = int(sprint_match.group(1)) if sprint_match else 1

            result = await create_task.ainvoke({
                "sprint_id": sprint_id,
                "title": task_title,
                "description": task_title,
                "prompt": f"Implement: {task_title}",
                "priority": 3,
            })
            return {"result": result, "messages": [AIMessage(content=result)]}

        # Write: update task status
        elif any(kw in msg_lower for kw in ["complete task", "mark task", "task done", "finish task"]):
            from app.services.legion_tools import update_task_status

            match = re.search(r't(?:ask)?\s*(\d+)', msg_lower)
            if match:
                task_id = int(match.group(1))
                status = "completed"
                if "block" in msg_lower:
                    status = "blocked"
                elif "start" in msg_lower or "begin" in msg_lower:
                    status = "running"
                result = await update_task_status.ainvoke({
                    "task_id": task_id,
                    "status": status,
                })
            else:
                result = "Please specify the task ID, e.g. 'complete task 42' or 'mark T42 done'"

            return {"result": result, "messages": [AIMessage(content=result)]}

        # Write: block a task
        elif "block task" in msg_lower or "block t" in msg_lower:
            from app.services.legion_tools import update_task_status

            match = re.search(r't(?:ask)?\s*(\d+)', msg_lower)
            if match:
                result = await update_task_status.ainvoke({
                    "task_id": int(match.group(1)),
                    "status": "blocked",
                })
            else:
                result = "Please specify the task ID, e.g. 'block task 42'"

            return {"result": result, "messages": [AIMessage(content=result)]}

        # Read: list tasks (fallback)
        else:
            from app.services.task_service import get_task_service
            svc = get_task_service()
            tasks = await svc.list_tasks(limit=10)
            if tasks:
                lines = ["Recent tasks:"]
                for t in tasks:
                    status = t.status.value if hasattr(t.status, 'value') else t.status
                    lines.append(f"- [{status}] {t.id}: {t.title}")
                result = "\n".join(lines)
            else:
                result = "No tasks found."

            return {"result": result, "messages": [AIMessage(content=result)]}

    except Exception as e:
        error_msg = f"Task operation failed: {e}"
        logger.error("task_node_error", error=str(e))
        return {"result": error_msg, "messages": [AIMessage(content=error_msg)]}


async def workflow_node(state: OrchestratorState) -> dict:
    """Handle workflow listing, triggering, and status queries."""
    messages = state.get("messages", [])
    content = messages[-1].content if messages else ""
    msg_lower = content.lower()

    try:
        from app.services.workflow_engine import get_workflow_engine
        engine = get_workflow_engine()

        # Write: trigger a workflow
        if any(kw in msg_lower for kw in ["trigger", "run workflow", "execute"]):
            # Try to extract workflow name
            match = re.search(r'(?:trigger|run|execute)\s+(?:workflow\s+)?["\']?([a-z0-9_-]+)["\']?', msg_lower)
            if match:
                name = match.group(1)
                result_data = await engine.trigger_workflow(name)
                if result_data.get("error"):
                    result = f"Failed: {result_data['error']}"
                else:
                    result = f"Workflow '{name}' triggered. Execution ID: {result_data.get('execution_id', 'unknown')}, Status: {result_data.get('status', 'started')}"
            else:
                # List available workflows so the user can pick one
                workflows = engine.list_workflows()
                if workflows:
                    lines = ["Which workflow? Available:"]
                    for w in workflows:
                        lines.append(f"- **{w['name']}**: {w.get('description', '')[:60]}")
                    result = "\n".join(lines)
                else:
                    result = "No workflows defined yet."

        # Read: active executions
        elif any(kw in msg_lower for kw in ["active", "running", "executing"]):
            active = engine.get_active_executions()
            if active:
                lines = ["Active workflow executions:"]
                for ex in active:
                    lines.append(f"- {ex.get('workflow_id', '?')}: {ex.get('status', '?')}")
                result = "\n".join(lines)
            else:
                result = "No active workflow executions."

        # Read: list workflows (default)
        else:
            workflows = engine.list_workflows()
            if workflows:
                lines = ["Available workflows:"]
                for w in workflows:
                    lines.append(f"- **{w['name']}** (v{w.get('version', '?')}): {w.get('description', '')[:80]}")
                result = "\n".join(lines)
            else:
                result = "No workflows defined yet. Add YAML workflow files to the workspace/workflows/ directory."

        return {"result": result, "messages": [AIMessage(content=result)]}
    except Exception as e:
        error_msg = f"Workflow query failed: {e}"
        logger.error("workflow_node_error", error=str(e))
        return {"result": error_msg, "messages": [AIMessage(content=error_msg)]}


async def system_node(state: OrchestratorState) -> dict:
    """Handle system health, GPU status, scheduler, and backup queries."""
    messages = state.get("messages", [])
    content = messages[-1].content if messages else ""
    msg_lower = content.lower()

    try:
        parts = []

        # GPU/VRAM status
        if any(kw in msg_lower for kw in ["gpu", "vram", "model"]):
            try:
                from app.services.gpu_manager_service import get_gpu_manager
                gpu_svc = get_gpu_manager()
                status = await gpu_svc.get_status()
                parts.append(f"GPU: {status.gpu_info.name if status.gpu_info else 'Unknown'}")
                parts.append(f"VRAM: {status.gpu_info.vram_used_mb:.0f}/{status.gpu_info.vram_total_mb:.0f} MB" if status.gpu_info else "VRAM: N/A")
                if status.loaded_models:
                    parts.append("Loaded models:")
                    for m in status.loaded_models:
                        parts.append(f"  - {m.name} ({m.size_mb:.0f} MB)")
            except Exception as e:
                parts.append(f"GPU status unavailable: {e}")

        # Scheduler status
        elif any(kw in msg_lower for kw in ["scheduler", "jobs", "cron"]):
            try:
                from app.services.scheduler_service import get_scheduler_service
                svc = get_scheduler_service()
                status = svc.get_status()
                parts.append(f"Scheduler: {'running' if status.get('running') else 'stopped'}")
                parts.append(f"Total jobs: {status.get('total_jobs', 0)}")
                if status.get("jobs"):
                    parts.append("Active jobs:")
                    for job in list(status["jobs"])[:10]:
                        parts.append(f"  - {job.get('id', '?')}: {job.get('next_run', 'N/A')}")
            except Exception as e:
                parts.append(f"Scheduler status unavailable: {e}")

        # General system health (default)
        else:
            parts.append("**System Health Check**")
            # Check Ollama
            try:
                from app.infrastructure.ollama_client import get_llm_client
                client = get_llm_client()
                await client.chat("ping", system="Reply with 'pong'", num_predict=5, timeout=5)
                parts.append("Ollama: online")
            except Exception:
                parts.append("Ollama: offline")

            # Check DB
            try:
                from app.infrastructure.database import get_session
                from sqlalchemy import text
                async with get_session() as session:
                    await session.execute(text("SELECT 1"))
                parts.append("Database: online")
            except Exception:
                parts.append("Database: offline")

            # GPU summary
            try:
                from app.services.gpu_manager_service import get_gpu_manager
                gpu_svc = get_gpu_manager()
                status = await gpu_svc.get_status()
                if status.gpu_info:
                    pct = (status.gpu_info.vram_used_mb / status.gpu_info.vram_total_mb * 100) if status.gpu_info.vram_total_mb else 0
                    parts.append(f"GPU VRAM: {pct:.0f}% used")
            except Exception:
                parts.append("GPU: unavailable")

        result = "\n".join(parts) if parts else "System status unavailable."
        return {"result": result, "messages": [AIMessage(content=result)]}
    except Exception as e:
        error_msg = f"System status check failed: {e}"
        logger.error("system_node_error", error=str(e))
        return {"result": error_msg, "messages": [AIMessage(content=error_msg)]}


async def general_node(state: OrchestratorState) -> dict:
    """Handle general queries using Kimi for conversational response."""
    messages = state.get("messages", [])
    content = messages[-1].content if messages else ""

    try:
        from app.infrastructure.unified_llm_client import get_unified_llm_client
        client = get_unified_llm_client()
        result = await client.chat(
            content,
            system=(
                "You are Zero, a personal AI assistant. Be concise, conversational, "
                "and Discord-friendly (short messages, emoji for tone, no tables). "
                "You help with: sprints, tasks (create/update), email, calendar, "
                "code enhancements, research, Notion, money-making ideas, briefings, "
                "knowledge/notes, workflows, and system health. "
                "If the user's request matches a domain, suggest they ask specifically."
            ),
            task_type="chat",
            temperature=0.5,
        )
        if not result:
            result = _HELP_MENU
    except Exception:
        result = _HELP_MENU

    return {"result": result, "messages": [AIMessage(content=result)]}


async def synthesizer_node(state: OrchestratorState) -> dict:
    """Synthesize raw data into a natural, conversational response."""
    raw_result = state.get("result", "")
    original_message = state.get("context", {}).get("original_message", "")

    if not raw_result or "failed:" in raw_result.lower():
        return state

    # Build memory context if available
    memories = state.get("memories", [])
    memory_context = ""
    if memories:
        memory_lines = []
        for m in memories[:3]:
            if isinstance(m, dict):
                memory_lines.append(f"- {m.get('title', '')}: {m.get('content', '')[:100]}")
        if memory_lines:
            memory_context = f"\n\nRelevant memories:\n" + "\n".join(memory_lines)

    try:
        from app.infrastructure.unified_llm_client import get_unified_llm_client
        client = get_unified_llm_client()
        response = await client.chat(
            f"User asked: {original_message}\n\nData retrieved:\n{raw_result[:3000]}{memory_context}",
            system=(
                "You are Zero, a personal AI assistant responding on Discord. "
                "Synthesize the data into a SHORT, conversational response. Rules:\n"
                "- Keep it 1-3 sentences when possible, break up long info into bullet points\n"
                "- Use **bold** for emphasis, not ## headers\n"
                "- NO markdown tables (Discord renders them ugly)\n"
                "- Use emoji sparingly for tone\n"
                "- Be direct, skip filler like 'I'd be happy to help'\n"
                "- Do not add information not in the data"
            ),
            task_type="summarization",
            temperature=0.3,
            max_tokens=1024,
        )
        if response and len(response.strip()) > 10:
            return {"result": response, "messages": [AIMessage(content=response)]}
    except Exception as e:
        logger.warning("synthesizer_fallback", error=str(e))

    return state


async def tiktok_node(state: OrchestratorState) -> dict:
    """Handle TikTok Shop queries — delegates pipeline ops to tiktok_agent_graph."""
    messages = state.get("messages", [])
    content = messages[-1].content if messages else ""
    msg_lower = content.lower()

    try:
        from app.services.tiktok_shop_service import get_tiktok_shop_service
        svc = get_tiktok_shop_service()

        # Pipeline operations — delegate to LangGraph agent
        if any(kw in msg_lower for kw in ["run pipeline", "full pipeline", "start pipeline", "run the pipeline"]):
            from app.services.tiktok_agent_graph import invoke_tiktok_pipeline
            pipeline_result = await invoke_tiktok_pipeline(mode="full")
            result = (
                f"TikTok Pipeline ({pipeline_result['status']}):\n"
                f"{pipeline_result.get('summary', 'No summary')}\n"
                f"Products discovered: {pipeline_result.get('products_discovered', 0)}\n"
                f"Auto-approved: {pipeline_result.get('auto_approved', 0)}\n"
                f"Scripts generated: {pipeline_result.get('scripts_generated', 0)}\n"
                f"Generation jobs queued: {pipeline_result.get('generation_jobs', 0)}"
            )
            if pipeline_result.get("errors"):
                result += f"\nErrors: {len(pipeline_result['errors'])}"

        # Approval queue
        elif any(kw in msg_lower for kw in ["pending", "approve", "approval", "review"]):
            pending = await svc.list_pending(limit=20)
            if pending:
                lines = [f"Pending Approval ({len(pending)} products):"]
                for p in pending:
                    lines.append(f"- [{p.opportunity_score:.0f}] {p.name} ({p.niche or 'general'})")
                lines.append("\nUse the TikTok Shop dashboard to approve or reject products.")
                result = "\n".join(lines)
            else:
                result = "No products pending approval. All caught up!"

        # Video/content pipeline
        elif any(kw in msg_lower for kw in ["video", "script", "faceless", "content queue", "content pipeline"]):
            from app.services.tiktok_agent_graph import invoke_tiktok_pipeline
            pipeline_result = await invoke_tiktok_pipeline(mode="content_only")
            result = (
                f"Content Pipeline ({pipeline_result['status']}):\n"
                f"{pipeline_result.get('summary', 'No summary')}\n"
                f"Scripts generated: {pipeline_result.get('scripts_generated', 0)}\n"
                f"Generation jobs queued: {pipeline_result.get('generation_jobs', 0)}"
            )

        # Performance tracking
        elif any(kw in msg_lower for kw in ["performance", "metrics", "how is", "how are"]):
            from app.services.tiktok_agent_graph import invoke_tiktok_pipeline
            pipeline_result = await invoke_tiktok_pipeline(mode="performance_only")
            result = f"Performance Tracking: {pipeline_result.get('summary', 'Completed')}"

        # Pipeline status
        elif any(kw in msg_lower for kw in ["pipeline status", "last pipeline", "last run", "job status", "scheduler status"]):
            from app.db.models import SchedulerAuditLogModel
            from app.infrastructure.database import get_session as _get_session
            async with _get_session() as session:
                tiktok_jobs = [
                    "tiktok_continuous_research", "tiktok_auto_content_pipeline",
                    "tiktok_performance_sync", "tiktok_pipeline_health",
                ]
                lines = ["TikTok Pipeline Status:"]
                for job_name in tiktok_jobs:
                    log_result = await session.execute(
                        select(SchedulerAuditLogModel).where(
                            SchedulerAuditLogModel.job_name == job_name
                        ).order_by(SchedulerAuditLogModel.started_at.desc()).limit(1)
                    )
                    row = log_result.scalar_one_or_none()
                    if row:
                        ago = (datetime.now(timezone.utc) - row.started_at).total_seconds() / 3600
                        lines.append(
                            f"- {job_name}: {row.status} ({ago:.1f}h ago)"
                            + (f" — {row.error[:80]}" if row.error else "")
                        )
                    else:
                        lines.append(f"- {job_name}: never run")
                result = "\n".join(lines)

        # Stats
        elif any(kw in msg_lower for kw in ["stat", "overview", "how many"]):
            stats = await svc.get_stats()
            result = (
                f"TikTok Shop Stats:\n"
                f"Total products: {stats.total_products}\n"
                f"Pending approval: {stats.pending_approval_products}\n"
                f"Approved: {stats.approved_products}\n"
                f"Active: {stats.active_products}, Discovered: {stats.discovered_products}\n"
                f"Avg opportunity score: {stats.avg_opportunity_score:.1f}\n"
                f"Top niches: {', '.join(stats.top_niches[:5]) if stats.top_niches else 'none yet'}"
            )

        # Top opportunities
        elif any(kw in msg_lower for kw in ["top", "best", "opportunity", "high score"]):
            products = await svc.list_products(limit=5)
            products.sort(key=lambda p: p.opportunity_score or 0, reverse=True)
            lines = ["Top TikTok Shop Opportunities:"]
            for p in products[:5]:
                lines.append(f"- [{p.opportunity_score:.0f}] {p.name} ({p.niche or 'general'}) — {p.status}")
            result = "\n".join(lines) if len(lines) > 1 else "No products discovered yet. Run a research cycle!"

        # Research cycle
        elif any(kw in msg_lower for kw in ["research", "discover", "cycle", "find"]):
            from app.services.tiktok_agent_graph import invoke_tiktok_pipeline
            pipeline_result = await invoke_tiktok_pipeline(mode="research_only")
            result = (
                f"Research Pipeline ({pipeline_result['status']}):\n"
                f"{pipeline_result.get('summary', 'No summary')}\n"
                f"Products discovered: {pipeline_result.get('products_discovered', 0)}"
            )

        # Default: list products
        else:
            products = await svc.list_products(limit=10)
            if products:
                lines = ["TikTok Shop Products:"]
                for p in products:
                    lines.append(f"- [{p.opportunity_score:.0f}] {p.name} ({p.status})")
                result = "\n".join(lines)
            else:
                result = "No TikTok Shop products yet. Ask me to run a research cycle or the full pipeline!"

        return {"result": result, "messages": [AIMessage(content=result)]}
    except Exception as e:
        error_msg = f"TikTok Shop query failed: {e}"
        logger.error("tiktok_node_error", error=str(e))
        return {"result": error_msg, "messages": [AIMessage(content=error_msg)]}


async def content_node(state: OrchestratorState) -> dict:
    """Handle content agent queries — topics, rules, generation, performance."""
    messages = state.get("messages", [])
    content = messages[-1].content if messages else ""
    msg_lower = content.lower()

    try:
        from app.services.content_agent_service import get_content_agent_service
        svc = get_content_agent_service()

        if any(kw in msg_lower for kw in ["stat", "overview", "how many"]):
            stats = await svc.get_stats()
            result = (
                f"Content Agent Stats:\n"
                f"Topics: {stats.total_topics} ({stats.active_topics} active)\n"
                f"Total examples: {stats.total_examples}\n"
                f"Content generated: {stats.total_generated}\n"
                f"Avg performance: {stats.avg_performance_score:.1f}\n"
                f"Active rules: {stats.total_rules}"
            )
        elif any(kw in msg_lower for kw in ["improve", "cycle", "feedback"]):
            result_data = await svc.run_improvement_cycle()
            if isinstance(result_data, dict):
                result = f"Improvement cycle complete: {result_data.get('topics_processed', 0)} topics processed, {result_data.get('rules_updated', 0)} rules updated"
            else:
                result = str(result_data)
        elif any(kw in msg_lower for kw in ["performance", "metric", "engagement"]):
            from sqlalchemy import select, func
            from app.infrastructure.database import get_session
            from app.db.models import ContentPerformanceModel
            async with get_session() as session:
                q = select(func.count(ContentPerformanceModel.id), func.avg(ContentPerformanceModel.performance_score))
                row = (await session.execute(q)).one()
                result = f"Content Performance: {row[0]} records, avg score: {row[1]:.1f}" if row[0] else "No performance data yet."
        else:
            topics = await svc.list_topics()
            if topics:
                lines = ["Content Topics:"]
                for t in topics:
                    rule_count = len(t.rules) if t.rules else 0
                    lines.append(f"- {t.name} ({t.platform}) — {t.status}, {rule_count} rules, {t.examples_count} examples")
                result = "\n".join(lines)
            else:
                result = "No content topics yet. Create one to get started!"

        return {"result": result, "messages": [AIMessage(content=result)]}
    except Exception as e:
        error_msg = f"Content agent query failed: {e}"
        logger.error("content_node_error", error=str(e))
        return {"result": error_msg, "messages": [AIMessage(content=error_msg)]}


async def prediction_market_node(state: OrchestratorState) -> dict:
    """Handle prediction market queries — markets, bettors, quality, Legion progress."""
    messages = state.get("messages", [])
    content = messages[-1].content if messages else ""
    msg_lower = content.lower()

    try:
        from app.services.prediction_market_service import get_prediction_market_service
        from app.services.prediction_legion_manager import get_prediction_legion_manager
        svc = get_prediction_market_service()
        legion_mgr = get_prediction_legion_manager()

        if any(kw in msg_lower for kw in ["legion", "sprint progress", "ada sprint", "how is legion"]):
            report = await legion_mgr.report_legion_quality()
            lines = [f"**Prediction Market Legion Status**"]
            lines.append(f"Completion: {report.get('completion_pct', 0):.0f}%")
            lines.append(f"Quality score: {report.get('quality_score', 0):.0f}/100")
            for rec in report.get("recommendations", []):
                lines.append(f"- {rec}")
            result = "\n".join(lines)

        elif any(kw in msg_lower for kw in ["quality", "health", "issue", "problem"]):
            report = await svc.get_quality_report()
            result = (
                f"**Prediction Market Quality Report**\n"
                f"Markets tracked: {report.get('total_markets', 0)}\n"
                f"Bettors tracked: {report.get('total_bettors', 0)}\n"
                f"Kalshi sync: {report.get('kalshi_status', 'unknown')}\n"
                f"Polymarket sync: {report.get('polymarket_status', 'unknown')}\n"
                f"Push to ADA: {report.get('push_status', 'unknown')}"
            )

        elif any(kw in msg_lower for kw in ["bettor", "leaderboard", "winner", "top"]):
            bettors = await svc.list_bettors(limit=10)
            if bettors:
                lines = ["**Top Prediction Market Bettors:**"]
                for b in bettors:
                    name = b.get("display_name") or b.get("bettor_address", "?")[:12]
                    lines.append(
                        f"- [{b.get('composite_score', 0):.0f}] {name} "
                        f"({b.get('platform', '?')}) — "
                        f"WR: {b.get('win_rate', 0):.0f}%, "
                        f"PnL: ${b.get('pnl_total', 0):,.0f}"
                    )
                result = "\n".join(lines)
            else:
                result = "No bettors tracked yet. Run bettor discovery first!"

        elif any(kw in msg_lower for kw in ["mover", "moving", "price change"]):
            markets = await svc.list_markets(limit=20)
            # Sort by volume (proxy for activity)
            markets.sort(key=lambda m: m.get("volume", 0), reverse=True)
            if markets:
                lines = ["**Active Markets (by volume):**"]
                for m in markets[:10]:
                    lines.append(
                        f"- {m.get('title', '?')[:60]} "
                        f"(Yes: {m.get('yes_price', 0):.0%}) "
                        f"Vol: ${m.get('volume', 0):,.0f}"
                    )
                result = "\n".join(lines)
            else:
                result = "No markets tracked yet. Trigger a sync first!"

        elif any(kw in msg_lower for kw in ["stat", "overview", "how many"]):
            stats = await svc.get_stats()
            result = (
                f"**Prediction Market Stats:**\n"
                f"Total markets: {stats.get('total_markets', 0)} "
                f"(Kalshi: {stats.get('kalshi_markets', 0)}, Polymarket: {stats.get('polymarket_markets', 0)})\n"
                f"Open markets: {stats.get('open_markets', 0)}\n"
                f"Bettors tracked: {stats.get('total_bettors', 0)}\n"
                f"Total volume: ${stats.get('total_volume', 0):,.0f}"
            )

        else:
            # Default: show recent markets
            markets = await svc.list_markets(limit=10)
            if markets:
                lines = ["**Prediction Markets:**"]
                for m in markets[:10]:
                    lines.append(
                        f"- [{m.get('platform', '?')}] {m.get('title', '?')[:50]} "
                        f"(Yes: {m.get('yes_price', 0):.0%})"
                    )
                result = "\n".join(lines)
            else:
                result = "No prediction markets tracked yet. Ask me to sync Kalshi or Polymarket!"

        return {"result": result, "messages": [AIMessage(content=result)]}
    except Exception as e:
        error_msg = f"Prediction market query failed: {e}"
        logger.error("prediction_market_node_error", error=str(e))
        return {"result": error_msg, "messages": [AIMessage(content=error_msg)]}


# =============================================================================
# Conditional Edge Router
# =============================================================================

async def planner_node(state: OrchestratorState) -> dict:
    """Handle complex planning requests using Gemini-powered planner.

    Decomposes task into subtasks, delegates to appropriate providers,
    and synthesizes the final result.
    """
    messages = state.get("messages", [])
    content = messages[-1].content if messages else ""

    try:
        from app.services.planner_service import get_planner_service
        planner = get_planner_service()

        # Gather context from state
        context = state.get("context", {})

        result = await planner.plan_and_execute(
            task_description=content,
            context=context,
        )

        # Format the response
        response = result["final_response"]

        # Add step summary as metadata
        steps_used = len(result.get("step_results", []))
        models_used = set(
            r.get("model_used", "unknown")
            for r in result.get("step_results", [])
        )

        logger.info(
            "planner_complete",
            steps=steps_used,
            models=list(models_used),
        )

    except Exception as e:
        logger.error("planner_node_failed", error=str(e))
        response = f"Planning failed: {e}. Try asking a more specific question."

    return {"result": response, "messages": [AIMessage(content=response)]}


async def ai_company_node(state: OrchestratorState) -> dict:
    """Handle AI Company queries — roles, tasks, delegation."""
    messages = state.get("messages", [])
    content = messages[-1].content if messages else ""
    msg_lower = content.lower()

    try:
        from app.services.agent_company_service import get_agent_company_service
        svc = get_agent_company_service()

        if any(kw in msg_lower for kw in ["create task", "new task", "delegate"]):
            # CEO plans and delegates
            result_data = await svc.ceo_plan_and_delegate(content)
            lines = [f"CEO planned {len(result_data.get('subtasks', []))} subtasks:"]
            for st in result_data.get("subtasks", []):
                lines.append(f"- [{st.get('assigned_role', '?')}] {st.get('title', 'Untitled')}")
            text = "\n".join(lines)
        elif any(kw in msg_lower for kw in ["role", "roles", "who"]):
            roles = await svc.list_roles()
            lines = ["Agent Roles:"]
            for r in roles:
                lines.append(f"- **{r.name}** ({r.id}) — {r.llm_provider}/{r.llm_model}")
            text = "\n".join(lines)
        elif any(kw in msg_lower for kw in ["stats", "status", "dashboard"]):
            stats = await svc.get_stats()
            text = (f"AI Company Stats:\n"
                    f"- Roles: {stats.total_roles}\n"
                    f"- Tasks: {stats.total_tasks} ({stats.tasks_completed} completed)\n"
                    f"- Total cost: ${stats.total_cost_usd:.4f}")
        else:
            tasks = await svc.list_tasks(limit=10)
            if tasks:
                lines = ["Recent Agent Tasks:"]
                for t in tasks:
                    lines.append(f"- [{t.status}] {t.title} → {t.assigned_role}")
                text = "\n".join(lines)
            else:
                text = "No agent tasks yet. Ask the CEO to plan a task!"

        return {"result": text, "messages": [AIMessage(content=text)]}
    except Exception as e:
        error_msg = f"AI Company query failed: {e}"
        logger.error("ai_company_node_error", error=str(e))
        return {"result": error_msg, "messages": [AIMessage(content=error_msg)]}


async def deep_research_node(state: OrchestratorState) -> dict:
    """Handle deep research queries — start research, view reports."""
    messages = state.get("messages", [])
    content = messages[-1].content if messages else ""
    msg_lower = content.lower()

    try:
        from app.services.deep_research_service import get_deep_research_service
        from app.models.agent_company import DeepResearchRequest
        svc = get_deep_research_service()

        if any(kw in msg_lower for kw in ["start", "research", "investigate", "report on"]):
            # Extract query — strip command prefixes
            query = content
            for prefix in ["deep research ", "research ", "investigate ", "report on "]:
                if msg_lower.startswith(prefix):
                    query = content[len(prefix):].strip()
                    break
            report = await svc.start_research(DeepResearchRequest(query=query))
            text = f"Deep research started: **{report.query}**\nID: {report.id}\nStatus: {report.status}"
        else:
            reports = await svc.list_reports(limit=10)
            if reports:
                lines = ["Deep Research Reports:"]
                for r in reports:
                    lines.append(f"- [{r.status}] {r.query[:80]} (ID: {r.id})")
                text = "\n".join(lines)
            else:
                text = "No deep research reports yet. Say 'deep research <topic>' to start one!"

        return {"result": text, "messages": [AIMessage(content=text)]}
    except Exception as e:
        error_msg = f"Deep research query failed: {e}"
        logger.error("deep_research_node_error", error=str(e))
        return {"result": error_msg, "messages": [AIMessage(content=error_msg)]}


async def experiment_node(state: OrchestratorState) -> dict:
    """Handle experiment queries — design, run, list experiments."""
    messages = state.get("messages", [])
    content = messages[-1].content if messages else ""
    msg_lower = content.lower()

    try:
        from app.services.experiment_service import get_experiment_service
        from app.models.agent_company import ExperimentCreate
        svc = get_experiment_service()

        if any(kw in msg_lower for kw in ["design", "create", "new experiment", "hypothesis"]):
            hypothesis = content
            for prefix in ["design experiment ", "new experiment ", "test hypothesis "]:
                if msg_lower.startswith(prefix):
                    hypothesis = content[len(prefix):].strip()
                    break
            exp = await svc.design_experiment(ExperimentCreate(hypothesis=hypothesis))
            text = f"Experiment designed: **{exp.title}**\nHypothesis: {exp.hypothesis}\nID: {exp.id}"
        elif any(kw in msg_lower for kw in ["run", "execute"]):
            exps = await svc.list_experiments(status="designed", limit=1)
            if exps:
                result = await svc.run_experiment(exps[0].id)
                text = f"Experiment running: **{result.title}** — Status: {result.status}"
            else:
                text = "No designed experiments to run. Design one first!"
        else:
            exps = await svc.list_experiments(limit=10)
            if exps:
                lines = ["Experiments:"]
                for e in exps:
                    lines.append(f"- [{e.status}] {e.title} ({e.experiment_type})")
                text = "\n".join(lines)
            else:
                text = "No experiments yet. Say 'design experiment <hypothesis>' to start!"

        return {"result": text, "messages": [AIMessage(content=text)]}
    except Exception as e:
        error_msg = f"Experiment query failed: {e}"
        logger.error("experiment_node_error", error=str(e))
        return {"result": error_msg, "messages": [AIMessage(content=error_msg)]}


async def council_node(state: OrchestratorState) -> dict:
    """Handle council queries — propose decisions, run votes, view results."""
    messages = state.get("messages", [])
    content = messages[-1].content if messages else ""
    msg_lower = content.lower()

    try:
        from app.services.council_service import get_council_service
        from app.models.agent_company import CouncilProposal
        svc = get_council_service()

        if any(kw in msg_lower for kw in ["propose", "council vote", "decide", "should we"]):
            topic = content
            for prefix in ["propose ", "council vote on ", "should we "]:
                if msg_lower.startswith(prefix):
                    topic = content[len(prefix):].strip()
                    break
            decision = await svc.propose(CouncilProposal(topic=topic))
            text = f"Council decision proposed: **{decision.topic}**\nID: {decision.id}\nRun vote with: council vote {decision.id}"
        elif any(kw in msg_lower for kw in ["vote", "run vote"]):
            decisions = await svc.list_decisions(status="proposed", limit=1)
            if decisions:
                result = await svc.conduct_vote(decisions[0].id)
                text = (f"Council voted on: **{result.topic}**\n"
                        f"Decision: {result.decision}\n"
                        f"Confidence: {result.confidence_score:.0f}%")
            else:
                text = "No pending council decisions. Propose one first!"
        else:
            decisions = await svc.list_decisions(limit=10)
            if decisions:
                lines = ["Council Decisions:"]
                for d in decisions:
                    status = d.decision or "pending"
                    lines.append(f"- [{status}] {d.topic} (confidence: {d.confidence_score:.0f}%)")
                text = "\n".join(lines)
            else:
                text = "No council decisions yet. Say 'propose <topic>' to start a council vote!"

        return {"result": text, "messages": [AIMessage(content=text)]}
    except Exception as e:
        error_msg = f"Council query failed: {e}"
        logger.error("council_node_error", error=str(e))
        return {"result": error_msg, "messages": [AIMessage(content=error_msg)]}


async def character_content_node(state: OrchestratorState) -> dict:
    """Handle character content queries — research, generate carousels, review."""
    messages = state.get("messages", [])
    content = messages[-1].content if messages else ""
    msg_lower = content.lower()

    try:
        from app.services.character_content_service import get_character_content_service
        svc = get_character_content_service()

        if any(kw in msg_lower for kw in ["seed", "populate", "add characters"]):
            chars = await svc.seed_characters()
            text = f"Seeded {len(chars)} characters: {', '.join(c.name for c in chars[:10])}"
        elif any(kw in msg_lower for kw in ["research", "investigate"]):
            chars = await svc.list_characters(research_status="pending", limit=3)
            if chars:
                char = chars[0]
                await svc.research_character(char.id)
                text = f"Started research pipeline for **{char.name}** ({char.universe}). Check back in a minute."
            else:
                text = "All characters already researched or none found. Seed characters first."
        elif any(kw in msg_lower for kw in ["generate", "carousel", "create post"]):
            chars = await svc.list_characters(research_status="completed", limit=5)
            if chars:
                from app.models.character_content import CarouselCreate
                carousel = await svc.generate_carousel(CarouselCreate(character_id=chars[0].id))
                text = (f"Generated carousel for **{carousel.character_name}**: {carousel.title}\n"
                        f"Hook: {carousel.hook_text}\n"
                        f"Slides: {len(carousel.slides)} | Status: {carousel.status}")
            else:
                text = "No researched characters available. Run research first."
        elif any(kw in msg_lower for kw in ["review", "pending", "queue"]):
            queue = await svc.list_review_queue(limit=5)
            if queue:
                lines = [f"Review Queue ({len(queue)} items):"]
                for c in queue:
                    score = c.ai_review.get("overall_score", "?") if c.ai_review else "?"
                    lines.append(f"- {c.character_name}: {c.title} (AI: {score}/10)")
                text = "\n".join(lines)
            else:
                text = "Review queue is empty."
        else:
            stats = await svc.get_stats()
            text = (f"Character Content Stats:\n"
                    f"- {stats.total_characters} characters ({stats.characters_researched} researched)\n"
                    f"- {stats.total_carousels} carousels ({stats.total_published} published)\n"
                    f"- {stats.total_views:,} views, {stats.total_likes:,} likes")

        return {"result": text, "messages": [AIMessage(content=text)]}
    except Exception as e:
        error_msg = f"Character content query failed: {e}"
        logger.error("character_content_node_error", error=str(e))
        return {"result": error_msg, "messages": [AIMessage(content=error_msg)]}


async def pkm_node(state: OrchestratorState) -> dict:
    """PKM / vault surface. Searches the indexed Obsidian vault and returns hits.

    SecondBrain Phase 3. For writes, the supervisor goes through vault_writer
    (agent namespace) or cyanheads MCP (append-only markers on human-owned notes).
    """
    messages = state.get("messages", [])
    content = messages[-1].content if messages else ""
    try:
        from app.services.vault_retrieval_service import get_vault_retrieval
        svc = get_vault_retrieval()
        result = await svc.search(content or "", top_k=8)
        if not result.get("hits"):
            text = "No matching vault content yet. Has the vault been indexed? Try `POST /api/vault/reindex`."
        else:
            lines = [f"Vault hits ({result['bm25_count']} BM25, {result['dense_count']} dense, fused top-{len(result['hits'])})"]
            for h in result["hits"]:
                lines.append(
                    f"- `[{h['partition']}]` {h['path']}"
                    + (f" > {h['heading_path']}" if h.get("heading_path") else "")
                    + f" (score {h['score']:.3f})\n  {h['content'][:240]}..."
                )
            text = "\n".join(lines)
    except Exception as e:  # noqa: BLE001
        text = f"PKM node error: {e}"
    return {"result": text, "route": "pkm"}


async def legion_ops_node(state: OrchestratorState) -> dict:
    """Delegates code-improvement work to Legion. Gated by approval_queue.

    SecondBrain Phase 3. For now this is a thin wrapper that surfaces Legion
    health + the legion_client capability set. Actual task dispatch with
    interrupt()-gated approval lands in Phase 2.5 when Legion is hardened.
    """
    messages = state.get("messages", [])
    content = messages[-1].content if messages else ""
    try:
        from app.services.legion_client import get_legion_client
        client = get_legion_client()
        try:
            metrics = await client.get_project_metrics(
                project_id=int(getattr(client, "_project_id", 8))
            )
            summary = (
                f"Legion project 8 metrics: "
                f"tasks_open={metrics.get('tasks_open', '?')}, "
                f"sprints_active={metrics.get('sprints_active', '?')}"
            )
        except Exception as e:  # noqa: BLE001
            summary = f"Legion unreachable or project metrics missing: {e}"
        text = (
            f"legion_ops received: {content[:120]}...\n\n"
            f"Status: {summary}\n"
            "Task dispatch with approval gating arrives in Phase 2.5. For now, use "
            "`zero-deep-review` to audit Legion or `GET /api/legion/health` in the UI."
        )
    except Exception as e:  # noqa: BLE001
        text = f"legion_ops node error: {e}"
    return {"result": text, "route": "legion_ops"}


async def brain_node(state: OrchestratorState) -> dict:
    """Handle Zero Brain queries — status, benchmarks, learnings, memory."""
    messages = state.get("messages", [])
    content = messages[-1].content if messages else ""
    msg_lower = content.lower()

    try:
        from app.services.zero_brain_service import get_zero_brain_service
        svc = get_zero_brain_service()

        if any(kw in msg_lower for kw in ["benchmark", "score", "how am i doing"]):
            status = await svc.get_status()
            dims = status.dimension_scores
            top3 = sorted(dims.items(), key=lambda x: x[1].score, reverse=True)[:3]
            bot3 = sorted(dims.items(), key=lambda x: x[1].score)[:3]
            text = (
                f"Brain Score: **{status.overall_score:.1f}/100**\n"
                f"Weakest: {status.weakest_dimension}\n"
                f"Top: {', '.join(f'{d}={s.score:.0f}' for d, s in top3)}\n"
                f"Bottom: {', '.join(f'{d}={s.score:.0f}' for d, s in bot3)}\n"
                f"Memories: {status.total_memories} | Outcomes: {status.total_outcomes} | "
                f"Experiments: {status.active_experiments}"
            )
        elif any(kw in msg_lower for kw in ["learn", "what have you learned"]):
            learnings = await svc.get_learnings(days=7, limit=5)
            if learnings:
                text = "Recent Learnings:\n" + "\n".join(f"- {l}" for l in learnings)
            else:
                text = "No learnings recorded in the last 7 days."
        elif any(kw in msg_lower for kw in ["memory", "remember", "episodic"]):
            # Search memories with the query
            query = content.replace("memory", "").replace("search", "").strip()
            results = await svc.search_memory(query or "recent activity", limit=5)
            if results:
                text = "Matching Memories:\n" + "\n".join(
                    f"- [{r.memory.namespace}] {r.memory.content} ({r.similarity:.0%})"
                    for r in results
                )
            else:
                text = "No matching memories found."
        elif any(kw in msg_lower for kw in ["improve", "self-improve"]):
            result = await svc.run_improvement()
            text = (f"Improvement target: **{result['target_dimension']}** "
                    f"(score: {result['current_score']:.1f})\n"
                    f"Action: {result.get('improvement_action', 'None')}")
        elif "calibration" in msg_lower:
            cal = await svc.get_calibration()
            buckets = cal.get("buckets", [])
            if buckets:
                lines = ["Calibration Report:"]
                for b in buckets:
                    lines.append(f"- {b['range_label']}: {b['count']} records, "
                                f"MAE={b['mae']:.1f}")
                text = "\n".join(lines)
            else:
                text = "No calibration data yet."
        else:
            status = await svc.get_status()
            text = (
                f"Zero Brain: **{status.overall_score:.1f}/100**\n"
                f"Memories: {status.total_memories} | Outcomes: {status.total_outcomes} | "
                f"Prompts: {status.total_prompt_variants} | Experiments: {status.active_experiments}\n"
                f"Weakest: {status.weakest_dimension}"
            )

        return {"result": text, "messages": [AIMessage(content=text)]}
    except Exception as e:
        error_msg = f"Brain query failed: {e}"
        logger.error("brain_node_error", error=str(e))
        return {"result": error_msg, "messages": [AIMessage(content=error_msg)]}


def route_by_classification(state: OrchestratorState) -> str:
    """Route to the appropriate node based on classification."""
    route = state.get("route", "general")
    return route if route in VALID_ROUTES else "general"


# =============================================================================
# Graph Builder
# =============================================================================

def _make_traced(name: str, func, order: int):
    """Create a traced wrapper for a node function."""
    async def traced(state):
        return await _trace_node(func, state, name, order)
    traced.__name__ = f"traced_{name}"
    return traced


def build_orchestration_graph(checkpointer=None) -> Any:
    """Build and compile the orchestration supervisor StateGraph."""
    graph = StateGraph(OrchestratorState)

    # Add nodes with tracing wrappers
    graph.add_node("router", _make_traced("router", router_node, 0))

    _domain_nodes = {
        "sprint": sprint_node,
        "email": email_node,
        "calendar": calendar_node,
        "enhancement": enhancement_node,
        "briefing": briefing_node,
        "research": research_node,
        "notion": notion_node,
        "money_maker": money_maker_node,
        "knowledge": knowledge_node,
        "task": task_node,
        "workflow": workflow_node,
        "system": system_node,
        "tiktok": tiktok_node,
        "content": content_node,
        "prediction_market": prediction_market_node,
        "planner": planner_node,
        "ai_company": ai_company_node,
        "deep_research": deep_research_node,
        "experiment": experiment_node,
        "council": council_node,
        "character_content": character_content_node,
        "brain": brain_node,
        "pkm": pkm_node,
        "legion_ops": legion_ops_node,
        "general": general_node,
    }
    for i, (name, func) in enumerate(_domain_nodes.items(), start=1):
        graph.add_node(name, _make_traced(name, func, i))

    graph.add_node("synthesizer", _make_traced("synthesizer", synthesizer_node, 99))

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
            "notion": "notion",
            "money_maker": "money_maker",
            "knowledge": "knowledge",
            "task": "task",
            "workflow": "workflow",
            "system": "system",
            "tiktok": "tiktok",
            "content": "content",
            "prediction_market": "prediction_market",
            "planner": "planner",
            "ai_company": "ai_company",
            "deep_research": "deep_research",
            "experiment": "experiment",
            "council": "council",
            "character_content": "character_content",
            "brain": "brain",
            "pkm": "pkm",
            "legion_ops": "legion_ops",
            "general": "general",
        },
    )

    # Specialized nodes -> synthesizer -> END
    for node in ["sprint", "email", "calendar", "enhancement",
                 "briefing", "research", "notion", "money_maker",
                 "knowledge", "task", "workflow", "system",
                 "tiktok", "content", "prediction_market",
                 "ai_company", "deep_research", "experiment", "council",
                 "character_content", "brain", "pkm", "legion_ops"]:
        graph.add_edge(node, "synthesizer")
    graph.add_edge("synthesizer", END)

    # General node goes straight to END (already conversational)
    graph.add_edge("general", END)

    # Planner node goes straight to END (produces fully synthesized response)
    graph.add_edge("planner", END)

    # Compile
    compile_kwargs = {}
    if checkpointer:
        compile_kwargs["checkpointer"] = checkpointer

    compiled = graph.compile(**compile_kwargs)
    logger.info("orchestration_graph_compiled",
                nodes=list(VALID_ROUTES) + ["synthesizer"],
                checkpointer=type(checkpointer).__name__ if checkpointer else "none")
    return compiled


# =============================================================================
# Singleton with Optional Checkpointing
# =============================================================================

_compiled_graph = None


async def get_orchestration_graph():
    """Get the compiled orchestration graph with optional PostgreSQL checkpointing."""
    global _compiled_graph
    if _compiled_graph is not None:
        return _compiled_graph

    from app.infrastructure.checkpoint import get_checkpointer
    checkpointer = await get_checkpointer()

    _compiled_graph = build_orchestration_graph(checkpointer=checkpointer)
    return _compiled_graph


async def invoke_orchestration(
    message: str,
    thread_id: str = "default",
    channel: str = "api",
) -> dict:
    """Invoke the orchestration graph with a user message.

    Records conversation + per-node traces for full observability.
    """
    from app.services.orchestrator_trace_service import record_conversation, update_conversation_route

    # Record inbound conversation
    conv_id = await record_conversation(
        thread_id=thread_id,
        channel=channel,
        message=message,
        direction="inbound",
    )

    graph = await get_orchestration_graph()
    start = _time.time()

    config = {"configurable": {"thread_id": thread_id}}
    input_state = {
        "messages": [HumanMessage(content=message)],
        "route": None,
        "context": {
            "_trace_conversation_id": conv_id,
            "_trace_thread_id": thread_id,
        },
        "result": None,
    }

    try:
        result = await graph.ainvoke(input_state, config=config)
        latency_ms = round((_time.time() - start) * 1000, 1)

        route = result.get("route", "unknown")
        response_text = result.get("result", "No result generated.")
        ctx = result.get("context", {})

        # Record outbound response
        await record_conversation(
            thread_id=thread_id,
            channel=channel,
            message=response_text[:10000],
            direction="outbound",
            route=route,
            route_method=ctx.get("method"),
            route_confidence=ctx.get("keyword_confidence"),
            latency_ms=latency_ms,
        )

        # Backfill inbound record with route info (for stats/filtering)
        await update_conversation_route(
            conversation_id=conv_id,
            route=route,
            route_method=ctx.get("method"),
            route_confidence=ctx.get("keyword_confidence"),
            latency_ms=latency_ms,
        )

        return {
            "result": response_text,
            "route": route,
            "thread_id": thread_id,
            "conversation_id": conv_id,
            "latency_ms": latency_ms,
        }
    except Exception as e:
        latency_ms = round((_time.time() - start) * 1000, 1)
        await record_conversation(
            thread_id=thread_id,
            channel=channel,
            message=str(e),
            direction="outbound",
            error=str(e),
            latency_ms=latency_ms,
        )
        # Backfill inbound record with error info
        await update_conversation_route(
            conversation_id=conv_id,
            latency_ms=latency_ms,
            error=str(e),
        )
        raise
