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
import re
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
        from app.models.agent_company import DeepResearchRequest
        svc = get_deep_research_service()
        # DeepResearchService exposes start_research(DeepResearchRequest): it
        # creates the report row, kicks the pipeline off in the background and
        # returns a report handle immediately. The old svc.start(query=...)
        # never existed, so every voice research request hit the swallowed
        # AttributeError and silently did nothing.
        report = await svc.start_research(DeepResearchRequest(query=user_text))
        ref = getattr(report, "id", None) or "queued"
        return SupervisorResult(
            intent="research",
            spoken="I queued a researcher on that. I'll bring back the findings as soon as it's done.",
            tool_calls=[{"adapter": "research", "ok": True, "task": ref}],
            followups=[{
                "kind": "research_pending",
                "task_id": ref,
                "query": user_text,
            }],
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


# _summary_regen_adapter / _face_enroll_adapter / _adhoc_capture_adapter
# (F-75 / F-65 / F-50, voice-triggered meeting adapters) removed — they were
# already unreachable (not registered in _KEYWORD_INTENTS or self._adapters,
# per the 2026-06-20 meeting-concept retirement) and imported from
# app.services.reachy_realtime, which is deleted now that robot/Reachy
# hardware control has moved to a separate app (Zero Studio) and voice chat
# has been dropped from Zero entirely.


async def _system_check_adapter(user_text: str, ctx: dict[str, Any]) -> SupervisorResult:
    """F-45 — voice "Hey Zero, system check / how's everything?".

    Reads the meeting-steward status aggregator and speaks a one-sentence
    summary. Falls back to a generic 'something needs attention' line on
    any failed gate."""
    try:
        from app.routers.meeting_steward_status import meeting_steward_status

        data = await meeting_steward_status()
        issues = data.get("issues") or []
        if not issues:
            companion = data.get("companion") or {}
            approvals = data.get("approvals") or {}
            backlog = data.get("transcript_backlog") or {}
            pending = approvals.get("pending") or 0
            in_flight = backlog.get("total_processing") or 0
            extras = []
            if pending:
                extras.append(f"{pending} pending approval{'s' if pending != 1 else ''}")
            if in_flight:
                extras.append(f"{in_flight} meeting{'s' if in_flight != 1 else ''} transcribing")
            tail = " " + " and ".join(extras) + "." if extras else ""
            # R3 (supervise zero 6a8c5562): this used to append "Companion is in
            # {mode} mode", where mode came from `companion.get("mode") or
            # "ambient"`. The robot companion moved to Zero Studio on 2026-07-11
            # and meeting_steward_status.py:43 now returns {"retired": True}
            # with no "mode" key at all — so the `or "ambient"` default always
            # fired and Zero confidently reported a deleted subsystem as running.
            # This is a live path: system_check is reachable from ordinary text
            # ("system check", "health check", "everything ok").
            spoken = f"All systems nominal.{tail}"
            if not companion.get("retired") and companion.get("mode"):
                spoken = (
                    f"All systems nominal. "
                    f"Companion is in {companion['mode']} mode.{tail}"
                )
        else:
            first = issues[0]
            spoken = (
                f"{len(issues)} issue{'s' if len(issues) != 1 else ''} to look at — "
                f"{first.get('id')}: {first.get('detail', '')[:120]}"
            )
        return SupervisorResult(
            intent="system_check",
            spoken=spoken[:500],
            tool_calls=[{"adapter": "system_check", "ok": not issues, "issue_count": len(issues)}],
        )
    except Exception as e:
        logger.warning("supervisor_system_check_failed", error=str(e))
        return SupervisorResult(
            intent="system_check",
            spoken="I couldn't read the system status right now.",
            tool_calls=[{"adapter": "system_check", "ok": False, "error": str(e)}],
            error=str(e),
        )


async def _meeting_rag_adapter(user_text: str, ctx: dict[str, Any]) -> SupervisorResult:
    """Voice → meeting-transcript RAG.

    Powers questions like "what did Sarah say about the budget last week?" or
    "what did we agree to in the standup yesterday?". Routes through
    meeting_rag_service.query() which ranks chunks across past transcripts
    and returns a synthesized answer + sourced excerpts.
    """
    try:
        from app.services.meeting_rag_service import get_meeting_rag_service
        from app.infrastructure.database import get_session

        svc = get_meeting_rag_service()
        async with get_session() as db:
            result = await svc.query(question=user_text, db=db, meeting_id=None, top_k=6)
        answer = (result.get("answer") or "").strip()
        sources = result.get("sources") or []
        if not answer:
            answer = (
                "I searched recent meetings but didn't find anything that matches."
                if not sources
                else "I found some context but couldn't summarise it just yet."
            )
        return SupervisorResult(
            intent="meeting_rag",
            spoken=answer[:600],
            tool_calls=[{
                "adapter": "meeting_rag",
                "ok": True,
                "sources": [
                    {
                        "meeting_id": s.get("meeting_id"),
                        "meeting_title": s.get("meeting_title"),
                        "speaker": s.get("speaker"),
                    }
                    for s in sources[:5]
                ],
            }],
        )
    except Exception as e:
        logger.warning("supervisor_meeting_rag_adapter_failed", error=str(e))
        return SupervisorResult(
            intent="meeting_rag",
            spoken="I couldn't search the meeting archive right now.",
            tool_calls=[{"adapter": "meeting_rag", "ok": False, "error": str(e)}],
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
    # Meeting voice intents (meeting_capture / face_enroll / summary_regen /
    # meeting_rag) removed 2026-06-20 — meetings concept retired from product.
    # F-45: system_check wins early so "how's everything" doesn't fall
    # into the daily-brief / calendar buckets.
    ("system_check", (
        "system check", "system status", "how's everything", "how are things",
        "any alarms", "any issues", "everything ok", "everything okay",
        "status report", "health check",
    )),
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


# R2 (supervise zero 6a8c5562): matching was `if kw in t` — an unanchored
# substring test — over a keyword list containing tokens as short as "ada",
# "ein", "cpa", and "tax". So "am I being productive?" matched "ein" and routed
# to the company adapter, which answered with an ADA AI LLC brief; "Adam"
# matched "ada"; "syntax" matched "tax"; "work-life balance" matched "balance".
# The turn isn't dropped, it's answered by the wrong agent — indistinguishable
# from a drop on the user's side. Word boundaries fix it without touching the
# keyword list, and \b handles the multi-word phrases ("daily brief", "p and l")
# unchanged. Compiled once at import; the list is static.
@lru_cache(maxsize=1)
def _compiled_keyword_intents() -> tuple[tuple[str, tuple[re.Pattern, ...]], ...]:
    return tuple(
        (intent, tuple(re.compile(rf"\b{re.escape(kw.strip())}\b") for kw in keywords))
        for intent, keywords in _KEYWORD_INTENTS
    )


def _classify(user_text: str) -> str:
    t = (user_text or "").strip().lower()
    if not t:
        return "direct"
    for intent, patterns in _compiled_keyword_intents():
        for pat in patterns:
            if pat.search(t):
                return intent
    return "direct"


async def _classify_llm(user_text: str, intents: list[str]) -> str:
    """Enhancement-13: LLM fallback classifier.

    Used ONLY when the keyword pass returns "direct", so the common path stays
    zero-latency. Returns one of ``intents`` or "direct". Never raises — any
    failure (LLM down, garbage output) degrades to "direct".
    """
    text = (user_text or "").strip()
    if not text or not intents:
        return "direct"
    try:
        from app.infrastructure.unified_llm_client import get_unified_llm_client
        llm = get_unified_llm_client()
        options = ", ".join(list(intents) + ["direct"])
        prompt = (
            "Classify the user's request into exactly one intent label.\n"
            f"Allowed labels: {options}.\n"
            "Reply with ONLY the single label, nothing else.\n\n"
            f"Request: {text}"
        )
        raw = await llm.chat(
            prompt=prompt,
            task_type="classification",
            temperature=0.0,
            max_tokens=12,
        )
        guess = (raw or "").strip().lower()
        guess = guess.split()[0] if guess.split() else ""
        guess = "".join(ch for ch in guess if ch.isalnum() or ch == "_")
        return guess if guess in intents else "direct"
    except Exception as e:  # noqa: BLE001
        logger.warning("supervisor_llm_classify_failed", error=str(e))
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
            "system_check": _system_check_adapter,
            # Meeting adapters (meeting_rag / meeting_capture / face_enroll /
            # summary_regen) removed 2026-06-20 — meetings concept retired.
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
            intent = _classify(state.get("user_text", ""))
            if intent == "direct":
                # Enhancement-13 parity (Fix-96): the keyword pass missed, so
                # try the LLM fallback before degrading to an unrouted direct
                # response. The non-LangGraph handle() path already does this;
                # the LangGraph branch previously skipped it entirely, so any
                # intent the keywords missed died as "direct" with no rescue.
                intent = await _classify_llm(
                    state.get("user_text", ""), list(self._adapters.keys())
                )
            return {**state, "intent": intent}

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
            # Enhancement-13: keyword pass missed — try the LLM fallback before
            # giving up to an unrouted direct response (e.g. "show me what's on
            # for tomorrow" has no calendar keyword). Degrades to direct on error.
            intent = await _classify_llm(user_text, list(self._adapters.keys()))
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
