"""
Ask Zero Chat Service

Conversational AI assistant with:
- Multi-turn conversation memory (in-memory, session-based)
- Rich context injection from all Zero domain services
- Project-aware system prompts
- Streaming responses via Ollama chat API
- LangChain message types for conversation management

Modeled after Legion's chat_service.py, adapted for Zero's 13+ domain services.
"""

import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, AsyncIterator, Dict, List, Optional

import structlog
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from app.infrastructure.ollama_client import get_ollama_client

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ConversationSession:
    session_id: str
    messages: List[BaseMessage] = field(default_factory=list)
    project_id: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)
    title: Optional[str] = None


@dataclass
class ChatResponse:
    content: str
    session_id: str
    sources: List[Dict[str, Any]] = field(default_factory=list)
    model: str = ""


# ---------------------------------------------------------------------------
# In-memory session store
# ---------------------------------------------------------------------------

_sessions: Dict[str, ConversationSession] = {}
SESSION_TTL_SECONDS = 86400  # 24 hours

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

ZERO_SYSTEM_PROMPT = """You are Zero, a personal AI assistant that manages sprints, tasks, emails, calendar, knowledge, research, finances, and more.

You help with:
- Sprint status, task tracking, project health
- Email summaries, unread counts, important messages
- Calendar events, today's schedule, upcoming meetings
- Knowledge base: notes, user facts, contacts
- Research topics, findings, and trends
- Money-making ideas and financial opportunities
- Notifications and reminders
- Enhancement signals and code quality

Guidelines:
- Be concise and actionable
- Reference specific data from the Live Context section below
- ONLY report data explicitly shown in Live Context — never fabricate statistics, names, dates, or counts
- If a section shows no data, say so honestly
- Suggest concrete next steps when appropriate
- For follow-up questions, use conversation history for context"""

# Max chars for conversation history sent to LLM
MAX_CONTEXT_CHARS = 48000


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class ChatService:
    """
    Context-aware conversational AI backed by Zero's domain services.
    """

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    @staticmethod
    def _cleanup_expired():
        now = time.time()
        expired = [
            sid for sid, s in _sessions.items()
            if now - s.last_active > SESSION_TTL_SECONDS
        ]
        for sid in expired:
            del _sessions[sid]

    @staticmethod
    def get_or_create_session(
        session_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> ConversationSession:
        ChatService._cleanup_expired()

        if session_id and session_id in _sessions:
            session = _sessions[session_id]
            session.last_active = time.time()
            if project_id is not None:
                session.project_id = project_id
            return session

        new_id = session_id or str(uuid.uuid4())
        session = ConversationSession(
            session_id=new_id,
            project_id=project_id,
        )
        _sessions[new_id] = session
        return session

    @staticmethod
    def list_sessions() -> List[Dict[str, Any]]:
        ChatService._cleanup_expired()
        results = []
        for s in sorted(_sessions.values(), key=lambda x: x.last_active, reverse=True):
            results.append({
                "session_id": s.session_id,
                "title": s.title,
                "project_id": s.project_id,
                "message_count": len([m for m in s.messages if not isinstance(m, SystemMessage)]),
                "created_at": datetime.fromtimestamp(s.created_at).isoformat(),
                "last_active": datetime.fromtimestamp(s.last_active).isoformat(),
            })
        return results

    @staticmethod
    def get_session_history(session_id: str) -> Optional[List[Dict[str, str]]]:
        if session_id not in _sessions:
            return None
        session = _sessions[session_id]
        return [
            {"role": _msg_role(m), "content": m.content}
            for m in session.messages
            if not isinstance(m, SystemMessage)
        ]

    @staticmethod
    def delete_session(session_id: str) -> bool:
        if session_id in _sessions:
            del _sessions[session_id]
            return True
        return False

    # ------------------------------------------------------------------
    # Context building
    # ------------------------------------------------------------------

    @staticmethod
    async def _gather_context(project_id: Optional[str] = None) -> tuple[str, List[Dict[str, Any]]]:
        """Gather live context from all Zero services. Returns (context_text, sources)."""
        parts = []
        sources = []

        # Sprint context
        try:
            from app.services.sprint_service import get_sprint_service
            svc = get_sprint_service()
            sprints = await svc.list_sprints(status="active")
            if sprints:
                lines = [f"Active sprints: {len(sprints)}"]
                for s in sprints[:5]:
                    lines.append(f"  - {s.name} [{s.status}] (points: {s.completed_points}/{s.total_points})")
                parts.append("## Sprints\n" + "\n".join(lines))
                sources.append({"name": "sprints", "description": f"{len(sprints)} active sprint(s)"})
            else:
                parts.append("## Sprints\nNo active sprints.")
        except Exception as e:
            logger.debug("chat_context_sprints_failed", error=str(e))

        # Task context
        try:
            from app.services.task_service import get_task_service
            svc = get_task_service()
            tasks = await svc.list_tasks(limit=50)
            if tasks:
                status_counts: Dict[str, int] = {}
                for t in tasks:
                    status_counts[t.status] = status_counts.get(t.status, 0) + 1
                breakdown = ", ".join(f"{s}: {c}" for s, c in sorted(status_counts.items()))
                parts.append(f"## Tasks\nTotal recent: {len(tasks)} | {breakdown}")
                blocked = [t for t in tasks if t.status == "blocked"]
                if blocked:
                    parts[-1] += "\nBlocked tasks:"
                    for t in blocked[:3]:
                        parts[-1] += f"\n  - {t.title}" + (f" ({t.blocked_reason})" if t.blocked_reason else "")
                sources.append({"name": "tasks", "description": f"{len(tasks)} tasks ({breakdown})"})
        except Exception as e:
            logger.debug("chat_context_tasks_failed", error=str(e))

        # Project context
        try:
            from app.services.project_service import get_project_service
            svc = get_project_service()
            projects = await svc.list_projects()
            if projects:
                lines = [f"Registered projects: {len(projects)}"]
                for p in projects[:5]:
                    lines.append(f"  - {p.name} [{p.status}]")
                parts.append("## Projects\n" + "\n".join(lines))
                sources.append({"name": "projects", "description": f"{len(projects)} project(s)"})
        except Exception as e:
            logger.debug("chat_context_projects_failed", error=str(e))

        # Calendar context
        try:
            from app.services.calendar_service import get_calendar_service
            svc = get_calendar_service()
            schedule = await svc.get_today_schedule()
            events = schedule.events if hasattr(schedule, 'events') else []
            if events:
                lines = [f"Today's events: {len(events)}"]
                for ev in events[:5]:
                    summary = ev.get("summary", ev) if isinstance(ev, dict) else str(ev)
                    lines.append(f"  - {summary}")
                parts.append("## Calendar\n" + "\n".join(lines))
                sources.append({"name": "calendar", "description": f"{len(events)} event(s) today"})
            else:
                parts.append("## Calendar\nNo events today.")
        except Exception as e:
            logger.debug("chat_context_calendar_failed", error=str(e))

        # Email context
        try:
            from app.services.gmail_service import get_gmail_service
            from app.models.email import EmailStatus
            svc = get_gmail_service()
            emails = await svc.list_emails(status=EmailStatus.UNREAD, limit=10)
            count = len(emails) if emails else 0
            if count > 0:
                lines = [f"Unread emails: {count}"]
                for em in emails[:3]:
                    subj = getattr(em, "subject", "No subject")
                    lines.append(f"  - {subj}")
                parts.append("## Email\n" + "\n".join(lines))
                sources.append({"name": "email", "description": f"{count} unread email(s)"})
            else:
                parts.append("## Email\nInbox clear — no unread emails.")
        except Exception as e:
            logger.debug("chat_context_email_failed", error=str(e))

        # Knowledge context
        try:
            from app.services.knowledge_service import get_knowledge_service
            svc = get_knowledge_service()
            profile = await svc.get_user_profile()
            notes = await svc.list_notes(limit=5)
            facts = profile.facts if profile else []
            lines = []
            if profile:
                lines.append(f"User: {profile.name}")
            if facts:
                lines.append(f"Known facts: {len(facts)}")
                for f in facts[:3]:
                    lines.append(f"  - {f.fact}")
            if notes:
                lines.append(f"Recent notes: {len(notes)}")
            if lines:
                parts.append("## Knowledge\n" + "\n".join(lines))
                sources.append({"name": "knowledge", "description": f"{len(facts)} facts, {len(notes)} notes"})
        except Exception as e:
            logger.debug("chat_context_knowledge_failed", error=str(e))

        # Research context
        try:
            from app.services.research_service import get_research_service
            svc = get_research_service()
            stats = await svc.get_stats()
            if stats:
                total = getattr(stats, "total_topics", 0) if not isinstance(stats, dict) else stats.get("total_topics", 0)
                findings_week = getattr(stats, "findings_this_week", 0) if not isinstance(stats, dict) else stats.get("findings_this_week", 0)
                parts.append(f"## Research\nActive topics: {total} | Findings this week: {findings_week}")
                sources.append({"name": "research", "description": f"{total} topics, {findings_week} findings this week"})
        except Exception as e:
            logger.debug("chat_context_research_failed", error=str(e))

        # Money maker context
        try:
            from app.services.money_maker_service import get_money_maker_service
            svc = get_money_maker_service()
            stats = await svc.get_stats()
            if stats:
                total = stats.get("total_ideas", 0) if isinstance(stats, dict) else 0
                active = stats.get("active_ideas", 0) if isinstance(stats, dict) else 0
                if total > 0:
                    parts.append(f"## Money Maker\nTotal ideas: {total} | Active: {active}")
                    sources.append({"name": "money_maker", "description": f"{total} ideas, {active} active"})
        except Exception as e:
            logger.debug("chat_context_money_failed", error=str(e))

        # Notification context
        try:
            from app.services.notification_service import get_notification_service
            svc = get_notification_service()
            unread = await svc.get_unread_count()
            if unread > 0:
                parts.append(f"## Notifications\nUnread: {unread}")
                sources.append({"name": "notifications", "description": f"{unread} unread"})
        except Exception as e:
            logger.debug("chat_context_notifications_failed", error=str(e))

        context_text = "\n\n".join(parts) if parts else "No live data available."
        return context_text, sources

    @staticmethod
    async def _build_system_prompt(
        query: str, session: ConversationSession
    ) -> tuple[str, List[Dict[str, Any]]]:
        """Build full system prompt with injected live context."""
        prompt_parts = [ZERO_SYSTEM_PROMPT]

        live_ctx, sources = await ChatService._gather_context(session.project_id)
        prompt_parts.append(f"\n## Live Context\n{live_ctx}")

        return "\n".join(prompt_parts), sources

    # ------------------------------------------------------------------
    # Conversation windowing
    # ------------------------------------------------------------------

    @staticmethod
    def _build_message_window(
        system_prompt: str,
        messages: List[BaseMessage],
    ) -> List[Dict[str, str]]:
        """Convert LangChain messages to Ollama format with sliding window."""
        ollama_msgs = [{"role": "system", "content": system_prompt}]
        budget = MAX_CONTEXT_CHARS - len(system_prompt)

        window: List[Dict[str, str]] = []
        for msg in reversed(messages):
            entry = {"role": _msg_role(msg), "content": msg.content}
            cost = len(msg.content)
            if budget - cost < 0:
                break
            window.insert(0, entry)
            budget -= cost

        ollama_msgs.extend(window)
        return ollama_msgs

    # ------------------------------------------------------------------
    # Chat (non-streaming)
    # ------------------------------------------------------------------

    async def chat(
        self,
        message: str,
        session_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> ChatResponse:
        session = self.get_or_create_session(session_id, project_id)
        session.messages.append(HumanMessage(content=message))

        if not session.title:
            session.title = message[:60] + ("..." if len(message) > 60 else "")

        system_prompt, sources = await self._build_system_prompt(message, session)
        ollama_msgs = self._build_message_window(system_prompt, session.messages)

        client = get_ollama_client()
        try:
            content = await client.chat(
                messages=ollama_msgs,
                task_type="chat",
                temperature=0.5,
                num_predict=4096,
            )
            model = client._resolve_model(None, "chat")
        except Exception as e:
            logger.error("ask_zero_chat_failed", error=str(e))
            content = f"Sorry, I couldn't generate a response. Error: {e}"
            model = "error"

        session.messages.append(AIMessage(content=content))

        return ChatResponse(
            content=content,
            session_id=session.session_id,
            sources=sources,
            model=model,
        )

    # ------------------------------------------------------------------
    # Chat (streaming via SSE)
    # ------------------------------------------------------------------

    async def chat_stream(
        self,
        message: str,
        session_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> AsyncIterator[str]:
        """Stream a chat response as SSE events."""
        session = self.get_or_create_session(session_id, project_id)
        session.messages.append(HumanMessage(content=message))

        if not session.title:
            session.title = message[:60] + ("..." if len(message) > 60 else "")

        system_prompt, sources = await self._build_system_prompt(message, session)
        ollama_msgs = self._build_message_window(system_prompt, session.messages)

        client = get_ollama_client()
        model_name = client._resolve_model(None, "chat")
        full_content = ""

        try:
            async for chunk in client.chat_stream(
                messages=ollama_msgs,
                task_type="chat",
                temperature=0.5,
                num_predict=4096,
            ):
                full_content += chunk
                yield f'data: {json.dumps({"type": "chunk", "content": chunk})}\n\n'
        except Exception as e:
            logger.error("ask_zero_stream_failed", error=str(e))
            error_msg = f"Sorry, I couldn't generate a response. Error: {e}"
            yield f'data: {json.dumps({"type": "chunk", "content": error_msg})}\n\n'
            full_content = error_msg

        session.messages.append(AIMessage(content=full_content))

        yield f'data: {json.dumps({"type": "done", "session_id": session.session_id, "sources": sources, "model": model_name})}\n\n'


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _msg_role(msg: BaseMessage) -> str:
    if isinstance(msg, HumanMessage):
        return "user"
    elif isinstance(msg, AIMessage):
        return "assistant"
    elif isinstance(msg, SystemMessage):
        return "system"
    return "user"
