"""
Supervisor graph — the single agent the voice loop talks to.

Decides whether to answer directly (small talk, persona-only chat) or fan
out to a sub-agent (email, calendar, company ops, research, bookkeeper,
daily brief). Each sub-agent is a thin adapter over a service that already
exists in Zero — we are unifying, not rebuilding.

State machine (intentionally simple; LangGraph optional via env):

    classify ─┬─> direct_reply   ──> finalize
              ├─> dispatch_email ──> finalize
              ├─> dispatch_calendar ──> finalize
              ├─> dispatch_company  ──> finalize
              ├─> dispatch_research ──> finalize
              ├─> dispatch_bookkeeper ──> finalize
              └─> dispatch_brief ──> finalize

Voice loop usage:

    sup = get_supervisor()
    result = await sup.handle(
        user_text="what's on my calendar today?",
        persona_id="default",
    )
    # result.spoken: short prose for TTS
    # result.tool_calls: structured trace for logging / dashboard
    # result.followups: list of approval prompts to surface
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Awaitable, Callable, Optional

import structlog

logger = structlog.get_logger()

USE_LANGGRAPH = os.getenv("ZERO_SUPERVISOR_LANGGRAPH", "").strip().lower() in (
    "1", "true", "yes",
)


@dataclass
class SupervisorResult:
    intent: str
    spoken: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    followups: list[dict[str, Any]] = field(default_factory=list)
    direct: bool = False
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "spoken": self.spoken,
            "tool_calls": list(self.tool_calls),
            "followups": list(self.followups),
            "direct": self.direct,
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# Sub-agent adapters — every adapter takes (user_text, ctx) and returns a
# SupervisorResult. Adapters MUST be defensive: they run inside the voice
# loop, so any uncaught exception kills the turn. Catch broadly, log, and
# return a graceful spoken response.
# ---------------------------------------------------------------------------

AdapterFn = Callable[[str, dict[str, Any]], Awaitable[SupervisorResult]]


async def _email_adapter(user_text: str, ctx: dict[str, Any]) -> SupervisorResult:
    try:
        from app.services.email_automation_service import (
            get_email_automation_service,
        )
        svc = get_email_automation_service()
        # Pull a quick summary of unread/important — same surface the
        # Reachy email triage router uses.
        try:
            summary = await svc.summary_for_voice()  # type: ignore[attr-defined]
        except AttributeError:
            try:
                summary = await svc.recent_summary()  # type: ignore[attr-defined]
            except AttributeError:
                summary = "Email summary not available."
        return SupervisorResult(
            intent="email",
            spoken=str(summary)[:500],
            tool_calls=[{"adapter": "email", "ok": True}],
        )
    except Exception as e:
        logger.warning("supervisor_email_adapter_failed", error=str(e))
        return SupervisorResult(
            intent="email",
            spoken="I couldn't reach your email right now.",
            tool_calls=[{"adapter": "email", "ok": False, "error": str(e)}],
            error=str(e),
        )


async def _calendar_adapter(user_text: str, ctx: dict[str, Any]) -> SupervisorResult:
    try:
        from app.services.calendar_service import get_calendar_service
        svc = get_calendar_service()
        try:
            today = await svc.today_summary_for_voice()  # type: ignore[attr-defined]
        except AttributeError:
            try:
                today = await svc.summary_for_today()  # type: ignore[attr-defined]
            except AttributeError:
                today = "Calendar summary not available."
        return SupervisorResult(
            intent="calendar",
            spoken=str(today)[:500],
            tool_calls=[{"adapter": "calendar", "ok": True}],
        )
    except Exception as e:
        logger.warning("supervisor_calendar_adapter_failed", error=str(e))
        return SupervisorResult(
            intent="calendar",
            spoken="I couldn't reach your calendar right now.",
            tool_calls=[{"adapter": "calendar", "ok": False, "error": str(e)}],
            error=str(e),
        )


async def _company_adapter(user_text: str, ctx: dict[str, Any]) -> SupervisorResult:
    try:
        from app.services.company_operator_service import (
            get_company_operator_service,
        )
        svc = get_company_operator_service()
        try:
            brief = await svc.voice_brief()  # type: ignore[attr-defined]
        except AttributeError:
            try:
                brief = await svc.brief()  # type: ignore[attr-defined]
            except AttributeError:
                brief = (
                    "ADA AI status: company operator not yet exposing a voice brief."
                )
        return SupervisorResult(
            intent="company",
            spoken=str(brief)[:500],
            tool_calls=[{"adapter": "company", "ok": True}],
        )
    except Exception as e:
        logger.warning("supervisor_company_adapter_failed", error=str(e))
        return SupervisorResult(
            intent="company",
            spoken="I couldn't pull ADA AI's status right now.",
            tool_calls=[{"adapter": "company", "ok": False, "error": str(e)}],
            error=str(e),
        )


async def _research_adapter(user_text: str, ctx: dict[str, Any]) -> SupervisorResult:
    try:
        from app.services.deep_research_service import get_deep_research_service  # type: ignore
        svc = get_deep_research_service()
        try:
            handle = await svc.start(query=user_text, source="reachy_voice")  # type: ignore[attr-defined]
            ref = getattr(handle, "id", None) or getattr(handle, "task_id", None) or "queued"
            return SupervisorResult(
                intent="research",
                spoken=f"I queued a researcher on that. I'll bring back the findings as soon as it's done.",
                tool_calls=[{"adapter": "research", "ok": True, "task": ref}],
                followups=[{
                    "kind": "research_pending",
                    "task_id": ref,
                    "query": user_text,
                }],
            )
        except AttributeError:
            return SupervisorResult(
                intent="research",
                spoken="Researcher is configured but the start hook isn't wired yet.",
                tool_calls=[{"adapter": "research", "ok": False}],
            )
    except Exception as e:
        logger.warning("supervisor_research_adapter_failed", error=str(e))
        return SupervisorResult(
            intent="research",
            spoken="The researcher is offline right now.",
            tool_calls=[{"adapter": "research", "ok": False, "error": str(e)}],
            error=str(e),
        )


async def _bookkeeper_adapter(user_text: str, ctx: dict[str, Any]) -> SupervisorResult:
    try:
        from app.services.bookkeeper_service import get_bookkeeper_service
        svc = get_bookkeeper_service()
        ans = await svc.answer_voice_question(user_text)
        return SupervisorResult(
            intent="bookkeeper",
            spoken=str(ans)[:500],
            tool_calls=[{"adapter": "bookkeeper", "ok": True}],
        )
    except Exception as e:
        logger.warning("supervisor_bookkeeper_adapter_failed", error=str(e))
        return SupervisorResult(
            intent="bookkeeper",
            spoken="The bookkeeper isn't ready yet — Beancount needs a journal.",
            tool_calls=[{"adapter": "bookkeeper", "ok": False, "error": str(e)}],
            error=str(e),
        )


async def _brief_adapter(user_text: str, ctx: dict[str, Any]) -> SupervisorResult:
    try:
        from app.services.daily_brief_service import get_daily_brief_service
        svc = get_daily_brief_service()
        brief = await svc.compose_today()
        return SupervisorResult(
            intent="daily_brief",
            spoken=brief.spoken_summary[:600] if hasattr(brief, "spoken_summary") else str(brief)[:600],
            tool_calls=[{"adapter": "daily_brief", "ok": True}],
        )
    except Exception as e:
        logger.warning("supervisor_brief_adapter_failed", error=str(e))
        return SupervisorResult(
            intent="daily_brief",
            spoken="Daily brief isn't ready yet.",
            tool_calls=[{"adapter": "daily_brief", "ok": False, "error": str(e)}],
            error=str(e),
        )


# ---------------------------------------------------------------------------
# Classification — keyword-first (zero latency) with optional LLM fallback.
# Intentionally narrow: returns one of the registered intents or "direct".
# ---------------------------------------------------------------------------

# Order matters: more-specific actions (research verb, daily-brief phrases)
# win over broader topical keywords (company nouns) when they overlap. A
# request like "research the best CPAs in Duval" should land on research,
# not company, even though the latter's keyword list includes "duval"/"cpa".
_KEYWORD_INTENTS: list[tuple[str, tuple[str, ...]]] = [
    ("daily_brief", (
        "daily brief", "morning brief", "what should i work on", "overnight report",
    )),
    ("research", ("research ", "look up", "find out", "investigate", "compare")),
    ("email", ("email", "inbox", "mail", "gmail", "message", "messages")),
    ("calendar", ("calendar", "schedule", "agenda", "meeting", "meetings", "appointment")),
    ("bookkeeper", (
        "bookkeeping", "expense", "expenses", "p&l", "p and l", "tax", "taxes",
        "invoice", "balance", "ledger", "journal", "revenue",
    )),
    ("company", ("ada ai", "ada", "company", "business", "llc", "sunbiz", "ein", "duval", "cpa")),
]


def _classify(user_text: str) -> str:
    t = (user_text or "").strip().lower()
    if not t:
        return "direct"
    for intent, keywords in _KEYWORD_INTENTS:
        for kw in keywords:
            if kw in t:
                return intent
    return "direct"


# ---------------------------------------------------------------------------
# Supervisor — orchestrates the graph. LangGraph is wired only when env
# `ZERO_SUPERVISOR_LANGGRAPH=1` AND the package is importable.
# ---------------------------------------------------------------------------

class SupervisorGraph:
    def __init__(self) -> None:
        self._adapters: dict[str, AdapterFn] = {
            "email": _email_adapter,
            "calendar": _calendar_adapter,
            "company": _company_adapter,
            "research": _research_adapter,
            "bookkeeper": _bookkeeper_adapter,
            "daily_brief": _brief_adapter,
        }
        self._lg_app: Any = None
        if USE_LANGGRAPH:
            self._maybe_build_langgraph()

    def _maybe_build_langgraph(self) -> None:
        try:
            from langgraph.graph import StateGraph, END  # type: ignore
        except ImportError:
            logger.info("supervisor_langgraph_not_installed")
            return

        sg = StateGraph(dict)

        async def classify_node(state: dict) -> dict:
            return {**state, "intent": _classify(state.get("user_text", ""))}

        async def dispatch_node(state: dict) -> dict:
            intent = state.get("intent") or "direct"
            adapter = self._adapters.get(intent)
            if adapter is None:
                return {**state, "result": SupervisorResult(
                    intent="direct", spoken="", direct=True,
                ).to_dict()}
            res = await adapter(state.get("user_text", ""), state.get("ctx", {}))
            return {**state, "result": res.to_dict()}

        sg.add_node("classify", classify_node)
        sg.add_node("dispatch", dispatch_node)
        sg.set_entry_point("classify")
        sg.add_edge("classify", "dispatch")
        sg.add_edge("dispatch", END)
        self._lg_app = sg.compile()
        logger.info("supervisor_langgraph_compiled")

    async def handle(
        self,
        user_text: str,
        *,
        persona_id: str = "default",
        ctx: Optional[dict[str, Any]] = None,
    ) -> SupervisorResult:
        ctx = dict(ctx or {})
        ctx.setdefault("persona_id", persona_id)
        ctx.setdefault("ts", datetime.now(timezone.utc).isoformat())

        if self._lg_app is not None:
            try:
                state = await self._lg_app.ainvoke({"user_text": user_text, "ctx": ctx})
                payload = state.get("result") or {}
                return SupervisorResult(
                    intent=payload.get("intent") or "direct",
                    spoken=payload.get("spoken") or "",
                    tool_calls=payload.get("tool_calls") or [],
                    followups=payload.get("followups") or [],
                    direct=bool(payload.get("direct")),
                    error=payload.get("error"),
                )
            except Exception as e:
                logger.warning("supervisor_langgraph_failed", error=str(e))

        intent = _classify(user_text)
        if intent == "direct":
            return SupervisorResult(intent="direct", spoken="", direct=True)
        adapter = self._adapters.get(intent)
        if adapter is None:
            return SupervisorResult(intent="direct", spoken="", direct=True)
        return await adapter(user_text, ctx)

    def list_adapters(self) -> list[str]:
        return sorted(self._adapters.keys())


@lru_cache(maxsize=1)
def get_supervisor() -> SupervisorGraph:
    return SupervisorGraph()
