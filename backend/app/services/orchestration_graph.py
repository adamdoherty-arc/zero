"""
LangGraph Orchestration Gateway for Zero.

Two-tier intelligent routing: fast keyword matching for unambiguous requests,
LLM-based classification for ambiguous queries. Includes response synthesis
for natural conversational output.

Routes: sprint, email, calendar, enhancement, briefing, research, notion,
        money_maker, knowledge, task, workflow, system, general.
"""

from typing import TypedDict, Annotated, Optional, Any
from datetime import datetime
from functools import lru_cache
import re

from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langchain_core.messages import HumanMessage, AIMessage

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
    memories: Optional[list]


# =============================================================================
# Route Classification - Two-Tier System
# =============================================================================

VALID_ROUTES = {
    "sprint", "email", "calendar", "enhancement", "briefing",
    "research", "notion", "money_maker", "knowledge", "task",
    "workflow", "system", "tiktok", "content", "prediction_market",
    "planner", "general",
}

ROUTE_KEYWORDS = {
    "sprint": ["sprint", "project", "legion", "backlog", "progress", "velocity"],
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
    "- **planner** — complex multi-step planning (uses Gemini 3.1 Pro for deep reasoning)\n\n"
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


async def classify_route_llm(message: str) -> str:
    """Tier 2: LLM-based intent classification for ambiguous queries."""
    try:
        from app.infrastructure.ollama_client import get_ollama_client
        client = get_ollama_client()
        result = await client.chat(
            f"Classify this message: {message}",
            system=CLASSIFICATION_SYSTEM_PROMPT,
            task_type="classification",
            temperature=0.0,
            num_predict=20,
            timeout=10,
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
                from app.infrastructure.ollama_client import get_ollama_client
                client = get_ollama_client()
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
    """Handle general queries using LLM for conversational response."""
    messages = state.get("messages", [])
    content = messages[-1].content if messages else ""

    try:
        from app.infrastructure.ollama_client import get_ollama_client
        client = get_ollama_client()
        result = await client.chat_safe(
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
        from app.infrastructure.ollama_client import get_ollama_client
        client = get_ollama_client()
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
            task_type="chat",
            temperature=0.3,
            num_predict=1024,
            timeout=30,
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


def route_by_classification(state: OrchestratorState) -> str:
    """Route to the appropriate node based on classification."""
    route = state.get("route", "general")
    return route if route in VALID_ROUTES else "general"


# =============================================================================
# Graph Builder
# =============================================================================

def build_orchestration_graph(checkpointer=None) -> Any:
    """Build and compile the orchestration supervisor StateGraph."""
    graph = StateGraph(OrchestratorState)

    # Add nodes
    graph.add_node("router", router_node)
    graph.add_node("sprint", sprint_node)
    graph.add_node("email", email_node)
    graph.add_node("calendar", calendar_node)
    graph.add_node("enhancement", enhancement_node)
    graph.add_node("briefing", briefing_node)
    graph.add_node("research", research_node)
    graph.add_node("notion", notion_node)
    graph.add_node("money_maker", money_maker_node)
    graph.add_node("knowledge", knowledge_node)
    graph.add_node("task", task_node)
    graph.add_node("workflow", workflow_node)
    graph.add_node("system", system_node)
    graph.add_node("tiktok", tiktok_node)
    graph.add_node("content", content_node)
    graph.add_node("prediction_market", prediction_market_node)
    graph.add_node("planner", planner_node)
    graph.add_node("general", general_node)
    graph.add_node("synthesizer", synthesizer_node)

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
            "general": "general",
        },
    )

    # Specialized nodes -> synthesizer -> END
    for node in ["sprint", "email", "calendar", "enhancement",
                 "briefing", "research", "notion", "money_maker",
                 "knowledge", "task", "workflow", "system",
                 "tiktok", "content", "prediction_market"]:
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


async def invoke_orchestration(message: str, thread_id: str = "default") -> dict:
    """Invoke the orchestration graph with a user message."""
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
