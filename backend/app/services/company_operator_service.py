"""Zero Company Operator service.

This is the supervised 24/7 company-manager loop for ADA AI LLC.
It is deliberately conservative: it can organize internal state, create
internal tasks, prepare packets, and queue approvals, but it does not execute
external legal, financial, account, client, or public actions.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any, Optional

import httpx
import structlog
from sqlalchemy import func, or_, select, update

from app.db.models import (
    AgentApprovalModel,
    AgentRoleModel,
    AgentTaskModel,
    CompanyAgentQuestionModel,
    CompanyOperatorRunModel,
    ExperimentModel,
    PromptRunModel,
    SchedulerAuditLogModel,
    ServiceConfigModel,
)
from app.infrastructure.database import get_session
from app.models.agent_company import AgentTaskCreate, AgentTaskType
from app.models.brain import PromptRunCreate
from app.models.task import (
    Task,
    TaskCategory,
    TaskCreate,
    TaskPriority,
    TaskSource,
    TaskStatus,
    TaskUpdate,
)
from app.services.agent_company_service import COMPANY_AGENT_PROMPT_POLICY, get_agent_company_service
from app.services.approval_queue_service import get_approval_queue
from app.services.company_context_service import get_company_context_service
from app.services.company_dashboard_review_service import get_company_dashboard_review_service
from app.services.company_work_item_service import get_company_work_item_service
from app.services.prompt_evolution_service import get_prompt_evolution_service
from app.services.task_service import get_task_service

logger = structlog.get_logger(__name__)


COMPANY_PROJECT_ID = "company"
CONFIG_KEY = "company_operator"

DEFAULT_CONFIG: dict[str, Any] = {
    "paused": False,
    "overnight_enabled": True,
    "agent_work_enabled": True,
    "agent_work_interval_minutes": 15,
    "max_work_items_per_tick": 8,
    "max_approvals_per_tick": 6,
    "max_agent_tasks_per_tick": 6,
    "max_agent_executions_per_tick": 5,
    "max_questions_per_tick": 10,
    "agent_task_lease_minutes": 20,
    "autonomy": "approval_staged",
    "company_facts": {
        "legal_name": "ADA AI LLC",
        "public_brand": "ADA AI",
        "llc_created": True,
        "llc_created_source": "Adam confirmed ADA AI LLC was created in Company OS.",
    },
}

LOW_VALUE_QUESTION_RE = re.compile(
    r"\b("
    r"what confirmation or source should zero attach|"
    r"what source should zero attach|"
    r"what confirmation should zero attach|"
    r"please confirm this company step is complete"
    r")\b",
    re.IGNORECASE,
)

HIGH_RISK_RE = re.compile(
    r"\b("
    r"verify name on sunbiz|file florida llc|articles of organization|apply for ein|get ein|"
    r"choose registered agent|sign operating agreement|sign ip assignment|"
    r"open .*bank account|open .*credit card|business credit card|get duval local business tax receipt|"
    r"schedule cpa|schedule attorney|hire cpa|hire attorney|set up business email|"
    r"configure dns|purchase domain|domain purchase|set up password vault|create receipt inbox|"
    r"publish|send .*proposal|client communication|public|linkedin|stripe account|"
    r"tax election|trademark filing|disclaimer"
    r")\b",
    re.IGNORECASE,
)

FORMATION_RE = re.compile(
    r"\b("
    r"formation|llc|sunbiz|ein|registered agent|operating agreement|"
    r"ip assignment|bank|credit card|duval|lbtr|cpa|attorney|insurance"
    r")\b",
    re.IGNORECASE,
)

COMPANY_APPROVAL_TOOL = "company_operator_company_gate"

SUBAGENT_ROLES: tuple[dict[str, Any], ...] = (
    {
        "id": "ceo",
        "name": "CEO / Chief-of-Staff Agent",
        "capabilities": ["routing", "planning", "reporting", "approval_triage"],
        "autonomy": "write_local",
    },
    {
        "id": "finance_cpa",
        "name": "Finance / CPA Ops Agent",
        "capabilities": ["bookkeeping_prep", "receipt_review", "tax_calendar", "cpa_packet"],
        "autonomy": "write_local",
    },
    {
        "id": "legal_compliance",
        "name": "Legal / Compliance Ops Agent",
        "capabilities": ["llc_checklist", "doc_inventory", "attorney_packet", "approval_policy"],
        "autonomy": "write_local",
    },
    {
        "id": "procurement_asset",
        "name": "Procurement / Asset Agent",
        "capabilities": ["subscriptions", "hardware", "licenses", "renewals", "warranties"],
        "autonomy": "write_local",
    },
    {
        "id": "consulting_revenue",
        "name": "Consulting Revenue Agent",
        "capabilities": ["icp", "offers", "crm_followup_drafts", "proposals"],
        "autonomy": "write_local",
    },
    {
        "id": "delivery",
        "name": "Delivery Agent",
        "capabilities": ["client_onboarding", "meeting_notes", "deliverables", "checklists"],
        "autonomy": "write_local",
    },
    {
        "id": "product",
        "name": "Product Agent",
        "capabilities": ["strategy", "specs", "roadmap", "release_notes"],
        "autonomy": "write_local",
    },
    {
        "id": "engineering",
        "name": "Engineering Agent",
        "capabilities": ["architecture", "implementation", "tests", "deployment_readiness"],
        "autonomy": "write_local",
    },
    {
        "id": "llm_ops",
        "name": "LLM Ops Agent",
        "capabilities": ["models", "costs", "routing", "evals", "prompt_experiments"],
        "autonomy": "write_local",
    },
    {
        "id": "knowledge_second_brain",
        "name": "Knowledge / Second-Brain Agent",
        "capabilities": ["vault_summaries", "decisions", "backlinks", "weekly_review"],
        "autonomy": "write_local",
    },
    {
        "id": "marketing_content",
        "name": "Marketing / Content Agent",
        "capabilities": ["website_plan", "case_studies", "linkedin_drafts", "blog_drafts"],
        "autonomy": "write_local",
    },
    {
        "id": "robotics_lab",
        "name": "Robotics / 3D Lab Agent",
        "capabilities": ["printer_inventory", "materials", "print_jobs", "maintenance", "liability_checklist"],
        "autonomy": "write_local",
    },
    {
        "id": "security_risk",
        "name": "Security / Risk Agent",
        "capabilities": ["secrets", "access_reviews", "owasp", "nist", "incident_log"],
        "autonomy": "write_local",
    },
)

FORMATION_AGENT_TASKS: tuple[dict[str, str], ...] = (
    {
        "title": "Prepare LLC filing approval packet",
        "assigned_role": "legal_compliance",
        "description": "Prepare a checklist for Sunbiz name check, registered agent choice, Articles of Organization, operating agreement, and IP assignment. Do not file anything.",
    },
    {
        "title": "Prepare CPA readiness packet",
        "assigned_role": "finance_cpa",
        "description": "Summarize first-year bookkeeping, home office, subscriptions, hardware assets, tax calendar, and CPA questions. Do not make tax elections.",
    },
    {
        "title": "Prepare banking and procurement setup checklist",
        "assigned_role": "procurement_asset",
        "description": "List bank/card/account setup steps, evidence to retain, and subscriptions/assets to migrate after approval. Do not open accounts or buy anything.",
    },
    {
        "title": "Prepare consulting offer launch checklist",
        "assigned_role": "consulting_revenue",
        "description": "Draft internal checklist for ICP, service packages, discovery questions, proposal/SOW templates, and website update approvals.",
    },
    {
        "title": "Prepare company docs and decision summary",
        "assigned_role": "knowledge_second_brain",
        "description": "Summarize the company docs, decision log, second-brain mirror convention, and current formation next actions.",
    },
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _dt(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def _compact(text: Any, *, limit: int = 220) -> str:
    out = str(text or "").replace("\n", " ").strip()
    return out if len(out) <= limit else out[: limit - 1].rstrip() + "..."


def _normalize_question_text(text: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()
    return re.sub(r"\s+", " ", normalized)


def _agent_task_is_running(task: AgentTaskModel, *, now: Optional[datetime] = None) -> bool:
    if task.status != "in_progress":
        return False
    if not task.lease_expires_at:
        return False
    return task.lease_expires_at > (now or _now())


def _task_text(task: Task) -> str:
    return f"{task.title} {task.domain or ''}"


def _is_high_risk_task(task: Task) -> bool:
    return bool(HIGH_RISK_RE.search(_task_text(task)))


def _is_formation_task(task: Task) -> bool:
    return bool(FORMATION_RE.search(_task_text(task)))


def _approval_tier_for_task(task: Task) -> str:
    return "financial" if re.search(
        r"\b(bank|card|purchase|subscription|cpa|attorney|registered agent|receipt|bookkeeping|tax)\b",
        _task_text(task),
        re.I,
    ) else "write_external"


def _approval_summary_for_task(task: Task) -> str:
    return f"Approval needed before completing company launch task: {task.title}"


def _approval_arguments_for_task(task: Task) -> dict[str, Any]:
    return {
        "task_id": task.id,
        "title": task.title,
        "project_id": COMPANY_PROJECT_ID,
        "company": "ADA AI LLC",
        "formation": _is_formation_task(task),
        "adam_action": f"Review and either perform or explicitly approve the external step for: {task.title}",
        "safe_zero_work": "Zero may draft, summarize, prepare checklists, collect evidence, and update internal task history.",
        "guardrail": "Adam must perform or approve filings, purchases, account changes, legal/tax decisions, and professional engagements.",
    }


def _serialize_task(task: Task) -> dict[str, Any]:
    status = getattr(task.status, "value", task.status)
    priority = getattr(task.priority, "value", task.priority)
    category = getattr(task.category, "value", task.category)
    source = getattr(task.source, "value", task.source)
    return {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "status": status,
        "priority": priority,
        "category": category,
        "source": source,
        "project_id": task.project_id,
        "sprint_id": task.sprint_id,
        "blocked_reason": task.blocked_reason,
        "domain": task.domain,
        "owner_agent": task.owner_agent,
        "due_at": _dt(task.due_at),
        "scheduled_for": _dt(task.scheduled_for),
        "risk_level": task.risk_level,
        "approval_state": task.approval_state,
        "approval_id": task.approval_id,
        "tags": task.tags or [],
        "links": task.links or [],
        "sort_order": task.sort_order,
        "estimate_points": task.estimate_points,
        "parent_task_id": task.parent_task_id,
        "created_at": _dt(task.created_at),
        "updated_at": _dt(task.updated_at),
        "completed_at": _dt(task.completed_at),
        "risk": task.risk_level or ("high" if _is_high_risk_task(task) else "low"),
        "formation": _is_formation_task(task),
    }


def _serialize_agent_task(row: AgentTaskModel) -> dict[str, Any]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "title": row.title,
        "description": row.description,
        "task_type": row.task_type,
        "assigned_role": row.assigned_role,
        "status": row.status,
        "priority": row.priority,
        "context": row.context or {},
        "result": row.result,
        "parent_task_id": row.parent_task_id,
        "cost_usd": row.cost_usd,
        "error": row.error,
        "lease_id": row.lease_id,
        "lease_expires_at": _dt(row.lease_expires_at),
        "attempt_count": row.attempt_count or 0,
        "last_heartbeat_at": _dt(row.last_heartbeat_at),
        "created_at": _dt(row.created_at),
        "started_at": _dt(row.started_at),
        "completed_at": _dt(row.completed_at),
    }


def _serialize_question(row: CompanyAgentQuestionModel) -> dict[str, Any]:
    context = row.context or {}
    return {
        "id": row.id,
        "question": row.question,
        "context": context,
        "answer_type": row.answer_type,
        "options": row.options or [],
        "priority": row.priority,
        "status": row.status,
        "asked_by_agent": row.asked_by_agent,
        "task_id": row.task_id,
        "agent_task_id": row.agent_task_id,
        "operator_run_id": row.operator_run_id,
        "source": row.source,
        "answer": row.answer,
        "answered_by": row.answered_by,
        "created_at": _dt(row.created_at),
        "answered_at": _dt(row.answered_at),
        "dismissed_at": _dt(row.dismissed_at),
        "updated_at": _dt(row.updated_at),
        "recommended_default": context.get("recommended_default"),
        "why_needed": context.get("why_needed"),
        "blocks_progress": context.get("blocks_progress"),
        "decision_type": context.get("decision_type"),
    }


def _serialize_approval(row: AgentApprovalModel) -> dict[str, Any]:
    return {
        "id": row.id,
        "tool_name": row.tool_name,
        "tier": row.tier,
        "summary": row.summary,
        "arguments": row.arguments or {},
        "requested_by": row.requested_by,
        "status": row.status,
        "decision_reason": row.decision_reason,
        "decided_by": row.decided_by,
        "created_at": _dt(row.created_at),
        "decided_at": _dt(row.decided_at),
        "executed_at": _dt(row.executed_at),
        "expires_at": _dt(row.expires_at),
    }


def _serialize_run(row: CompanyOperatorRunModel) -> dict[str, Any]:
    return {
        "id": row.id,
        "run_type": row.run_type,
        "requested_by": row.requested_by,
        "status": row.status,
        "summary": row.summary,
        "report": row.report or {},
        "actions": row.actions or [],
        "errors": row.errors or [],
        "started_at": _dt(row.started_at),
        "completed_at": _dt(row.completed_at),
        "created_at": _dt(row.created_at),
    }


class CompanyOperatorService:
    """Supervised company operator for Zero."""

    async def get_config(self) -> dict[str, Any]:
        async with get_session() as session:
            row = await session.get(ServiceConfigModel, CONFIG_KEY)
            if row is None:
                return dict(DEFAULT_CONFIG)
            return {**DEFAULT_CONFIG, **(row.config or {})}

    async def update_config(self, updates: dict[str, Any]) -> dict[str, Any]:
        allowed = set(DEFAULT_CONFIG)
        cleaned = {k: v for k, v in updates.items() if k in allowed}
        async with get_session() as session:
            row = await session.get(ServiceConfigModel, CONFIG_KEY)
            if row is None:
                row = ServiceConfigModel(service_name=CONFIG_KEY, config={**DEFAULT_CONFIG, **cleaned})
                session.add(row)
            else:
                row.config = {**DEFAULT_CONFIG, **(row.config or {}), **cleaned}
                row.updated_at = _now()
            await session.flush()
            return dict(row.config)

    async def pause(self) -> dict[str, Any]:
        return await self.update_config({"paused": True})

    async def resume(self) -> dict[str, Any]:
        return await self.update_config({"paused": False})

    async def status(self) -> dict[str, Any]:
        config, latest, overnight, today = await self._basic_operator_state()
        snapshot = await self._snapshot(include_legion=False)
        dashboard_review = await get_company_dashboard_review_service().summary()
        agent_work_runs = await self.runs(run_type="agent_work", limit=1)
        open_questions = await self.questions(status="open", limit=10)
        return {
            "operator": "Zero Company Operator",
            "company": "ADA AI LLC",
            "active": not bool(config.get("paused")),
            "autonomy": config.get("autonomy", "internal_work"),
            "paused": bool(config.get("paused")),
            "overnight_enabled": bool(config.get("overnight_enabled")),
            "agent_work_enabled": bool(config.get("agent_work_enabled")),
            "agent_work_interval_minutes": int(config.get("agent_work_interval_minutes") or 15),
            "heartbeat": latest,
            "latest_agent_work": agent_work_runs[0] if agent_work_runs else None,
            "latest_overnight": overnight,
            "today": today,
            "counts": snapshot["counts"],
            "formation": snapshot["formation"],
            "approvals": snapshot["approvals"][:10],
            "questions": open_questions,
            "blocked_tasks": snapshot["blocked_tasks"][:10],
            "subagents": snapshot["subagents"],
            "prompt_lab": snapshot["prompt_lab"],
            "dashboard_review": dashboard_review.model_dump(mode="json"),
        }

    async def runs(self, *, run_type: Optional[str] = None, limit: int = 30) -> list[dict[str, Any]]:
        async with get_session() as session:
            q = select(CompanyOperatorRunModel).order_by(CompanyOperatorRunModel.created_at.desc()).limit(limit)
            if run_type:
                q = q.where(CompanyOperatorRunModel.run_type == run_type)
            result = await session.execute(q)
            return [_serialize_run(r) for r in result.scalars().all()]

    async def latest_report(self, *, report_type: Optional[str] = None) -> dict[str, Any]:
        run_types = {
            "overnight": ("overnight",),
            "morning": ("morning_brief",),
            "evening": ("evening_report",),
            "weekly": ("weekly_review",),
        }.get(str(report_type or "").lower(), None)
        async with get_session() as session:
            q = select(CompanyOperatorRunModel).order_by(CompanyOperatorRunModel.created_at.desc()).limit(1)
            if run_types:
                q = q.where(CompanyOperatorRunModel.run_type.in_(run_types))
            result = await session.execute(q)
            row = result.scalars().first()
        if row:
            return _serialize_run(row)
        snapshot = await self._snapshot(include_legion=True)
        return {
            "id": None,
            "run_type": report_type or "snapshot",
            "status": "not_run_yet",
            "summary": self._summary_from_snapshot(snapshot),
            "report": self._report_from_snapshot(report_type or "snapshot", snapshot, []),
            "actions": [],
            "errors": [],
        }

    async def overnight(self) -> dict[str, Any]:
        latest = await self.latest_report(report_type="overnight")
        recent = await self.runs(limit=10)
        recent_overnight = [r for r in recent if r["run_type"] == "overnight"][:5]
        return {"latest": latest, "recent": recent_overnight}

    async def today(self) -> dict[str, Any]:
        snapshot = await self._snapshot(include_legion=False)
        top_tasks = snapshot["next_tasks"][:5]
        return {
            "question": "What should Adam work on today?",
            "answer": self._today_answer(snapshot),
            "next_tasks": top_tasks,
            "approvals": snapshot["approvals"][:5],
            "blocked_tasks": snapshot["blocked_tasks"][:5],
            "formation": snapshot["formation"],
        }

    async def create_company_task(self, data: TaskCreate) -> Task:
        return await get_company_work_item_service().create_work_item(data, actor="zero-company-operator")

    async def update_company_task(self, task_id: str, updates: TaskUpdate) -> Optional[Task]:
        return await get_company_work_item_service().update_work_item(task_id, updates, actor="zero-company-operator")

    async def queue_approval(
        self,
        *,
        summary: str,
        tool_name: str = "company_operator_manual_approval",
        tier: str = "write_external",
        arguments: Optional[dict[str, Any]] = None,
        requested_by: str = "zero-company-operator",
    ) -> dict[str, Any]:
        row = await get_approval_queue().request(
            tool_name=tool_name,
            tier=tier,
            summary=summary,
            arguments=arguments or {},
            requested_by=requested_by,
        )
        return _serialize_approval(row)

    async def questions(
        self,
        *,
        status: Optional[str] = "open",
        task_id: Optional[str] = None,
        agent_task_id: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        async with get_session() as session:
            q = select(CompanyAgentQuestionModel).order_by(
                CompanyAgentQuestionModel.created_at.desc()
            ).limit(limit)
            if status:
                q = q.where(CompanyAgentQuestionModel.status == status)
            if task_id:
                q = q.where(CompanyAgentQuestionModel.task_id == task_id)
            if agent_task_id:
                q = q.where(CompanyAgentQuestionModel.agent_task_id == agent_task_id)
            result = await session.execute(q)
            return [_serialize_question(row) for row in result.scalars().all()]

    async def triage_questions(
        self,
        *,
        requested_by: str = "dashboard",
        limit: int = 200,
        max_open: int = 25,
    ) -> dict[str, Any]:
        """Consolidate noisy agent questions without answering Adam-only decisions.

        This is intentionally conservative: it only dismisses exact/near-exact
        duplicates and generic fallback questions that do not block progress.
        The remaining questions get triage metadata so the inbox can surface the
        few decisions that are actually useful.
        """
        now = _now()
        limit = max(1, min(int(limit or 200), 500))
        max_open = max(5, min(int(max_open or 25), 100))
        dismissed: list[dict[str, Any]] = []
        highlighted: list[dict[str, Any]] = []
        seen: dict[str, CompanyAgentQuestionModel] = {}

        async with get_session() as session:
            rows = (
                await session.execute(
                    select(CompanyAgentQuestionModel)
                    .where(CompanyAgentQuestionModel.status == "open")
                    .order_by(CompanyAgentQuestionModel.created_at.asc())
                    .limit(limit)
                )
            ).scalars().all()
            priority_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
            rows = sorted(
                rows,
                key=lambda item: (
                    priority_rank.get(str(item.priority or "").lower(), 4),
                    item.created_at or now,
                ),
            )

            for row in rows:
                normalized = _normalize_question_text(row.question)
                reason: Optional[str] = None
                canonical_id: Optional[str] = None
                if LOW_VALUE_QUESTION_RE.search(row.question):
                    reason = "generic_nonblocking_fallback_question"
                elif normalized in seen:
                    reason = "duplicate_question"
                    canonical_id = seen[normalized].id
                elif len(highlighted) >= max_open:
                    reason = "deferred_by_focus_queue_budget"
                else:
                    seen[normalized] = row

                context = dict(row.context or {})
                if reason:
                    context["triage"] = {
                        "status": "dismissed",
                        "reason": reason,
                        "canonical_question_id": canonical_id,
                        "focus_queue_limit": max_open,
                        "triaged_by": requested_by,
                        "triaged_at": now.isoformat(),
                    }
                    row.context = context
                    row.status = "dismissed"
                    row.answer = (
                        "Auto-triaged by Zero: duplicate, generic, or outside the current Adam focus queue. "
                        "Agents must continue with safe internal defaults and re-ask only if the decision blocks progress "
                        "under the stricter question schema."
                    )
                    row.answered_by = requested_by
                    row.dismissed_at = now
                    row.updated_at = now
                    dismissed.append(_serialize_question(row))
                    continue

                blocks_progress = bool(context.get("blocks_progress"))
                if row.priority in {"critical", "high"}:
                    blocks_progress = True
                context["triage"] = {
                    "status": "highlighted",
                    "rank_basis": "priority, blocking status, and creation time",
                    "triaged_by": requested_by,
                    "triaged_at": now.isoformat(),
                }
                context.setdefault("blocks_progress", blocks_progress)
                if not context.get("recommended_default"):
                    context["recommended_default"] = "Use the safest internal default, keep external action approval-gated, and continue drafting around the uncertainty."
                row.context = context
                row.updated_at = now
                highlighted.append(_serialize_question(row))

            await session.flush()

        for item in dismissed[:25]:
            if item.get("task_id"):
                await get_company_work_item_service().record_event(
                    str(item["task_id"]),
                    "question_triaged",
                    actor=requested_by,
                    summary=f"Auto-triaged agent question: {_compact(item['question'], limit=140)}",
                    after={
                        "question_id": item["id"],
                        "status": item["status"],
                    "triage": (item.get("context") or {}).get("triage"),
                    },
                )

        return {
            "requested_by": requested_by,
            "reviewed": len(highlighted) + len(dismissed),
            "highlighted": len(highlighted),
            "dismissed": len(dismissed),
            "max_open": max_open,
            "top_questions": highlighted[:10],
            "dismissed_questions": dismissed[:10],
            "summary": (
                f"Question triage reviewed {len(highlighted) + len(dismissed)} open questions, "
                f"kept {len(highlighted)} visible Adam decisions, and dismissed/deferred {len(dismissed)} noisy or lower-priority asks."
            ),
        }

    async def answer_question(
        self,
        question_id: str,
        *,
        answer: str,
        answered_by: str = "dashboard",
    ) -> Optional[dict[str, Any]]:
        now = _now()
        async with get_session() as session:
            row = await session.get(CompanyAgentQuestionModel, question_id)
            if not row:
                return None
            row.status = "answered"
            row.answer = answer
            row.answered_by = answered_by
            row.answered_at = now
            row.updated_at = now
            if row.agent_task_id:
                agent_task = await session.get(AgentTaskModel, row.agent_task_id)
                if agent_task:
                    context = dict(agent_task.context or {})
                    answers = list(context.get("adam_answers") or [])
                    answers.append({"question_id": row.id, "answer": answer, "answered_by": answered_by, "answered_at": now.isoformat()})
                    context["adam_answers"] = answers
                    agent_task.context = context
                    if agent_task.status in {"failed", "needs_review"}:
                        agent_task.status = "pending"
                        agent_task.error = None
                        agent_task.completed_at = None
            await session.flush()
            serialized = _serialize_question(row)
        if serialized.get("task_id"):
            await get_company_work_item_service().record_event(
                str(serialized["task_id"]),
                "question_answered",
                actor=answered_by,
                summary=f"Adam answered agent question: {_compact(serialized['question'], limit=140)}",
                after={"question_id": question_id, "answer": answer},
            )
        return serialized

    async def dismiss_question(
        self,
        question_id: str,
        *,
        answered_by: str = "dashboard",
    ) -> Optional[dict[str, Any]]:
        now = _now()
        async with get_session() as session:
            row = await session.get(CompanyAgentQuestionModel, question_id)
            if not row:
                return None
            row.status = "dismissed"
            row.answered_by = answered_by
            row.dismissed_at = now
            row.updated_at = now
            await session.flush()
            serialized = _serialize_question(row)
        if serialized.get("task_id"):
            await get_company_work_item_service().record_event(
                str(serialized["task_id"]),
                "question_dismissed",
                actor=answered_by,
                summary=f"Dismissed agent question: {_compact(serialized['question'], limit=140)}",
                after={"question_id": question_id},
            )
        return serialized

    async def assign_task_to_subagent(
        self,
        *,
        task_id: str,
        role_id: str,
        requested_by: str = "user",
    ) -> dict[str, Any]:
        task = await get_task_service().get_task(task_id)
        if not task:
            raise ValueError(f"task {task_id} not found")
        await self._ensure_company_roles()
        req = AgentTaskCreate(
            title=f"{role_id}: {task.title}",
            description=task.description or task.title,
            task_type=AgentTaskType.PLANNING,
            assigned_role=role_id,
            priority=2 if task.priority in (TaskPriority.CRITICAL, TaskPriority.HIGH) else 3,
            project_id=COMPANY_PROJECT_ID,
            context={
                "zero_task_id": task.id,
                "requested_by": requested_by,
                "autonomy": "approval_staged",
                "external_actions_allowed": False,
                "external_approval_required": _is_high_risk_task(task),
                "approval_required": _is_high_risk_task(task),
                "guardrail": "Prepare the internal packet and exact Adam action. Do not execute external/legal/financial/client/public/account work.",
            },
        )
        agent_task = await get_agent_company_service().create_task(req)
        return agent_task.model_dump()

    async def run_tick(
        self,
        *,
        run_type: str = "manual",
        requested_by: str = "user",
        force: bool = False,
        target_agent_id: Optional[str] = None,
    ) -> dict[str, Any]:
        run_id = f"cor-{uuid.uuid4().hex[:12]}"
        started = _now()
        actions: list[dict[str, Any]] = []
        errors: list[str] = []
        status = "completed"

        try:
            config = await self.get_config()
            if config.get("paused") and not force:
                status = "skipped"
                snapshot = await self._snapshot(include_legion=False)
                report = self._report_from_snapshot(run_type, snapshot, actions)
                summary = "Zero Company Operator is paused. No work was performed."
                return await self._save_run(
                    run_id=run_id,
                    run_type=run_type,
                    requested_by=requested_by,
                    status=status,
                    summary=summary,
                    report=report,
                    actions=actions,
                    errors=errors,
                    started_at=started,
                )

            work_enabled = run_type in {"manual", "overnight", "formation", "dashboard_review", "agent_work"}
            await self._ensure_company_roles(actions=actions if work_enabled else None)

            if run_type == "dashboard_review":
                actions.extend(await self._recover_stale_agent_tasks(config, operator_run_id=run_id))
                review_result = await get_company_dashboard_review_service().run_dashboard_review(
                    operator_run_id=run_id,
                    reviewed_by=requested_by or "zero-company-operator",
                    auto_apply=True,
                )
                actions.extend(review_result.get("actions", []))
                actions.extend(await self._reconcile_company_facts(config, requested_by=requested_by))
                actions.extend(await self._queue_company_approvals(config))
                actions.append(
                    {
                        "type": "agent_execution_deferred",
                        "reason": (
                            "dashboard_review grades, enriches, links, and logs company work; "
                            "safe packet execution is handled by manual, formation, or overnight operator runs."
                        ),
                    }
                )
            elif work_enabled:
                actions.extend(await self._recover_stale_agent_tasks(config, operator_run_id=run_id))
                actions.extend(await self._reconcile_company_facts(config, requested_by=requested_by))
                if run_type in {"manual", "overnight", "formation"}:
                    actions.extend(await self._triage_formation_tasks(config))
                    actions.extend(await self._ensure_formation_subagent_tasks(config))
                actions.extend(await self._queue_company_approvals(config))
                if run_type in {"agent_work", "manual", "overnight"}:
                    triage = await self.triage_questions(
                        requested_by="zero-company-operator",
                        limit=int(config.get("max_questions_per_tick") or 10) * 20,
                        max_open=int(config.get("max_open_questions") or 25),
                    )
                    if triage.get("dismissed") or triage.get("highlighted"):
                        actions.append({"type": "question_triage", **triage})
                if run_type != "monitor":
                    if target_agent_id:
                        actions.extend(
                            await self._execute_safe_agent_tasks(
                                config,
                                operator_run_id=run_id,
                                target_agent_id=target_agent_id,
                            )
                        )
                    else:
                        actions.extend(await self._execute_safe_agent_tasks(config, operator_run_id=run_id))

            snapshot = await self._snapshot(include_legion=run_type not in {"dashboard_review", "agent_work"})
            report = self._report_from_snapshot(run_type, snapshot, actions)
            summary = self._summary_from_snapshot(snapshot)
            if run_type == "dashboard_review":
                report["prompt_run_id"] = None
                report["prompt_recording"] = "skipped_for_fast_dashboard_review"
            else:
                prompt_run_id = await self._record_operator_prompt_run(run_id, run_type, report, summary)
                report["prompt_run_id"] = prompt_run_id
        except Exception as e:  # noqa: BLE001
            logger.exception("company_operator_tick_failed", run_type=run_type)
            status = "failed"
            errors.append(f"{type(e).__name__}: {e}")
            snapshot = await self._snapshot(include_legion=False, tolerate_errors=True)
            report = self._report_from_snapshot(run_type, snapshot, actions)
            summary = "Zero Company Operator failed before completing its report."

        return await self._save_run(
            run_id=run_id,
            run_type=run_type,
            requested_by=requested_by,
            status=status,
            summary=summary,
            report=report,
            actions=actions,
            errors=errors,
            started_at=started,
        )

    async def generate_report(self, *, report_type: str = "manual", requested_by: str = "user") -> dict[str, Any]:
        return await self.run_tick(run_type=report_type, requested_by=requested_by, force=True)

    async def run_prompt_eval_bridge(self, *, limit: int = 20) -> dict[str, Any]:
        run_id = f"cor-{uuid.uuid4().hex[:12]}"
        started = _now()
        actions: list[dict[str, Any]] = []
        errors: list[str] = []
        graded = 0
        skipped = 0

        try:
            from app.services.prompt_grader_service import get_prompt_grader_service

            grader = get_prompt_grader_service()
            prompt_svc = get_prompt_evolution_service()
            actions.extend(await self._ensure_company_prompt_variants())
            async with get_session() as session:
                result = await session.execute(
                    select(PromptRunModel)
                    .where(PromptRunModel.source.in_(["company_operator", "company_subagent"]))
                    .where(PromptRunModel.success.is_(True))
                    .where(PromptRunModel.graded_at.is_(None))
                    .where(PromptRunModel.response_text.isnot(None))
                    .order_by(PromptRunModel.created_at.asc())
                    .limit(limit)
                )
                pending = [prompt_svc._run_to_pydantic(r) for r in result.scalars().all()]

            for run in pending:
                grade = await grader.grade_run(run)
                if grade is None:
                    skipped += 1
                    continue
                if await prompt_svc.apply_grade(run.id, grade):
                    graded += 1
                else:
                    skipped += 1

            experiment_id = await self._ensure_prompt_experiment()
            actions.append(
                {
                    "type": "prompt_eval_bridge",
                    "graded": graded,
                    "skipped": skipped,
                    "experiment_id": experiment_id,
                    "legion_role": "prompt evaluation bridge",
                }
            )
            snapshot = await self._snapshot(include_legion=True)
            report = self._report_from_snapshot("prompt_eval", snapshot, actions)
            report["prompt_eval"] = {"requested": limit, "graded": graded, "skipped": skipped, "experiment_id": experiment_id}
            summary = f"Prompt bridge graded {graded} company prompt runs and skipped {skipped}."
            status = "completed"
        except Exception as e:  # noqa: BLE001
            logger.exception("company_prompt_eval_bridge_failed")
            errors.append(f"{type(e).__name__}: {e}")
            report = {"prompt_eval": {"requested": limit, "graded": graded, "skipped": skipped}, "errors": errors}
            summary = "Company prompt evaluation bridge failed."
            status = "failed"

        return await self._save_run(
            run_id=run_id,
            run_type="prompt_eval",
            requested_by="scheduler",
            status=status,
            summary=summary,
            report=report,
            actions=actions,
            errors=errors,
            started_at=started,
        )

    async def spoken_company_summary(self, query: str) -> dict[str, Any]:
        q = query.lower()
        if "approval" in q:
            approvals = (await self._snapshot(include_legion=False))["approvals"]
            if not approvals:
                text = "No company approvals are waiting right now."
            else:
                top = _compact(approvals[0]["summary"], limit=110)
                text = f"{len(approvals)} company approvals are waiting. First: {top}."
            return {"response_text": text, "kind": "approvals", "approvals": approvals[:5]}

        if "overnight" in q or "last night" in q:
            latest = await self.latest_report(report_type="overnight")
            text = latest.get("summary") or "No overnight company report has run yet."
            return {"response_text": _compact(text, limit=240), "kind": "overnight", "report": latest}

        if "block" in q or "stuck" in q:
            blocked = (await self._snapshot(include_legion=False))["blocked_tasks"]
            if not blocked:
                text = "No company tasks are blocked right now."
            else:
                text = f"{len(blocked)} company tasks are blocked. First: {_compact(blocked[0]['title'], limit=120)}."
            return {"response_text": text, "kind": "blockers", "blocked_tasks": blocked[:5]}

        if "today" in q or "work on" in q or "next" in q:
            today = await self.today()
            return {"response_text": _compact(today["answer"], limit=240), "kind": "today", "today": today}

        snapshot = await self._snapshot(include_legion=False)
        text = self._summary_from_snapshot(snapshot)
        return {"response_text": _compact(text, limit=240), "kind": "status", "status": snapshot}

    async def _basic_operator_state(self) -> tuple[dict[str, Any], Optional[dict[str, Any]], Optional[dict[str, Any]], dict[str, Any]]:
        config = await self.get_config()
        latest_runs = await self.runs(limit=1)
        latest = latest_runs[0] if latest_runs else None
        overnight_runs = await self.runs(run_type="overnight", limit=1)
        overnight = overnight_runs[0] if overnight_runs else None
        today = await self.today()
        return config, latest, overnight, today

    async def _save_run(
        self,
        *,
        run_id: str,
        run_type: str,
        requested_by: str,
        status: str,
        summary: str,
        report: dict[str, Any],
        actions: list[dict[str, Any]],
        errors: list[str],
        started_at: datetime,
    ) -> dict[str, Any]:
        completed_at = _now()
        async with get_session() as session:
            row = CompanyOperatorRunModel(
                id=run_id,
                run_type=run_type,
                requested_by=requested_by,
                status=status,
                summary=summary,
                report=report,
                actions=actions,
                errors=errors,
                started_at=started_at,
                completed_at=completed_at,
            )
            session.add(row)
            await session.flush()
            return _serialize_run(row)

    async def _snapshot(self, *, include_legion: bool, tolerate_errors: bool = False) -> dict[str, Any]:
        try:
            tasks = await get_task_service().list_tasks(project_id=COMPANY_PROJECT_ID, limit=500)
            tasks = [t for t in tasks if getattr(t.status, "value", t.status) != TaskStatus.ARCHIVED.value]
            approvals = await get_approval_queue().list(status="pending", limit=100)
            questions = await self._company_questions(limit=200, status="open")
            question_counts = await self._company_question_counts()
            agent_tasks = await self._company_agent_tasks(limit=500)
            agent_task_counts = await self._company_agent_task_counts()
            roles = await self._company_roles()
            scheduler = await self._company_scheduler_audit()
            prompt_lab = await self._prompt_lab_stats()
            docs = get_company_context_service().list_docs()
            legion = await self._legion_status() if include_legion else {"status": "not_checked"}
        except Exception:
            if not tolerate_errors:
                raise
            tasks, approvals, questions, agent_tasks, roles, scheduler, docs = [], [], [], [], [], [], []
            question_counts = {"questions_total": 0, "questions_open": 0, "questions_answered": 0, "questions_dismissed": 0}
            agent_task_counts = {
                "agent_tasks_total": 0,
                "agent_tasks_active": 0,
                "agent_tasks_running": 0,
                "agent_tasks_queued": 0,
                "agent_tasks_needs_review": 0,
                "agent_tasks_stale": 0,
            }
            prompt_lab, legion = {}, {"status": "not_checked"}

        task_cards = [_serialize_task(t) for t in tasks]
        formation_tasks = [t for t in task_cards if t["formation"]]
        blocked = [t for t in task_cards if t["status"] == TaskStatus.BLOCKED.value]
        next_tasks = [
            t for t in task_cards
            if t["status"] in {TaskStatus.TODO.value, TaskStatus.IN_PROGRESS.value, TaskStatus.BACKLOG.value}
        ]
        next_tasks.sort(key=lambda t: {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(str(t["priority"]), 4))

        counts = {
            "tasks_total": len(task_cards),
            "tasks_backlog": sum(1 for t in task_cards if t["status"] == TaskStatus.BACKLOG.value),
            "tasks_ready": sum(1 for t in task_cards if t["status"] == TaskStatus.TODO.value),
            "tasks_in_progress": sum(1 for t in task_cards if t["status"] == TaskStatus.IN_PROGRESS.value),
            "tasks_blocked": len(blocked),
            "tasks_done": sum(1 for t in task_cards if t["status"] == TaskStatus.DONE.value),
            "approvals_pending": len(approvals),
            "subagents": len(roles),
            "company_docs": len(docs),
        }
        counts.update(agent_task_counts)
        counts.update(question_counts)

        formation_done = sum(1 for t in formation_tasks if t["status"] == TaskStatus.DONE.value)
        formation_blocked = sum(1 for t in formation_tasks if t["status"] == TaskStatus.BLOCKED.value)
        formation_ready = sum(1 for t in formation_tasks if t["status"] in {TaskStatus.TODO.value, TaskStatus.IN_PROGRESS.value})
        formation = {
            "total": len(formation_tasks),
            "done": formation_done,
            "ready": formation_ready,
            "blocked": formation_blocked,
            "percent": round((formation_done / len(formation_tasks)) * 100, 1) if formation_tasks else 0,
            "tasks": formation_tasks[:20],
        }

        role_cards = []
        agent_by_role: dict[str, list[AgentTaskModel]] = {}
        for task in agent_tasks:
            agent_by_role.setdefault(task.assigned_role or "unassigned", []).append(task)
        questions_by_role: dict[str, list[CompanyAgentQuestionModel]] = {}
        for question in questions:
            if question.status == "open":
                questions_by_role.setdefault(question.asked_by_agent or "ceo", []).append(question)
        task_owner_by_id = {t["id"]: t.get("owner_agent") or "ceo" for t in task_cards}
        approvals_by_role: dict[str, list[AgentApprovalModel]] = {}
        for approval in approvals:
            task_id = str((approval.arguments or {}).get("task_id") or "")
            role_id = task_owner_by_id.get(task_id, "ceo")
            approvals_by_role.setdefault(role_id, []).append(approval)
        for role in roles:
            now = _now()
            role_tasks = agent_by_role.get(role.id, [])
            running = [t for t in role_tasks if _agent_task_is_running(t, now=now)]
            stale_running = [t for t in role_tasks if t.status == "in_progress" and not _agent_task_is_running(t, now=now)]
            queued = [t for t in role_tasks if t.status in {"pending", "failed"}]
            needs_review = [t for t in role_tasks if t.status == "needs_review"]
            role_questions = questions_by_role.get(role.id, [])
            role_approvals = approvals_by_role.get(role.id, [])
            blocked_for_approval = [
                t for t in role_tasks
                if t.status == "pending" and (t.context or {}).get("external_actions_allowed") is True
            ]
            failed = [t for t in role_tasks if t.status == "failed"]
            last = role_tasks[0] if role_tasks else None
            if running:
                agent_status = "Running now"
                idle_reason = None
                current_assignment = running[0].title
            elif role_questions:
                agent_status = "Waiting on Adam"
                idle_reason = _compact(role_questions[0].question, limit=160)
                current_assignment = queued[0].title if queued else None
            elif blocked_for_approval:
                agent_status = "Waiting on approval"
                idle_reason = "Waiting for Adam approval before external/high-risk work."
                current_assignment = blocked_for_approval[0].title
            elif role_approvals:
                agent_status = "Waiting on approval"
                idle_reason = _compact(role_approvals[0].summary, limit=160)
                current_assignment = queued[0].title if queued else None
            elif needs_review:
                agent_status = "Needs review"
                idle_reason = needs_review[0].error or "Last output needs human review."
                current_assignment = needs_review[0].title
            elif stale_running:
                agent_status = "Needs review"
                idle_reason = "Previous run lease expired; the next agent_work tick will recover and retry it."
                current_assignment = stale_running[0].title
            elif queued:
                agent_status = "Queued"
                idle_reason = "Queued for the next 15-minute company agent work cycle."
                current_assignment = queued[0].title
            elif failed and failed[0] is last:
                agent_status = "Needs review"
                idle_reason = f"Last run failed: {failed[0].error or 'unknown error'}"
                current_assignment = None
            elif not role_tasks:
                agent_status = "Idle"
                idle_reason = "No work assigned yet."
                current_assignment = None
            else:
                agent_status = "Idle"
                idle_reason = "No pending internal work."
                current_assignment = None
            role_cards.append(
                {
                    "id": role.id,
                    "name": role.name,
                    "description": role.description,
                    "capabilities": role.capabilities or [],
                    "autonomy": (role.delegation_rules or {}).get("autonomy", "write_local"),
                    "agent_status": agent_status,
                    "active_tasks": len(running),
                    "running_tasks": len(running),
                    "queued_tasks": len(queued),
                    "waiting_on_adam": len(role_questions),
                    "waiting_on_approval": len(role_approvals) + len(blocked_for_approval),
                    "needs_review_tasks": len(needs_review) + len(stale_running),
                    "question_count": len(role_questions),
                    "approval_count": len(role_approvals),
                    "total_tasks": len(role_tasks),
                    "last_run_at": _dt(last.completed_at or last.started_at or last.created_at) if last else None,
                    "next_scheduled_run": "Every 15 minutes via company_agent_work",
                    "current_assignment": current_assignment,
                    "blocked_reason": running[0].error if running and running[0].error else None,
                    "idle_reason": idle_reason,
                    "last_output": _compact(str((last.result or {}).get("summary") or (last.result or {}).get("output") or last.error or ""), limit=180) if last else None,
                    "last_task_status": last.status if last else None,
                    "cost_usd": round(sum(float(t.cost_usd or 0) for t in role_tasks), 4),
                }
            )

        return {
            "generated_at": _dt(_now()),
            "counts": counts,
            "tasks": task_cards,
            "next_tasks": next_tasks[:20],
            "blocked_tasks": blocked,
            "formation": formation,
            "approvals": [_serialize_approval(a) for a in approvals],
            "questions": [_serialize_question(q) for q in questions],
            "subagents": role_cards,
            "agent_tasks": [_serialize_agent_task(t) for t in agent_tasks[:40]],
            "scheduler": scheduler,
            "prompt_lab": prompt_lab,
            "legion": legion,
            "docs": {"count": len(docs), "titles": [d["title"] for d in docs[:12]]},
        }

    async def _ensure_company_roles(self, *, actions: Optional[list[dict[str, Any]]] = None) -> None:
        async with get_session() as session:
            existing = {r[0] for r in (await session.execute(select(AgentRoleModel.id))).all()}
            for spec in SUBAGENT_ROLES:
                if spec["id"] in existing:
                    continue
                row = AgentRoleModel(
                    id=spec["id"],
                    name=spec["name"],
                    description=f"ADA AI LLC company subagent for {', '.join(spec['capabilities'])}.",
                    capabilities=spec["capabilities"],
                    system_prompt=(
                        f"You are the {spec['name']} for ADA AI LLC. "
                        "Work only on internal analysis, drafts, checklists, and reports unless an approval gate is present. "
                        "Never perform purchases, filings, tax elections, client messages, public changes, or account changes."
                    ),
                    llm_provider="kimi",
                    llm_model="kimi-k2.5",
                    llm_temperature=0.4,
                    delegation_rules={"autonomy": spec["autonomy"], "approval_required_for": ["external", "financial", "legal", "client", "public"]},
                )
                session.add(row)
                existing.add(spec["id"])
                if actions is not None:
                    actions.append({"type": "role_created", "role_id": spec["id"], "name": spec["name"]})
            await session.flush()

    async def _reconcile_company_facts(self, config: dict[str, Any], *, requested_by: str = "zero-company-operator") -> list[dict[str, Any]]:
        facts = config.get("company_facts") or {}
        if not facts.get("llc_created"):
            return []

        actions: list[dict[str, Any]] = []
        tasks = await get_task_service().list_tasks(project_id=COMPANY_PROJECT_ID, limit=500)
        llc_done_re = re.compile(r"\b(verify name on sunbiz|file florida llc|articles of organization)\b", re.I)
        for task in tasks:
            status = getattr(task.status, "value", task.status)
            if status in {TaskStatus.DONE.value, TaskStatus.ARCHIVED.value}:
                continue
            if not llc_done_re.search(task.title):
                continue
            before = task.model_dump(mode="json")
            updated = await get_task_service().update_task(
                task.id,
                TaskUpdate(
                    status=TaskStatus.DONE,
                    approval_state="approved",
                    risk_level=task.risk_level or "high",
                    blocked_reason="",
                ),
            )
            if not updated:
                continue
            await get_company_work_item_service().record_event(
                task.id,
                "fact_reconciled",
                actor=requested_by or "zero-company-operator",
                summary="Marked done because Adam confirmed ADA AI LLC has been created.",
                before=before,
                after={"company_facts": facts, "task": updated.model_dump(mode="json")},
            )
            actions.append(
                {
                    "type": "fact_reconciled",
                    "task_id": task.id,
                    "title": task.title,
                    "fact": "ADA AI LLC created",
                }
            )
        return actions

    async def _triage_formation_tasks(self, config: dict[str, Any]) -> list[dict[str, Any]]:
        max_items = int(config.get("max_work_items_per_tick") or 8)
        actions: list[dict[str, Any]] = []
        tasks = await get_task_service().list_tasks(project_id=COMPANY_PROJECT_ID, limit=500)
        formation_tasks = [t for t in tasks if _is_formation_task(t) and t.status in {TaskStatus.BACKLOG, TaskStatus.TODO, TaskStatus.BLOCKED}]
        for task in formation_tasks[:max_items]:
            high_risk = _is_high_risk_task(task)
            if high_risk and task.status != TaskStatus.BLOCKED:
                updated = await get_task_service().update_task(
                    task.id,
                    TaskUpdate(
                        status=TaskStatus.BLOCKED,
                        risk_level=task.risk_level or "high",
                        approval_state="pending",
                        blocked_reason="Awaiting Adam approval gate before any legal, financial, account, or public action.",
                    ),
                )
                if updated:
                    actions.append({"type": "task_blocked_for_approval", "task_id": task.id, "title": task.title})
            elif not high_risk and task.status == TaskStatus.BACKLOG:
                updated = await get_task_service().update_task(task.id, TaskUpdate(status=TaskStatus.TODO))
                if updated:
                    actions.append({"type": "task_moved_to_ready", "task_id": task.id, "title": task.title})
        return actions

    async def _ensure_formation_subagent_tasks(self, config: dict[str, Any]) -> list[dict[str, Any]]:
        max_items = int(config.get("max_agent_tasks_per_tick") or 6)
        actions: list[dict[str, Any]] = []
        async with get_session() as session:
            existing_result = await session.execute(
                select(AgentTaskModel.title)
                .where(AgentTaskModel.project_id == COMPANY_PROJECT_ID)
                .where(AgentTaskModel.title.in_([t["title"] for t in FORMATION_AGENT_TASKS]))
            )
            existing = {r[0] for r in existing_result.all()}

        created = 0
        for spec in FORMATION_AGENT_TASKS:
            if created >= max_items:
                break
            if spec["title"] in existing:
                continue
            req = AgentTaskCreate(
                title=spec["title"],
                description=spec["description"],
                task_type=AgentTaskType.PLANNING,
                assigned_role=spec["assigned_role"],
                priority=2,
                project_id=COMPANY_PROJECT_ID,
                context={"work_packet": "formation_sprint", "autonomy": "internal_work", "external_actions_allowed": False},
            )
            task = await get_agent_company_service().create_task(req)
            actions.append({"type": "agent_task_created", "agent_task_id": task.id, "assigned_role": task.assigned_role, "title": task.title})
            created += 1
        return actions

    async def _queue_formation_approvals(self, config: dict[str, Any]) -> list[dict[str, Any]]:
        return await self._queue_company_approvals(config)

    async def _queue_company_approvals(self, config: dict[str, Any]) -> list[dict[str, Any]]:
        max_items = int(config.get("max_approvals_per_tick") or 6)
        actions: list[dict[str, Any]] = []
        tasks = await get_task_service().list_tasks(project_id=COMPANY_PROJECT_ID, limit=500)
        pending = await get_approval_queue().list(status="pending", limit=200)
        pending_task_ids = {
            str((approval.arguments or {}).get("task_id"))
            for approval in pending
            if (approval.arguments or {}).get("task_id")
        }
        actions.extend(await self._normalize_pending_company_approvals(tasks, pending))

        queued = 0
        for task in tasks:
            if queued >= max_items:
                break
            if not _is_high_risk_task(task):
                continue
            if task.status in {TaskStatus.DONE, TaskStatus.ARCHIVED} or task.id in pending_task_ids:
                continue
            if task.approval_state == "approved" and task.approval_id:
                continue
            tier = _approval_tier_for_task(task)
            approval = await get_approval_queue().request(
                tool_name=COMPANY_APPROVAL_TOOL,
                tier=tier,
                summary=_approval_summary_for_task(task),
                arguments=_approval_arguments_for_task(task),
                requested_by="zero-company-operator",
            )
            await get_task_service().update_task(
                task.id,
                TaskUpdate(
                    status=TaskStatus.BLOCKED,
                    approval_state="pending",
                    approval_id=approval.id,
                    risk_level=task.risk_level or "high",
                    blocked_reason=(
                        "Approval-gated external-action task. Zero may prepare the internal packet; "
                        "Adam must approve or perform the filing, purchase, account change, legal/tax decision, "
                        "client message, or public change."
                    ),
                ),
            )
            await get_company_work_item_service().record_event(
                task.id,
                "approval_linked",
                actor="zero-company-operator",
                summary=f"Queued Adam approval gate {approval.id} for this high-risk company task.",
                after={
                    "approval_id": approval.id,
                    "tool_name": COMPANY_APPROVAL_TOOL,
                    "tier": tier,
                    "status": TaskStatus.BLOCKED.value,
                },
            )
            actions.append(
                {
                    "type": "approval_queued",
                    "approval_id": approval.id,
                    "task_id": task.id,
                    "title": task.title,
                    "tier": tier,
                    "tool_name": COMPANY_APPROVAL_TOOL,
                }
            )
            queued += 1
        return actions

    async def _normalize_pending_company_approvals(
        self,
        tasks: list[Task],
        approvals: list[AgentApprovalModel],
    ) -> list[dict[str, Any]]:
        task_by_id = {task.id: task for task in tasks}
        actions: list[dict[str, Any]] = []
        updates: list[tuple[AgentApprovalModel, Task, dict[str, Any], str, str]] = []

        for approval in approvals:
            args = approval.arguments or {}
            task_id = str(args.get("task_id") or "")
            task = task_by_id.get(task_id)
            if not task or task.status in {TaskStatus.DONE, TaskStatus.ARCHIVED} or not _is_high_risk_task(task):
                continue
            normalized_args = _approval_arguments_for_task(task)
            merged_args = {**args, **normalized_args}
            normalized_tier = _approval_tier_for_task(task)
            normalized_summary = _approval_summary_for_task(task)
            if (
                approval.tool_name == COMPANY_APPROVAL_TOOL
                and approval.tier == normalized_tier
                and approval.summary == normalized_summary
                and merged_args == args
            ):
                continue
            updates.append((approval, task, merged_args, normalized_tier, normalized_summary))

        if not updates:
            return actions

        async with get_session() as session:
            for approval, task, merged_args, normalized_tier, normalized_summary in updates:
                row = await session.get(AgentApprovalModel, approval.id)
                if not row or row.status != "pending":
                    continue
                before = {
                    "tool_name": row.tool_name,
                    "tier": row.tier,
                    "summary": row.summary,
                    "arguments": row.arguments or {},
                }
                row.tool_name = COMPANY_APPROVAL_TOOL
                row.tier = normalized_tier
                row.summary = normalized_summary
                row.arguments = merged_args
                await get_company_work_item_service().record_event(
                    task.id,
                    "approval_normalized",
                    actor="zero-company-operator",
                    summary=f"Normalized pending approval {row.id} to the ADA AI LLC company launch gate format.",
                    before=before,
                    after={
                        "approval_id": row.id,
                        "tool_name": row.tool_name,
                        "tier": row.tier,
                        "summary": row.summary,
                        "arguments": row.arguments,
                    },
                )
                actions.append(
                    {
                        "type": "approval_normalized",
                        "approval_id": row.id,
                        "task_id": task.id,
                        "title": task.title,
                        "tier": row.tier,
                        "tool_name": row.tool_name,
                    }
                )
        return actions

    async def _execute_safe_agent_tasks(
        self,
        config: dict[str, Any],
        *,
        operator_run_id: Optional[str] = None,
        target_agent_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        max_items = int(config.get("max_agent_executions_per_tick") or 2)
        if target_agent_id:
            max_items = max(1, min(max_items, 2))
        if max_items <= 0:
            return []

        actions: list[dict[str, Any]] = []
        now = _now()
        async with get_session() as session:
            query = (
                select(AgentTaskModel)
                .where(AgentTaskModel.project_id == COMPANY_PROJECT_ID)
                .where(AgentTaskModel.status.in_(("pending", "failed")))
                .where(or_(AgentTaskModel.lease_expires_at.is_(None), AgentTaskModel.lease_expires_at < now))
            )
            if target_agent_id:
                query = query.where(AgentTaskModel.assigned_role == target_agent_id)
            rows = (
                await session.execute(
                    query.order_by(AgentTaskModel.priority.asc(), AgentTaskModel.created_at.asc()).limit(50)
                )
            ).scalars().all()

        if target_agent_id:
            actions.append(
                {
                    "type": "agent_work_targeted",
                    "assigned_role": target_agent_id,
                    "eligible_tasks": len(rows),
                }
            )

        executed = 0
        for row in rows:
            context = row.context or {}
            if context.get("external_actions_allowed") is True:
                actions.append(
                    {
                        "type": "agent_task_skipped",
                        "agent_task_id": row.id,
                        "assigned_role": row.assigned_role,
                        "reason": "external_actions_allowed_requires_explicit_adam_gate",
                        "title": row.title,
                    }
                )
                continue
            if context.get("autonomy") not in {None, "internal_work", "write_local", "approval_staged"}:
                actions.append(
                    {
                        "type": "agent_task_skipped",
                        "agent_task_id": row.id,
                        "assigned_role": row.assigned_role,
                        "reason": f"autonomy_{context.get('autonomy')}",
                        "title": row.title,
                    }
                )
                continue
            if executed >= max_items:
                break

            try:
                leased = await self._lease_agent_task(
                    row.id,
                    lease_id=operator_run_id or f"lease-{uuid.uuid4().hex[:12]}",
                    minutes=int(config.get("agent_task_lease_minutes") or 20),
                )
                if not leased:
                    actions.append(
                        {
                            "type": "agent_task_skipped",
                            "agent_task_id": row.id,
                            "assigned_role": row.assigned_role,
                            "reason": "leased_by_another_run",
                            "title": row.title,
                        }
                    )
                    continue
                result = await get_agent_company_service().execute_task(row.id)
                prompt_run_id = await self._record_subagent_prompt_run(result)
                linked_task_id = (result.context or {}).get("zero_task_id")
                quality_flags = await self._flag_stale_agent_output(result.id, result.result or {})
                question_actions = await self._create_agent_questions_from_result(
                    result,
                    operator_run_id=operator_run_id,
                    limit=int(config.get("max_questions_per_tick") or 10),
                )
                if linked_task_id:
                    await get_company_work_item_service().record_event(
                        str(linked_task_id),
                        "agent_run_completed",
                        actor=result.assigned_role or "company_subagent",
                        summary=f"{result.assigned_role or 'subagent'} completed internal packet: {result.title}",
                        after={
                            "agent_task_id": result.id,
                            "status": result.status,
                            "prompt_run_id": prompt_run_id,
                            "result": result.result or {},
                            "quality_flags": quality_flags,
                        },
                    )
                actions.append(
                    {
                        "type": "agent_task_executed",
                        "agent_task_id": result.id,
                        "assigned_role": result.assigned_role,
                        "status": result.status,
                        "title": result.title,
                        "prompt_run_id": prompt_run_id,
                        "quality_flags": quality_flags,
                    }
                )
                actions.extend(question_actions)
                executed += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("company_agent_task_execute_failed", agent_task_id=row.id, error=str(exc))
                await self._release_agent_task(row.id)
                actions.append(
                    {
                        "type": "agent_task_execute_failed",
                        "agent_task_id": row.id,
                        "assigned_role": row.assigned_role,
                        "title": row.title,
                        "error": str(exc)[:300],
                    }
                )
        return actions

    async def _lease_agent_task(self, task_id: str, *, lease_id: str, minutes: int = 20) -> bool:
        now = _now()
        expires = now + timedelta(minutes=max(1, minutes))
        async with get_session() as session:
            result = await session.execute(
                update(AgentTaskModel)
                .where(AgentTaskModel.id == task_id)
                .where(AgentTaskModel.status.in_(("pending", "failed")))
                .where(or_(AgentTaskModel.lease_expires_at.is_(None), AgentTaskModel.lease_expires_at < now))
                .values(lease_id=lease_id, lease_expires_at=expires, last_heartbeat_at=now)
            )
            await session.commit()
            return int(result.rowcount or 0) == 1

    async def _release_agent_task(self, task_id: str) -> None:
        async with get_session() as session:
            row = await session.get(AgentTaskModel, task_id)
            if row:
                row.lease_id = None
                row.lease_expires_at = None
                row.last_heartbeat_at = _now()
                await session.commit()

    @staticmethod
    def _stale_agent_output_flags(result: dict[str, Any]) -> list[str]:
        text = str(result)
        flags: list[str] = []
        stale_patterns = {
            "deprecated_company_identity": r"\bDoherty Applied AI LLC\b|\bDE LLC\b|\bWyoming LLC\b",
            "unsupported_ownership_assumption": r"\b60/40\b|\bco[- ]founder split\b",
            "unsafe_live_trading_claim": r"\bplaced live order\b|\bsubmitted trade\b|\bexecuted trade\b",
            "pre_llc_created_assumption": r"\bif the LLC is created\b|\bbefore creating the LLC\b",
        }
        for flag, pattern in stale_patterns.items():
            if re.search(pattern, text, re.I):
                flags.append(flag)
        for flag in result.get("stale_assumption_flags") or []:
            if flag and str(flag) not in flags:
                flags.append(str(flag))
        return flags

    async def _flag_stale_agent_output(self, agent_task_id: str, result: dict[str, Any]) -> list[str]:
        flags = self._stale_agent_output_flags(result)
        if not flags:
            return []
        async with get_session() as session:
            row = await session.get(AgentTaskModel, agent_task_id)
            if row:
                updated_result = dict(row.result or result or {})
                updated_result["quality_flags"] = flags
                updated_result["needs_review_reason"] = "Agent output mentioned stale or unsafe assumptions."
                row.result = updated_result
                row.status = "needs_review"
                row.error = "Needs review: " + ", ".join(flags)
                row.completed_at = _now()
                row.lease_id = None
                row.lease_expires_at = None
                await session.commit()
        return flags

    @staticmethod
    def _extract_agent_questions(result: dict[str, Any]) -> list[dict[str, Any]]:
        raw_questions = result.get("questions_for_adam") or result.get("questions") or []
        if isinstance(raw_questions, str):
            raw_questions = [raw_questions]
        questions: list[dict[str, Any]] = []
        for item in raw_questions:
            if isinstance(item, str):
                question = item.strip()
                payload: dict[str, Any] = {"question": question}
            elif isinstance(item, dict):
                question = str(item.get("question") or item.get("text") or "").strip()
                payload = dict(item)
                payload["question"] = question
            else:
                continue
            if question:
                questions.append(payload)
        return questions

    async def _question_exists(self, *, agent_task_id: str, question: str) -> bool:
        normalized = _normalize_question_text(question)
        async with get_session() as session:
            rows = (
                await session.execute(
                    select(CompanyAgentQuestionModel)
                    .where(CompanyAgentQuestionModel.status == "open")
                    .where(
                        or_(
                            CompanyAgentQuestionModel.agent_task_id == agent_task_id,
                            CompanyAgentQuestionModel.source == "company_agent_output",
                        )
                    )
                    .order_by(CompanyAgentQuestionModel.created_at.desc())
                    .limit(500)
                )
            ).scalars().all()
        return any(_normalize_question_text(row.question) == normalized for row in rows)

    async def _create_agent_questions_from_result(
        self,
        result: Any,
        *,
        operator_run_id: Optional[str] = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        payload = result.result or {}
        questions = self._extract_agent_questions(payload)
        actions: list[dict[str, Any]] = []
        if not questions:
            return actions
        questions = sorted(
            questions,
            key=lambda item: (
                0 if str(item.get("priority") or "").lower() in {"critical", "high"} else 1,
                0 if bool(item.get("blocks_progress")) else 1,
                len(str(item.get("question") or "")),
            ),
        )[: max(1, min(limit, 1))]

        linked_task_id = (result.context or {}).get("zero_task_id")
        created = 0
        for item in questions:
            if created >= limit:
                break
            question = str(item["question"]).strip()
            if LOW_VALUE_QUESTION_RE.search(question):
                actions.append(
                    {
                        "type": "question_suppressed",
                        "agent_task_id": result.id,
                        "assigned_role": result.assigned_role,
                        "reason": "generic_nonblocking_fallback_question",
                        "question": question,
                    }
                )
                continue
            if await self._question_exists(agent_task_id=result.id, question=question):
                continue
            row = CompanyAgentQuestionModel(
                id=f"caq-{uuid.uuid4().hex[:12]}",
                question=question,
                context={
                    "agent_task_title": result.title,
                    "agent_task_status": result.status,
                    "result_summary": payload.get("summary"),
                    "recommended_default": item.get("recommended_default") or item.get("suggested_default"),
                    "why_needed": item.get("why_needed") or item.get("rationale"),
                    "blocks_progress": bool(item.get("blocks_progress")),
                    "decision_type": item.get("decision_type") or item.get("category"),
                    "self_improvement_note": payload.get("self_improvement_notes"),
                },
                answer_type=str(item.get("answer_type") or "text"),
                options=item.get("options") or [],
                priority=str(item.get("priority") or ("high" if linked_task_id else "medium")),
                status="open",
                asked_by_agent=result.assigned_role or "ceo",
                task_id=str(linked_task_id) if linked_task_id else None,
                agent_task_id=result.id,
                operator_run_id=operator_run_id,
                source="company_agent_output",
            )
            async with get_session() as session:
                session.add(row)
                await session.flush()
                serialized = _serialize_question(row)
            if linked_task_id:
                await get_company_work_item_service().record_event(
                    str(linked_task_id),
                    "question_created",
                    actor=result.assigned_role or "company_subagent",
                    summary=f"Agent asked Adam: {_compact(question, limit=140)}",
                    after={"question_id": serialized["id"], "agent_task_id": result.id},
                )
            actions.append(
                {
                    "type": "question_created",
                    "question_id": serialized["id"],
                    "task_id": linked_task_id,
                    "agent_task_id": result.id,
                    "assigned_role": result.assigned_role,
                    "question": question,
                }
            )
            created += 1
        return actions

    async def _pending_task_approval_exists(self, task_id: str, *, tool_name: Optional[str] = None) -> bool:
        pending = await get_approval_queue().list(status="pending", limit=200)
        for approval in pending:
            args = approval.arguments or {}
            if args.get("task_id") != task_id:
                continue
            if tool_name and approval.tool_name != tool_name:
                continue
            return True
        return False

    async def _queue_task_completion_approval(self, task: Task) -> Optional[AgentApprovalModel]:
        tool_name = "company_work_item_completion_gate"
        if await self._pending_task_approval_exists(task.id, tool_name=tool_name):
            return None
        tier = "financial" if re.search(
            r"\b(bank|card|purchase|subscription|cpa|attorney|registered agent|tax)\b",
            _task_text(task),
            re.I,
        ) else "write_external"
        return await get_approval_queue().request(
            tool_name=tool_name,
            tier=tier,
            summary=f"Approval needed before marking high-risk company task done: {task.title}",
            arguments={
                "task_id": task.id,
                "title": task.title,
                "project_id": COMPANY_PROJECT_ID,
                "requested_status": "done",
                "guardrail": (
                    "High-risk company tasks cannot be marked complete by automation "
                    "until Adam confirms the external/legal/financial/client/public/account action."
                ),
            },
            requested_by="zero-company-operator",
        )

    async def _recover_stale_agent_tasks(
        self,
        config: dict[str, Any],
        *,
        operator_run_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        lease_minutes = int(config.get("agent_task_lease_minutes") or DEFAULT_CONFIG["agent_task_lease_minutes"])
        now = _now()
        heartbeat_cutoff = now - timedelta(minutes=max(lease_minutes * 2, 30))
        actions: list[dict[str, Any]] = []
        async with get_session() as session:
            rows = (
                await session.execute(
                    select(AgentTaskModel)
                    .where(AgentTaskModel.project_id == COMPANY_PROJECT_ID)
                    .where(AgentTaskModel.status == "in_progress")
                    .where(
                        or_(
                            AgentTaskModel.lease_expires_at.is_(None),
                            AgentTaskModel.lease_expires_at < now,
                            AgentTaskModel.last_heartbeat_at.is_(None),
                            AgentTaskModel.last_heartbeat_at < heartbeat_cutoff,
                        )
                    )
                    .order_by(AgentTaskModel.started_at.asc())
                    .limit(25)
                )
            ).scalars().all()
            for row in rows:
                before = {
                    "status": row.status,
                    "lease_id": row.lease_id,
                    "lease_expires_at": _dt(row.lease_expires_at),
                    "last_heartbeat_at": _dt(row.last_heartbeat_at),
                }
                row.status = "failed"
                row.error = "Recovered stale in-progress company agent lease; eligible for the next safe agent_work retry."
                row.lease_id = None
                row.lease_expires_at = None
                row.last_heartbeat_at = now
                context = dict(row.context or {})
                recovery_events = list(context.get("lease_recovery_events") or [])
                recovery_events.append(
                    {
                        "operator_run_id": operator_run_id,
                        "recovered_at": now.isoformat(),
                        "previous": before,
                    }
                )
                context["lease_recovery_events"] = recovery_events[-5:]
                row.context = context
                actions.append(
                    {
                        "type": "stale_agent_task_recovered",
                        "agent_task_id": row.id,
                        "assigned_role": row.assigned_role,
                        "title": row.title,
                        "previous": before,
                        "new_status": row.status,
                    }
                )
            await session.flush()
        return actions

    async def _company_agent_tasks(self, *, limit: int) -> list[AgentTaskModel]:
        async with get_session() as session:
            result = await session.execute(
                select(AgentTaskModel)
                .where(AgentTaskModel.project_id == COMPANY_PROJECT_ID)
                .order_by(AgentTaskModel.created_at.desc())
                .limit(limit)
            )
            return list(result.scalars().all())

    async def _company_agent_task_counts(self) -> dict[str, int]:
        now = _now()
        async with get_session() as session:
            status_rows = (
                await session.execute(
                    select(AgentTaskModel.status, func.count())
                    .where(AgentTaskModel.project_id == COMPANY_PROJECT_ID)
                    .group_by(AgentTaskModel.status)
                )
            ).all()
            running = (
                await session.execute(
                    select(func.count())
                    .select_from(AgentTaskModel)
                    .where(AgentTaskModel.project_id == COMPANY_PROJECT_ID)
                    .where(AgentTaskModel.status == "in_progress")
                    .where(AgentTaskModel.lease_expires_at.isnot(None))
                    .where(AgentTaskModel.lease_expires_at > now)
                )
            ).scalar_one()
        by_status = {str(status): int(count or 0) for status, count in status_rows}
        total = sum(by_status.values())
        stale = max(0, by_status.get("in_progress", 0) - int(running or 0))
        return {
            "agent_tasks_total": total,
            "agent_tasks_active": int(running or 0),
            "agent_tasks_running": int(running or 0),
            "agent_tasks_queued": by_status.get("pending", 0) + by_status.get("failed", 0),
            "agent_tasks_needs_review": by_status.get("needs_review", 0),
            "agent_tasks_stale": stale,
        }

    async def _company_question_counts(self) -> dict[str, int]:
        async with get_session() as session:
            rows = (
                await session.execute(
                    select(CompanyAgentQuestionModel.status, func.count())
                    .group_by(CompanyAgentQuestionModel.status)
                )
            ).all()
        by_status = {str(status): int(count or 0) for status, count in rows}
        return {
            "questions_total": sum(by_status.values()),
            "questions_open": by_status.get("open", 0),
            "questions_answered": by_status.get("answered", 0),
            "questions_dismissed": by_status.get("dismissed", 0),
        }

    async def _company_questions(
        self,
        *,
        limit: int,
        status: Optional[str] = None,
    ) -> list[CompanyAgentQuestionModel]:
        async with get_session() as session:
            query = (
                select(CompanyAgentQuestionModel)
                .order_by(CompanyAgentQuestionModel.created_at.desc())
                .limit(limit)
            )
            if status:
                query = query.where(CompanyAgentQuestionModel.status == status)
            result = await session.execute(query)
            return list(result.scalars().all())

    async def _company_roles(self) -> list[AgentRoleModel]:
        async with get_session() as session:
            role_ids = [r["id"] for r in SUBAGENT_ROLES]
            result = await session.execute(
                select(AgentRoleModel)
                .where(AgentRoleModel.id.in_(role_ids))
                .order_by(AgentRoleModel.name.asc())
            )
            return list(result.scalars().all())

    async def _company_scheduler_audit(self) -> list[dict[str, Any]]:
        async with get_session() as session:
            result = await session.execute(
                select(SchedulerAuditLogModel)
                .where(SchedulerAuditLogModel.job_name.like("company_%"))
                .order_by(SchedulerAuditLogModel.created_at.desc())
                .limit(20)
            )
            rows = result.scalars().all()
        return [
            {
                "job_name": r.job_name,
                "status": r.status,
                "started_at": _dt(r.started_at),
                "completed_at": _dt(r.completed_at),
                "duration_seconds": r.duration_seconds,
                "error": r.error,
            }
            for r in rows
        ]

    async def _prompt_lab_stats(self) -> dict[str, Any]:
        async with get_session() as session:
            total = (
                await session.execute(
                    select(PromptRunModel)
                    .where(PromptRunModel.source.in_(["company_operator", "company_subagent"]))
                    .order_by(PromptRunModel.created_at.desc())
                    .limit(100)
                )
            ).scalars().all()
        graded = [r for r in total if r.graded_at is not None]
        avg_quality = round(sum(float(r.quality_score or 0) for r in graded) / len(graded), 1) if graded else None
        return {
            "runs_100": len(total),
            "graded_100": len(graded),
            "ungraded_100": len(total) - len(graded),
            "avg_quality": avg_quality,
            "latest": [
                {
                    "id": r.id,
                    "task_type": r.task_type,
                    "source": r.source,
                    "quality_score": r.quality_score,
                    "graded_at": _dt(r.graded_at),
                    "created_at": _dt(r.created_at),
                }
                for r in total[:10]
            ],
        }

    async def _legion_status(self) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(1.5, connect=0.5)) as client:
                resp = await client.get("http://localhost:8005/health")
            if resp.status_code < 400:
                return {"status": "ok", "url": "http://localhost:8005", "detail": resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp.text[:200]}
            return {"status": "degraded", "url": "http://localhost:8005", "code": resp.status_code}
        except Exception as e:
            return {"status": "unreachable", "url": "http://localhost:8005", "error": str(e)[:160]}

    async def _record_operator_prompt_run(self, run_id: str, run_type: str, report: dict[str, Any], summary: str) -> Optional[str]:
        return await get_prompt_evolution_service().record_run(
            PromptRunCreate(
                task_type=f"company_operator_{run_type}",
                source="company_operator",
                source_id=run_id,
                provider="zero",
                model="rules-v1",
                system_prompt="Zero Company Operator creates supervised company reports and approval-gated internal work packets.",
                user_prompt=f"Generate {run_type} company operator report from current Company OS state.",
                response_text=summary,
                rendered_variables={"run_type": run_type},
                success=True,
                context={"report": report},
            )
        )

    async def _record_subagent_prompt_run(self, agent_task: Any) -> Optional[str]:
        result = getattr(agent_task, "result", None) or {}
        summary = (
            result.get("summary")
            or result.get("output")
            or result.get("analysis")
            or f"{getattr(agent_task, 'assigned_role', 'subagent')} completed {getattr(agent_task, 'title', 'task')}."
        )
        return await get_prompt_evolution_service().record_run(
            PromptRunCreate(
                task_type=f"company_subagent_{getattr(agent_task, 'assigned_role', 'unknown')}",
                source="company_subagent",
                source_id=getattr(agent_task, "id", None) or f"agent-task-{uuid.uuid4().hex[:8]}",
                provider="zero",
                model="agent-company-service",
                system_prompt=(
                    "Company subagents perform internal analysis, drafts, checklists, reports, "
                    "and task support behind approval gates.\n\n"
                    f"{COMPANY_AGENT_PROMPT_POLICY}"
                ),
                user_prompt=getattr(agent_task, "description", None) or getattr(agent_task, "title", "Company subagent task"),
                response_text=_compact(str(summary), limit=4000),
                rendered_variables={
                    "assigned_role": getattr(agent_task, "assigned_role", None),
                    "task_type": getattr(agent_task, "task_type", None),
                    "company": "ADA AI LLC",
                    "prompt_policy": "question_budget_one_blocking_question_with_recommended_default",
                    "legion_feedback": result.get("legion_prompt_feedback"),
                    "self_improvement_notes": result.get("self_improvement_notes"),
                },
                success=getattr(agent_task, "status", None) == "completed",
                context={
                    "agent_task": agent_task.model_dump(mode="json") if hasattr(agent_task, "model_dump") else {},
                    "result": result,
                },
            )
        )

    async def _ensure_prompt_experiment(self) -> Optional[str]:
        title = "Company operator prompt evaluation loop"
        async with get_session() as session:
            existing = (
                await session.execute(
                    select(ExperimentModel)
                    .where(ExperimentModel.title == title)
                    .order_by(ExperimentModel.created_at.desc())
                    .limit(1)
                )
            ).scalars().first()
            if existing:
                return existing.id
            row = ExperimentModel(
                id=f"exp-{uuid.uuid4().hex[:12]}",
                title=title,
                hypothesis="Prompt variants that receive higher company-operator quality scores will produce clearer next actions and fewer unsafe automation proposals.",
                methodology="Legion/Zero prompt bridge grades company_operator and company_subagent prompt runs, tracks outcomes, and queues promotion approvals for high-impact prompts.",
                experiment_type="prompt_eval",
                status="designed",
                parameters={"source": "company_operator", "approval_required_for_promotion": True},
                created_by_role="llm_ops",
            )
            session.add(row)
            await session.flush()
            return row.id

    async def _ensure_company_prompt_variants(self) -> list[dict[str, Any]]:
        prompt_svc = get_prompt_evolution_service()
        actions: list[dict[str, Any]] = []
        task_types = ["company_operator_agent_work"] + [
            f"company_subagent_{role['id']}" for role in SUBAGENT_ROLES
        ]
        for task_type in task_types:
            existing = await prompt_svc.select_best(task_type)
            if existing:
                continue
            variant = await prompt_svc.register_variant(
                task_type=task_type,
                variant_name="ada_ai_llc_approval_staged_baseline",
                prompt_template=COMPANY_AGENT_PROMPT_POLICY,
                is_baseline=True,
                parameters={
                    "company": "ADA AI LLC",
                    "question_budget": 1,
                    "approval_staged": True,
                    "legion_prompt_improvement": True,
                },
            )
            actions.append(
                {
                    "type": "company_prompt_variant_registered",
                    "task_type": task_type,
                    "variant_id": variant.id,
                    "variant_name": variant.variant_name,
                }
            )
        return actions

    def _report_from_snapshot(self, run_type: str, snapshot: dict[str, Any], actions: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "run_type": run_type,
            "generated_at": snapshot.get("generated_at"),
            "operator": "Zero Company Operator",
            "company": "ADA AI LLC",
            "mode": "internal_work_with_approval_gates",
            "headline": self._summary_from_snapshot(snapshot),
            "what_zero_did": actions,
            "what_adam_should_do": snapshot.get("next_tasks", [])[:5],
            "question_queue": snapshot.get("questions", [])[:10],
            "approval_queue": snapshot.get("approvals", [])[:10],
            "blocked_work": snapshot.get("blocked_tasks", [])[:10],
            "formation_sprint": snapshot.get("formation", {}),
            "subagents": snapshot.get("subagents", []),
            "prompt_lab": snapshot.get("prompt_lab", {}),
            "legion": snapshot.get("legion", {}),
            "scheduler": snapshot.get("scheduler", []),
            "guardrails": [
                "No purchases without approval",
                "No legal filings without approval",
                "No tax elections without approval",
                "No client or public communications without approval",
                "No account or credential changes without approval",
            ],
        }

    def _summary_from_snapshot(self, snapshot: dict[str, Any]) -> str:
        counts = snapshot.get("counts", {})
        formation = snapshot.get("formation", {})
        return (
            f"Company OS has {counts.get('tasks_total', 0)} tasks, "
            f"{counts.get('tasks_blocked', 0)} blocked, "
            f"{counts.get('approvals_pending', 0)} approvals waiting, "
            f"{counts.get('questions_open', 0)} agent questions open, "
            f"{counts.get('agent_tasks_running', 0)} agents running, and "
            f"{counts.get('agent_tasks_queued', 0)} queued. "
            f"Formation sprint is {formation.get('percent', 0)}% done with "
            f"{formation.get('ready', 0)} ready and {formation.get('blocked', 0)} approval-gated."
        )

    def _today_answer(self, snapshot: dict[str, Any]) -> str:
        questions = snapshot.get("questions", [])
        approvals = snapshot.get("approvals", [])
        next_tasks = snapshot.get("next_tasks", [])
        if questions:
            return f"Start with agent questions. {len(questions)} are open, led by: {_compact(questions[0]['question'], limit=120)}."
        if approvals:
            return f"Start with approvals. {len(approvals)} are waiting, led by: {_compact(approvals[0]['summary'], limit=120)}."
        if next_tasks:
            return f"Work on this first: {_compact(next_tasks[0]['title'], limit=140)}."
        return "No urgent company tasks are ready. Run the operator tick to refresh formation next steps."


@lru_cache()
def get_company_operator_service() -> CompanyOperatorService:
    return CompanyOperatorService()
