"""Company dashboard review and safe auto-enrichment.

The review pass grades every active Company OS work item, fills in useful
internal next steps, and makes agent/operator activity visible in task history.
It deliberately stops at internal preparation; legal, financial, client,
public, account, and purchasing actions remain approval-gated.
"""

from __future__ import annotations

import re
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any, Optional

from sqlalchemy import func, select

from app.db.models import AgentApprovalModel, AgentTaskModel, CompanyOperatorRunModel, CompanyTaskEventModel, CompanyWorkItemReviewModel
from app.infrastructure.database import get_session
from app.models.agent_company import AgentTaskCreate, AgentTaskType
from app.models.task import CompanyDashboardReviewSummary, CompanyWorkItemReview, Task, TaskPriority, TaskStatus, TaskUpdate
from app.services.agent_company_service import get_agent_company_service
from app.services.company_walkthroughs import walkthrough_for
from app.services.company_work_item_service import COMPANY_PROJECT_ID, get_company_work_item_service
from app.services.task_service import get_task_service


OFFICIAL_SOURCES: dict[str, dict[str, str]] = {
    "sba_startup": {
        "label": "SBA startup steps",
        "url": "https://www.sba.gov/business-guide/10-steps-start-your-business",
        "note": "Business planning, registration, tax IDs, licensing, banking, insurance, and compliance checklist.",
    },
    "irs_ein": {
        "label": "IRS EIN online",
        "url": "https://www.irs.gov/businesses/small-businesses-self-employed/get-an-employer-identification-number",
        "note": "Apply for an EIN directly with the IRS after state entity formation approval.",
    },
    "sunbiz_llc": {
        "label": "Florida Sunbiz LLC filing",
        "url": "https://dos.fl.gov/sunbiz/start-business/efile/fl-llc/",
        "note": "Florida LLC Articles of Organization, name search, payment options, and filing confirmation.",
    },
    "uspto_search": {
        "label": "USPTO trademark search",
        "url": "https://www.uspto.gov/trademarks/search",
        "note": "Search federal trademarks before investing heavily in ADA AI branding.",
    },
    "fincen_boi": {
        "label": "FinCEN BOI",
        "url": "https://www.fincen.gov/boi",
        "note": "Current federal BOI filing position and scam warnings; banks may still ask for beneficial-owner info.",
    },
}

ARCHIVE_PATTERNS = (
    "scaffold next.js dashboard app",
    "create supabase schema",
    "seed tasks, agents, approvals, assets, and deadlines",
    "build main dashboards",
    "build approval queue",
    "build legion status panel",
    "define agent profiles",
    "define permission tiers",
    "define run log",
    "define automation rules",
    "define approval policies",
)

HIGH_PRIORITY_RE = re.compile(
    r"\b("
    r"business email|domain|adappliedai|sunbiz|file florida llc|articles of organization|"
    r"ein|registered agent|operating agreement|ip assignment|bank account|credit card|"
    r"bookkeeping|receipt inbox|cpa|attorney|disclaimer|website|proposal|sow|"
    r"service packages|icp|outreach|trademark|name"
    r")\b",
    re.I,
)

CRITICAL_RE = re.compile(
    r"\b("
    r"verify name|sunbiz|file florida llc|articles of organization|ein|business email|"
    r"domain|disclaimer"
    r")\b",
    re.I,
)

APPROVAL_GATED_RE = re.compile(
    r"\b("
    r"verify name on sunbiz|file florida llc|articles of organization|apply for .*ein|get ein|"
    r"choose registered agent|sign .*operating agreement|sign .*ip assignment|"
    r"open .*bank account|open .*business checking|open .*checking|"
    r"open .*credit card|apply for .*credit card|apply for .*business card|"
    r"transfer .*equipment|transfer .*asset|transfer .*robot|buy .*robot|purchase .*robot|"
    r"get duval local business tax receipt|"
    r"schedule cpa|schedule attorney|hire cpa|hire attorney|set up business email|"
    r"configure dns|purchase domain|domain purchase|set up password vault|"
    r"publish|send .*proposal|client communication|public|linkedin|stripe account|"
    r"tax election|trademark filing|disclaimer"
    r")\b",
    re.I,
)

INTERNAL_PREP_RE = re.compile(
    r"\b("
    r"confirm .*no existing ein|"
    r"document .*issuer reporting policy|"
    r"create receipt inbox|bookkeeping categories|home-office worksheet|"
    r"assemble .*cpa .*packet|build .*packet|"
    r"record .*decision .*evidence|"
    r"draft .*ip .*schedule|software.?ip schedule .*review"
    r")\b",
    re.I,
)

OPTIONAL_LATER_RE = re.compile(
    r"\b(3d-printer|3d printer|consumables ledger|hardware inventory|gpu|printer hardware)\b",
    re.I,
)

PLACEHOLDER_RE = re.compile(
    r"(seeded from docs/company/task-backlog\.md|imported from docs/company/task-backlog\.md|created from the company os task board)",
    re.I,
)

DOMAIN_OWNER = {
    "Formation": "legal_compliance",
    "Finance": "finance_cpa",
    "Consulting": "consulting_revenue",
    "Product": "product",
    "Robotics": "robotics_lab",
    "Marketing": "marketing_content",
    "Dashboard": "engineering",
    "Agents": "ceo",
    "Knowledge": "knowledge_second_brain",
    "Operations": "ceo",
}

VALID_AGENT_ROLE_IDS = {
    "ceo",
    "finance_cpa",
    "legal_compliance",
    "procurement_asset",
    "consulting_revenue",
    "delivery",
    "product",
    "engineering",
    "llm_ops",
    "knowledge_second_brain",
    "marketing_content",
    "robotics_lab",
    "security_risk",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _text(task: Task) -> str:
    return f"{task.title} {task.description or ''} {task.domain or ''}"


def _compact(text: str, *, limit: int = 180) -> str:
    clean = " ".join(str(text).split())
    return clean if len(clean) <= limit else clean[: limit - 3].rstrip() + "..."


def _source(*keys: str) -> list[dict[str, str]]:
    return [OFFICIAL_SOURCES[key] for key in keys if key in OFFICIAL_SOURCES]


def _has_meaningful_description(task: Task) -> bool:
    description = task.description or ""
    if len(description.strip()) < 120:
        return False
    if PLACEHOLDER_RE.search(description):
        return False
    return "Steps" in description or "Acceptance" in description or len(description.splitlines()) >= 5


def _enum_value(value: Any) -> str:
    return getattr(value, "value", value)


class CompanyDashboardReviewService:
    """Grades and enriches the company launch dashboard."""

    async def run_dashboard_review(
        self,
        *,
        operator_run_id: Optional[str] = None,
        reviewed_by: str = "zero-company-operator",
        auto_apply: bool = True,
        max_agent_assignments: int = 25,
    ) -> dict[str, Any]:
        tasks = await get_task_service().list_tasks(project_id=COMPANY_PROJECT_ID, limit=1000)
        active_tasks = [task for task in tasks if _enum_value(task.status) != TaskStatus.ARCHIVED.value]
        event_counts = await self._event_counts()
        linked_agent_ids = await self._linked_agent_task_ids()

        actions: list[dict[str, Any]] = []
        reviews: list[CompanyWorkItemReview] = []
        agent_assignments = 0

        for task in active_tasks:
            packet = self._build_review_packet(
                task,
                event_count=event_counts.get(task.id, 0),
                has_agent_task=task.id in linked_agent_ids,
                operator_run_id=operator_run_id,
                reviewed_by=reviewed_by,
            )
            review = await self._save_review(task.id, packet)
            reviews.append(review)
            await get_company_work_item_service().record_event(
                task.id,
                "reviewed",
                actor=reviewed_by,
                summary=f"Dashboard review scored this work item {review.score}/100.",
                after={"review_id": review.id, "score": review.score, "recommendation": review.recommendation},
            )
            actions.append({"type": "reviewed", "task_id": task.id, "title": task.title, "score": review.score, "recommendation": review.recommendation})

            if auto_apply:
                applied = await self._apply_safe_updates(task, review)
                actions.extend(applied)

            if (
                auto_apply
                and review.recommendation != "archive"
                and task.id not in linked_agent_ids
                and agent_assignments < max_agent_assignments
                and (review.score < 85 or _enum_value(task.priority) in {"critical", "high"})
            ):
                assigned = await self._assign_internal_agent(task, review)
                if assigned:
                    linked_agent_ids.add(task.id)
                    agent_assignments += 1
                    actions.append(assigned)

        if auto_apply:
            actions.extend(await self._retire_non_gated_approvals(active_tasks, reviewed_by=reviewed_by))

        summary = await self.summary()
        actions.append(
            {
                "type": "dashboard_review_summary",
                "tasks_reviewed": len(reviews),
                "overall_score": summary.overall_score,
                "critical_blockers": summary.critical_blockers,
                "missing_info_count": summary.missing_info_count,
                "archived_count": summary.archived_count,
            }
        )
        return {
            "tasks_reviewed": len(reviews),
            "overall_score": summary.overall_score,
            "critical_blockers": summary.critical_blockers,
            "missing_info_count": summary.missing_info_count,
            "archived_count": summary.archived_count,
            "actions": actions,
        }

    async def get_review(self, task_id: str) -> Optional[CompanyWorkItemReview]:
        return await get_company_work_item_service().review(task_id)

    async def list_reviews(self, *, limit: int = 500) -> list[CompanyWorkItemReview]:
        async with get_session() as session:
            rows = (
                await session.execute(
                    select(CompanyWorkItemReviewModel)
                    .order_by(CompanyWorkItemReviewModel.updated_at.desc().nullslast(), CompanyWorkItemReviewModel.created_at.desc())
                    .limit(limit)
                )
            ).scalars().all()
        return [CompanyWorkItemReview.model_validate(row, from_attributes=True) for row in rows]

    async def summary(self) -> CompanyDashboardReviewSummary:
        reviews = await self.list_reviews(limit=1000)
        tasks = await get_task_service().list_tasks(project_id=COMPANY_PROJECT_ID, limit=1000)
        task_by_id = {task.id: task for task in tasks}
        active_reviews = [
            review
            for review in reviews
            if not task_by_id.get(review.task_id)
            or _enum_value(task_by_id[review.task_id].status) != TaskStatus.ARCHIVED.value
        ]
        overall = round(sum(review.score for review in active_reviews) / len(active_reviews)) if active_reviews else 0

        by_domain: dict[str, list[int]] = defaultdict(list)
        for review in active_reviews:
            task = task_by_id.get(review.task_id)
            domain = task.domain if task and task.domain else "Operations"
            by_domain[domain].append(review.score)
        category_scores = {domain: round(sum(scores) / len(scores)) for domain, scores in sorted(by_domain.items()) if scores}

        recommendation_counts = Counter(review.recommendation for review in reviews)
        missing_info_count = sum(len(review.missing_info or []) for review in active_reviews)
        archived_count = sum(1 for task in tasks if _enum_value(task.status) == TaskStatus.ARCHIVED.value)
        critical_blockers = sum(
            1
            for task in tasks
            if _enum_value(task.status) == TaskStatus.BLOCKED.value
            and _enum_value(task.priority) == "critical"
            and task.approval_state == "pending"
        )
        weakest_tasks = [
            {
                "task_id": review.task_id,
                "title": task_by_id.get(review.task_id).title if review.task_id in task_by_id else review.task_id,
                "score": review.score,
                "recommendation": review.recommendation,
                "domain": task_by_id.get(review.task_id).domain if review.task_id in task_by_id else None,
            }
            for review in sorted(active_reviews, key=lambda item: item.score)[:6]
        ]
        last_run = await self._latest_dashboard_review_run()
        return CompanyDashboardReviewSummary(
            overall_score=overall,
            status="ready" if active_reviews else "not_reviewed",
            tasks_reviewed=len(active_reviews),
            critical_blockers=critical_blockers,
            missing_info_count=missing_info_count,
            archived_count=archived_count,
            category_scores=category_scores,
            recommendation_counts=dict(recommendation_counts),
            weakest_tasks=weakest_tasks,
            reviews=active_reviews[:500],
            last_run=last_run,
            what_zero_did_last=(last_run or {}).get("actions", [])[:20],
        )

    def _build_review_packet(
        self,
        task: Task,
        *,
        event_count: int = 0,
        has_agent_task: bool = False,
        operator_run_id: Optional[str] = None,
        reviewed_by: str = "zero-company-operator",
    ) -> dict[str, Any]:
        steps, acceptance, sources, automation, summary = self._template_for(task)
        missing = self._missing_info(task, has_agent_task=has_agent_task, event_count=event_count)
        recommendation = "archive" if self._should_archive(task) else ("enrich" if missing else "keep")
        score = self._score(task, missing=missing, sources=sources, event_count=event_count, has_agent_task=has_agent_task, recommendation=recommendation)
        walkthrough = walkthrough_for(task.title, task.description or "")
        return {
            "score": score,
            "recommendation": recommendation,
            "summary": summary,
            "missing_info": missing,
            "action_steps": steps,
            "acceptance_criteria": acceptance,
            "automation_plan": automation,
            "source_links": sources,
            "walkthrough": walkthrough,
            "reviewed_by": reviewed_by,
            "operator_run_id": operator_run_id,
        }

    async def _event_counts(self) -> dict[str, int]:
        async with get_session() as session:
            result = await session.execute(
                select(CompanyTaskEventModel.task_id, func.count())
                .group_by(CompanyTaskEventModel.task_id)
            )
        return {str(task_id): int(count) for task_id, count in result.all()}

    async def _linked_agent_task_ids(self) -> set[str]:
        async with get_session() as session:
            rows = (
                await session.execute(
                    select(AgentTaskModel.context)
                    .where(AgentTaskModel.project_id == COMPANY_PROJECT_ID)
                )
            ).scalars().all()
        ids: set[str] = set()
        for context in rows:
            task_id = (context or {}).get("zero_task_id")
            if task_id:
                ids.add(str(task_id))
        return ids

    async def _latest_dashboard_review_run(self) -> Optional[dict[str, Any]]:
        async with get_session() as session:
            row = (
                await session.execute(
                    select(CompanyOperatorRunModel)
                    .where(CompanyOperatorRunModel.run_type == "dashboard_review")
                    .order_by(CompanyOperatorRunModel.created_at.desc())
                    .limit(1)
                )
            ).scalars().first()
        if not row:
            return None
        return {
            "id": row.id,
            "run_type": row.run_type,
            "status": row.status,
            "summary": row.summary,
            "actions": row.actions or [],
            "errors": row.errors or [],
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        }

    async def _save_review(self, task_id: str, packet: dict[str, Any]) -> CompanyWorkItemReview:
        async with get_session() as session:
            row = (
                await session.execute(
                    select(CompanyWorkItemReviewModel)
                    .where(CompanyWorkItemReviewModel.task_id == task_id)
                    .limit(1)
                )
            ).scalars().first()
            if row is None:
                row = CompanyWorkItemReviewModel(id=f"cwr-{uuid.uuid4().hex[:12]}", task_id=task_id)
                session.add(row)

            row.score = int(packet["score"])
            row.recommendation = str(packet["recommendation"])
            row.summary = packet.get("summary")
            row.missing_info = packet.get("missing_info") or []
            row.action_steps = packet.get("action_steps") or []
            row.acceptance_criteria = packet.get("acceptance_criteria") or []
            row.automation_plan = packet.get("automation_plan") or {}
            row.source_links = packet.get("source_links") or []
            walkthrough = packet.get("walkthrough")
            if walkthrough is not None:
                row.walkthrough = walkthrough
            row.reviewed_by = packet.get("reviewed_by") or "zero-company-operator"
            row.operator_run_id = packet.get("operator_run_id")
            row.updated_at = _now()
            await session.flush()
            return CompanyWorkItemReview.model_validate(row, from_attributes=True)

    async def _apply_safe_updates(self, task: Task, review: CompanyWorkItemReview) -> list[dict[str, Any]]:
        before = task.model_dump(mode="json")
        patch: dict[str, Any] = {}
        actions: list[dict[str, Any]] = []

        normalized_priority = self._normalized_priority(task)
        if normalized_priority and _enum_value(task.priority) != normalized_priority:
            patch["priority"] = TaskPriority(normalized_priority)

        requires_approval_gate = self._requires_approval_gate(task)
        optional_later = self._is_optional_later(task)
        normalized_risk = "high" if requires_approval_gate else ("low" if optional_later else "medium")
        if (task.risk_level or "medium") != normalized_risk:
            patch["risk_level"] = normalized_risk

        owner = DOMAIN_OWNER.get(task.domain or "Operations", "ceo")
        if owner not in VALID_AGENT_ROLE_IDS:
            owner = "ceo"
        if not task.owner_agent or task.owner_agent in {"zero-company-operator", "chief_of_staff"}:
            patch["owner_agent"] = owner

        if task.due_at is None and normalized_priority in {"critical", "high"} and review.recommendation != "archive":
            days = 2 if normalized_priority == "critical" else 7
            patch["due_at"] = _now() + timedelta(days=days)

        if review.recommendation == "archive":
            patch["status"] = TaskStatus.ARCHIVED
            tags = list(task.tags or [])
            if "archived-by-dashboard-review" not in tags:
                tags.append("archived-by-dashboard-review")
            patch["tags"] = tags
            patch["blocked_reason"] = ""
        elif not _has_meaningful_description(task):
            patch["description"] = self._render_enriched_description(task, review)

        links = list(task.links or [])
        existing_urls = {str(link.get("url")) for link in links if isinstance(link, dict)}
        for source in review.source_links or []:
            url = str(source.get("url"))
            if url and url not in existing_urls:
                links.append(source)
                existing_urls.add(url)
        if links != (task.links or []):
            patch["links"] = links

        if requires_approval_gate and review.recommendation != "archive":
            gate_reason = (
                "Approval-gated external-action task. Zero may prepare the internal packet; "
                "Adam must approve or perform the filing, purchase, account change, legal/tax decision, "
                "client message, or public change."
            )
            if task.approval_state in {None, "none"}:
                patch["approval_state"] = "pending"
            if _enum_value(task.status) not in {TaskStatus.DONE.value, TaskStatus.BLOCKED.value}:
                patch["status"] = TaskStatus.BLOCKED
            if (task.blocked_reason or "") != gate_reason:
                patch["blocked_reason"] = gate_reason
        elif review.recommendation != "archive":
            if task.approval_state == "pending":
                patch["approval_state"] = "none"
            if task.approval_id:
                patch["approval_id"] = ""
            if _enum_value(task.status) in {TaskStatus.BACKLOG.value, TaskStatus.TODO.value, TaskStatus.BLOCKED.value}:
                patch["status"] = TaskStatus.ON_HOLD if optional_later else TaskStatus.IN_PROGRESS
            if task.blocked_reason:
                patch["blocked_reason"] = ""

        if not patch:
            return actions

        updated = await get_task_service().update_task(task.id, TaskUpdate(**patch))
        if not updated:
            return actions

        if "description" in patch:
            await get_company_work_item_service().record_event(
                task.id,
                "enriched",
                actor=review.reviewed_by,
                summary="Zero added concrete steps, acceptance criteria, automation notes, and source links.",
                before=before,
                after=updated.model_dump(mode="json"),
            )
            actions.append({"type": "enriched", "task_id": task.id, "title": task.title})

        if "priority" in patch:
            await get_company_work_item_service().record_event(
                task.id,
                "priority_changed",
                actor=review.reviewed_by,
                summary=f"Priority normalized to {normalized_priority} during dashboard review.",
                before={"priority": _enum_value(task.priority)},
                after={"priority": normalized_priority},
            )
            actions.append({"type": "priority_changed", "task_id": task.id, "title": task.title, "priority": normalized_priority})

        if patch.get("status") == TaskStatus.ARCHIVED:
            await get_company_work_item_service().record_event(
                task.id,
                "archived",
                actor=review.reviewed_by,
                summary="Archived because this setup task has rolled into the live Zero Company OS baseline.",
                before=before,
                after=updated.model_dump(mode="json"),
            )
            actions.append({"type": "archived", "task_id": task.id, "title": task.title})

        if "approval_state" in patch or "blocked_reason" in patch:
            approval_event_type = "approval_linked" if requires_approval_gate else "approval_cleared"
            await get_company_work_item_service().record_event(
                task.id,
                approval_event_type,
                actor=review.reviewed_by,
                summary=(
                    "Review confirmed this task must stay behind Adam approval before external execution."
                    if requires_approval_gate
                    else "Review cleared a stale approval block because this task is internal preparation."
                ),
                before={"approval_state": task.approval_state, "status": _enum_value(task.status)},
                after={"approval_state": updated.approval_state, "status": _enum_value(updated.status)},
            )
            actions.append({"type": approval_event_type, "task_id": task.id, "title": task.title})

        return actions

    async def _assign_internal_agent(self, task: Task, review: CompanyWorkItemReview) -> Optional[dict[str, Any]]:
        role_id = task.owner_agent or DOMAIN_OWNER.get(task.domain or "Operations", "zero-company-operator")
        if role_id in {"zero-company-operator", "chief_of_staff"} or role_id not in VALID_AGENT_ROLE_IDS:
            role_id = "ceo"
        description = (
            f"Review and support this ADA AI company launch work item. "
            f"Score: {review.score}/100. Recommendation: {review.recommendation}. "
            "Work only on internal analysis, drafts, checklists, and next-step preparation."
        )
        req = AgentTaskCreate(
            title=f"Review next actions: {task.title}",
            description=description,
            task_type=AgentTaskType.PLANNING,
            assigned_role=role_id,
            priority=2 if _enum_value(task.priority) in {"critical", "high"} else 3,
            project_id=COMPANY_PROJECT_ID,
            context={
                "zero_task_id": task.id,
                "work_packet": "company_dashboard_review",
                "autonomy": "internal_work",
                "external_actions_allowed": False,
                "approval_required": False,
                "review_score": review.score,
                "recommendation": review.recommendation,
                "action_steps": review.action_steps,
                "acceptance_criteria": review.acceptance_criteria,
                "guardrail": "No filings, purchases, account changes, client messages, public changes, or tax/legal decisions without Adam approval.",
            },
        )
        agent_task = await get_agent_company_service().create_task(req)
        await get_company_work_item_service().record_event(
            task.id,
            "agent_assigned",
            actor="zero-company-operator",
            summary=f"Assigned {role_id} to prepare an internal packet for this work item.",
            after={"agent_task_id": agent_task.id, "assigned_role": role_id, "review_score": review.score},
        )
        return {
            "type": "agent_assigned",
            "task_id": task.id,
            "title": task.title,
            "agent_task_id": agent_task.id,
            "assigned_role": role_id,
        }

    def _score(
        self,
        task: Task,
        *,
        missing: list[str],
        sources: list[dict[str, Any]],
        event_count: int,
        has_agent_task: bool,
        recommendation: str,
    ) -> int:
        if recommendation == "archive":
            return 100
        score = 0
        text = _text(task)
        if (task.domain or "") in {"Formation", "Finance", "Consulting", "Marketing", "Product", "Operations"} or HIGH_PRIORITY_RE.search(text):
            score += 18
        elif (task.domain or "") in {"Dashboard", "Agents", "Knowledge"}:
            score += 12
        else:
            score += 8

        if _has_meaningful_description(task):
            score += 20
        elif len((task.description or "").strip()) >= 60:
            score += 8

        score += 15 if "acceptance_criteria" not in missing else 5
        score += 5 if task.owner_agent else 0
        score += 5 if task.due_at else 0
        score += 15 if "priority_or_risk" not in missing else 7
        score += 10 if sources or (task.links or []) else 0
        score += 5 if event_count > 0 else 0
        score += 5 if has_agent_task else 0
        score -= min(15, len(missing) * 3)
        return max(0, min(100, int(score)))

    def _missing_info(self, task: Task, *, has_agent_task: bool, event_count: int) -> list[str]:
        missing: list[str] = []
        if not _has_meaningful_description(task):
            missing.append("actionable_description")
        if not task.owner_agent:
            missing.append("owner_agent")
        if task.due_at is None and _enum_value(task.priority) in {"critical", "high"}:
            missing.append("due_date")
        if not task.links:
            missing.append("source_links")
        if not has_agent_task:
            missing.append("agent_review")
        if event_count == 0:
            missing.append("audit_history")
        if _enum_value(task.priority) not in {"critical", "high"} and HIGH_PRIORITY_RE.search(_text(task)):
            missing.append("priority_or_risk")
        if "Acceptance" not in (task.description or ""):
            missing.append("acceptance_criteria")
        return missing

    def _normalized_priority(self, task: Task) -> Optional[str]:
        title_text = f"{task.title} {task.domain or ''}"
        if self._is_optional_later(task):
            return "low"
        if CRITICAL_RE.search(title_text):
            return "critical"
        if HIGH_PRIORITY_RE.search(title_text) or (task.domain or "") in {"Formation", "Finance", "Consulting", "Marketing", "Product"}:
            return "high"
        return "medium"

    def _requires_approval_gate(self, task: Task) -> bool:
        title_text = task.title or ""
        if INTERNAL_PREP_RE.search(title_text):
            return False
        return bool(APPROVAL_GATED_RE.search(f"{title_text} {task.domain or ''}"))

    def _is_optional_later(self, task: Task) -> bool:
        if re.search(r"\b(safety|liability)\b", task.title, re.I):
            return False
        if re.search(r"\b(robot .*decision|transfer decision|asset evidence|software.?ip)\b", task.title, re.I):
            return False
        return (task.domain or "") == "Robotics" or bool(OPTIONAL_LATER_RE.search(task.title))

    async def _retire_non_gated_approvals(self, tasks: list[Task], *, reviewed_by: str) -> list[dict[str, Any]]:
        gated_task_ids = {task.id for task in tasks if self._requires_approval_gate(task)}
        task_ids = {task.id for task in tasks}
        actions: list[dict[str, Any]] = []
        async with get_session() as session:
            rows = (
                await session.execute(
                    select(AgentApprovalModel)
                    .where(AgentApprovalModel.status == "pending")
                    .where(AgentApprovalModel.tool_name.in_(("company_operator_formation_gate", "company_operator_company_gate")))
                )
            ).scalars().all()
            for row in rows:
                task_id = str((row.arguments or {}).get("task_id") or "")
                if not task_id or task_id not in task_ids or task_id in gated_task_ids:
                    continue
                row.status = "expired"
                row.decided_by = reviewed_by
                row.decision_reason = "Retired by dashboard review: task is internal preparation, not an external completion gate."
                row.decided_at = _now()
                actions.append({"type": "approval_retired", "approval_id": row.id, "task_id": task_id})
        return actions

    def _should_archive(self, task: Task) -> bool:
        title = task.title.strip().lower()
        if _enum_value(task.status) == TaskStatus.DONE.value:
            return False
        return any(pattern in title for pattern in ARCHIVE_PATTERNS)

    def _template_for(self, task: Task) -> tuple[list[str], list[str], list[dict[str, str]], dict[str, Any], str]:
        title = task.title.lower()
        domain = task.domain or "Operations"

        if "sunbiz" in title or "name" in title:
            steps = [
                "Search Florida Sunbiz records for ADA AI, Adam Doherty Applied AI, and close variants.",
                "Search USPTO for ADA AI and Adam Doherty Applied AI before public brand investment.",
                "Record exact search terms, result URLs, conflicts, and a go/no-go recommendation.",
                "If clear enough for launch, keep the filing/name task approval-gated for Adam.",
            ]
            acceptance = [
                "Sunbiz result and USPTO search notes are attached or linked.",
                "ADA AI naming decision is recorded in the task audit trail.",
                "Any filing remains blocked until Adam approves the external action.",
            ]
            return steps, acceptance, _source("sunbiz_llc", "uspto_search"), self._automation("legal_compliance", "search-and-record only"), "Verify company/brand name availability before launch spend."

        if "llc" in title or "articles of organization" in title or "registered agent" in title or "operating agreement" in title or "ip assignment" in title or "duval" in title:
            steps = [
                "Prepare the Florida LLC filing packet and list every field Adam must decide.",
                "Confirm registered agent choice, principal address, mailing address, and public-record exposure.",
                "Draft internal operating-agreement and IP-assignment review notes for attorney/CPA review.",
                "Queue or keep approval before filing, signing, paying, or submitting anything externally.",
            ]
            acceptance = [
                "Formation packet has decisions, source links, and open questions.",
                "Attorney/CPA review need is visible when appropriate.",
                "No filing/signature/payment is marked done without Adam approval.",
            ]
            return steps, acceptance, _source("sba_startup", "sunbiz_llc", "fincen_boi"), self._automation("legal_compliance", "packet preparation only"), "Build the legal formation packet while keeping filing behind approval."

        if "ein" in title:
            steps = [
                "Wait until the LLC is approved by Florida before applying for the EIN.",
                "Use the IRS EIN tool directly; do not use paid EIN sites.",
                "Record responsible party, entity type, legal name, and confirmation letter storage location.",
                "After EIN confirmation, unlock banking, bookkeeping, and vendor-account setup tasks.",
            ]
            acceptance = [
                "LLC approval evidence is linked before EIN is attempted.",
                "IRS EIN confirmation is stored in the company document convention.",
                "Banking and bookkeeping tasks reference the EIN evidence location.",
            ]
            return steps, acceptance, _source("irs_ein", "sba_startup"), self._automation("finance_cpa", "readiness checklist only"), "Apply for EIN only after the state entity exists."

        if "bank" in title or "credit card" in title:
            steps = [
                "Collect LLC approval, EIN confirmation, operating agreement, ID, and business address evidence.",
                "Compare business checking and credit-card options without opening accounts automatically.",
                "Prepare an approval packet with recommended bank, fees, required documents, and risk notes.",
                "After Adam approves and opens accounts, record account metadata without storing secrets.",
            ]
            acceptance = [
                "Banking packet lists documents, candidates, fees, and recommendation.",
                "Approval is recorded before opening accounts.",
                "Bookkeeping and receipt inbox tasks are linked after account opening.",
            ]
            return steps, acceptance, _source("sba_startup"), self._automation("finance_cpa", "research packet only"), "Prepare banking setup without opening accounts automatically."

        if "email" in title or "domain" in title or "website" in title or "adamdoherty" in title:
            steps = [
                "Confirm adappliedai.com ownership and DNS provider.",
                "Choose email provider and create ADA AI aliases needed for launch operations.",
                "Prepare DNS records for HTTPS, email authentication, and waitlist/contact routing.",
                "Keep any public website or account change behind Adam approval.",
            ]
            acceptance = [
                "Domain, DNS, HTTPS, and email-authentication checklist is complete.",
                "Founder/contact/legal-disclaimer pages are tracked.",
                "Public changes are approved before publish.",
            ]
            return steps, acceptance, _source("sba_startup", "uspto_search"), self._automation("marketing_content", "draft and DNS checklist only"), "Turn the ADA AI domain into a launch-ready public surface."

        if "icp" in title or "service package" in title or "discovery" in title or "proposal" in title or "sow" in title or "crm" in title:
            steps = [
                "Define the first buyer profile and expensive operational pain points.",
                "Draft three applied-AI service packages with fixed scope, outcomes, timeline, and price range.",
                "Create discovery questions and a simple CRM tracker for 10 named prospects.",
                "Route proposals, outreach, and public claims through approval before sending.",
            ]
            acceptance = [
                "One-page offer, three packages, discovery questions, and prospect tracker exist.",
                "First proposal or SOW has internal review notes.",
                "Any client communication remains approval-gated.",
            ]
            return steps, acceptance, _source("sba_startup"), self._automation("consulting_revenue", "drafting and CRM prep only"), "Move applied-AI services from idea to first revenue motion."

        if "mvp" in title or "pricing" in title or "roadmap" in title or "product thesis" in title or "stripe" in title or "disclaimer" in title:
            steps = [
                "Position ADA as decision-support and trading-intelligence advisory software, not live execution.",
                "Write the MVP scope, waitlist promise, compliance assumptions, and explicit no-advice disclaimer needs.",
                "Separate product roadmap from applied-AI consulting revenue path.",
                "Keep live trading, payments, public financial claims, and disclaimers approval-gated.",
            ]
            acceptance = [
                "ADA product scope says decision-support only.",
                "Compliance/disclaimer review is tracked before public launch.",
                "No live order or financial-advice behavior is marked allowed.",
            ]
            return steps, acceptance, _source("sba_startup"), self._automation("product", "product planning only"), "Protect ADA product scope while turning it into launchable IP."

        if "bookkeeping" in title or "receipt" in title or "subscription" in title or "asset" in title or "cpa" in title or "monthly close" in title:
            steps = [
                "Define evidence fields: vendor, date, amount, category, account, receipt link, and business purpose.",
                "Create monthly close checklist covering reconciliation, receipts, subscriptions, and asset updates.",
                "Prepare CPA export format and open questions without making tax elections.",
                "Link banking/EIN/LLC documents once approved.",
            ]
            acceptance = [
                "Receipt inbox, category map, monthly close checklist, and CPA packet are defined.",
                "Tax-election questions are flagged for CPA review.",
                "Finance task has a clear evidence storage convention.",
            ]
            return steps, acceptance, _source("sba_startup"), self._automation("finance_cpa", "bookkeeping prep only"), "Make finance evidence clean enough for CPA and banking setup."

        if "robotics" in title or "3d" in title or "printer" in title or "consumables" in title or "safety" in title:
            steps = [
                "Inventory hardware, consumables, maintenance needs, and safety constraints.",
                "Separate optional lab upgrades from launch-critical ADA AI company work.",
                "Track product-liability review separately before any customer-facing physical deliverable.",
                "Require approval before hardware purchases.",
            ]
            acceptance = [
                "Lab inventory and maintenance notes exist.",
                "Optional purchases are on hold until launch-critical work is stable.",
                "Product-liability review is visible if robotics becomes customer-facing.",
            ]
            return steps, acceptance, _source("sba_startup"), self._automation("procurement_asset", "inventory only"), "Keep robotics useful without distracting from company launch."

        if "obsidian" in title or "decision log" in title or "weekly review" in title or "source links" in title or "summary convention" in title:
            steps = [
                "Make Zero the operational source of truth and Obsidian the narrative mirror.",
                "Record formation, finance, brand, and product decisions with date, source, owner, and approval status.",
                "Create weekly review note fields for blockers, decisions, revenue, product, and next actions.",
                "Link source documents back to Zero tasks and reviews.",
            ]
            acceptance = [
                "Decision log has owner/date/source/approval fields.",
                "Weekly review note mirrors Zero task status.",
                "Source links are visible from task drawers.",
            ]
            return steps, acceptance, _source("sba_startup"), self._automation("knowledge_second_brain", "documentation sync only"), "Keep company knowledge navigable while Zero remains canonical."

        steps = [
            f"Clarify the launch outcome for this {domain} work item.",
            "Break the task into concrete steps, evidence needed, and completion criteria.",
            "Assign the correct owner agent and due date.",
            "Keep external, financial, legal, public, account, and client actions behind approval.",
        ]
        acceptance = [
            "Task has clear steps and acceptance criteria.",
            "Owner, priority, risk, due date, and source links are filled.",
            "Audit trail shows the latest review or agent packet.",
        ]
        return steps, acceptance, _source("sba_startup"), self._automation(DOMAIN_OWNER.get(domain, "ceo"), "internal planning only"), "Fill the missing launch context so this task can move."

    @staticmethod
    def _automation(owner: str, scope: str) -> dict[str, Any]:
        return {
            "owner_agent": owner,
            "safe_to_automate": [
                "summarize",
                "draft",
                "classify",
                "prepare_checklist",
                "create_internal_task",
                "record_audit_event",
            ],
            "approval_required_for": [
                "filings",
                "purchases",
                "tax_elections",
                "legal_decisions",
                "client_messages",
                "public_site_changes",
                "account_or_credential_changes",
            ],
            "scope": scope,
        }

    def _render_enriched_description(self, task: Task, review: CompanyWorkItemReview) -> str:
        steps = "\n".join(f"{index}. {step}" for index, step in enumerate(review.action_steps, start=1))
        criteria = "\n".join(f"- {item}" for item in review.acceptance_criteria)
        links = "\n".join(f"- {source.get('label')}: {source.get('url')}" for source in review.source_links)
        automation = review.automation_plan or {}
        safe = ", ".join(automation.get("safe_to_automate", []))
        gated = ", ".join(automation.get("approval_required_for", []))
        return (
            f"Goal: {review.summary or task.title}\n\n"
            f"Steps:\n{steps}\n\n"
            f"Acceptance Criteria:\n{criteria}\n\n"
            f"Automation:\n"
            f"- Owner agent: {automation.get('owner_agent') or task.owner_agent or 'zero-company-operator'}\n"
            f"- Zero may: {safe or 'prepare internal notes'}\n"
            f"- Approval required for: {gated or 'external execution'}\n\n"
            f"Evidence / Sources:\n{links or '- Add source links or evidence before completion.'}\n\n"
            "Guardrail: Zero may prepare this internally, but Adam must approve filings, purchases, tax/legal decisions, "
            "client/public communications, and account or credential changes."
        )


@lru_cache()
def get_company_dashboard_review_service() -> CompanyDashboardReviewService:
    return CompanyDashboardReviewService()
