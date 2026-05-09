"""
AI Company Service.
Manages agent roles, task execution, and the Kimi-plans-Gemma-executes pattern.
"""

import asyncio
import json
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from typing import List, Dict, Any, Optional

import structlog
from sqlalchemy import select, func as sql_func, update

from app.infrastructure.database import get_session
from app.infrastructure.llm_router import get_llm_router
from app.infrastructure.unified_llm_client import get_unified_llm_client, StructuredOutputError
from app.db.models import AgentRoleModel, AgentTaskModel
from app.models.agent_company import (
    AgentRole, AgentTask, AgentTaskCreate, AgentTaskStatus, AiCompanyStats,
)

logger = structlog.get_logger()


COMPANY_AGENT_PROMPT_POLICY = """
Company-agent execution policy:
1. Do safe internal work before asking Adam. Draft the checklist, packet, copy, evidence list, task update, or decision memo using the facts available.
2. Ask Adam at most one question, and only when the answer blocks the next safe internal step or an approval-gated external step. If the uncertainty does not block progress, choose the safest internal default and list it in assumptions_made.
3. Every question_for_adam item must be an object with: question, recommended_default, why_needed, blocks_progress, decision_type, answer_type, priority. The recommended_default should be the answer you would use if Adam says "use your judgment."
4. For legal, tax, finance, public/client communication, account, purchase, filing, DNS, email, credential, and live-trading actions: prepare the exact Adam action packet and approval_request. Do not claim the action was performed.
5. Make recommended_task_updates concrete. Use sections named Goal, Steps, Acceptance Criteria, Evidence/Links, Guardrail, and Adam Action when useful.
6. Self-improve the prompt run. Include quality_checks, assumptions_made, self_improvement_notes, and legion_prompt_feedback so the prompt evaluation bridge can grade and improve future agent prompts.
7. Use ADA AI LLC as the legal company fact. Do not mention old entity assumptions or live trading execution.
""".strip()


def _orm_to_role(row: AgentRoleModel) -> AgentRole:
    return AgentRole(
        id=row.id,
        name=row.name,
        description=row.description,
        capabilities=row.capabilities or [],
        system_prompt=row.system_prompt,
        llm_provider=row.llm_provider,
        llm_model=row.llm_model,
        llm_temperature=row.llm_temperature,
        execution_llm_provider=row.execution_llm_provider,
        execution_llm_model=row.execution_llm_model,
        delegation_rules=row.delegation_rules or {},
        is_active=row.is_active,
        created_at=row.created_at,
    )


def _orm_to_task(row: AgentTaskModel) -> AgentTask:
    return AgentTask(
        id=row.id,
        project_id=row.project_id,
        title=row.title,
        description=row.description,
        task_type=row.task_type,
        assigned_role=row.assigned_role or "ceo",
        status=row.status,
        priority=row.priority,
        dependencies=row.dependencies or [],
        context=row.context or {},
        result=row.result,
        parent_task_id=row.parent_task_id,
        cost_usd=row.cost_usd,
        error=row.error,
        lease_id=row.lease_id,
        lease_expires_at=row.lease_expires_at,
        attempt_count=row.attempt_count or 0,
        last_heartbeat_at=row.last_heartbeat_at,
        created_at=row.created_at,
        started_at=row.started_at,
        completed_at=row.completed_at,
    )


class AgentCompanyService:
    """Core AI Company engine: role management and task execution."""

    def __init__(self):
        self._llm = get_unified_llm_client()

    # ------------------------------------------------------------------
    # LLM routing helpers: DB override first, then central router
    # ------------------------------------------------------------------

    @staticmethod
    def _task_type_for(role: AgentRole, phase: str = "primary") -> str:
        """Resolve router task type for a role + phase.

        Researcher splits into plan/execute task types so the two-tier pattern
        (Kimi plans, cheap model executes) routes cleanly via router config.
        All other roles collapse to `agent_{role.id}`.
        """
        if role.id == "researcher":
            return "agent_researcher_execute" if phase == "execute" else "agent_researcher_plan"
        return f"agent_{role.id}"

    @classmethod
    def _llm_kwargs_for(cls, role: AgentRole, phase: str = "primary") -> Dict[str, Any]:
        """Build LLM call kwargs with DB override precedence.

        Precedence:
          1. DB row's llm_provider/llm_model (or execution_llm_* for execute phase)
             when non-NULL, passed as explicit `model=`.
          2. Router resolution via `task_type=`.
        """
        if phase == "execute" and role.execution_llm_provider and role.execution_llm_model:
            return {"model": f"{role.execution_llm_provider}/{role.execution_llm_model}"}
        if phase != "execute" and role.llm_provider and role.llm_model:
            return {"model": f"{role.llm_provider}/{role.llm_model}"}
        return {"task_type": cls._task_type_for(role, phase)}

    # ------------------------------------------------------------------
    # Roles CRUD
    # ------------------------------------------------------------------

    async def list_roles(self, active_only: bool = True) -> List[AgentRole]:
        async with get_session() as session:
            q = select(AgentRoleModel)
            if active_only:
                q = q.where(AgentRoleModel.is_active.is_(True))
            result = await session.execute(q)
            return [_orm_to_role(r) for r in result.scalars().all()]

    async def get_role(self, role_id: str) -> Optional[AgentRole]:
        async with get_session() as session:
            row = await session.get(AgentRoleModel, role_id)
            return _orm_to_role(row) if row else None

    # ------------------------------------------------------------------
    # Tasks CRUD
    # ------------------------------------------------------------------

    async def create_task(self, req: AgentTaskCreate) -> AgentTask:
        task_id = f"atask-{uuid.uuid4().hex[:12]}"
        async with get_session() as session:
            row = AgentTaskModel(
                id=task_id,
                project_id=req.project_id,
                title=req.title,
                description=req.description,
                task_type=req.task_type,
                assigned_role=req.assigned_role,
                priority=req.priority,
                context=req.context,
                parent_task_id=req.parent_task_id,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            logger.info("agent_task_created", task_id=task_id, role=req.assigned_role, type=req.task_type)
            return _orm_to_task(row)

    async def get_task(self, task_id: str) -> Optional[AgentTask]:
        async with get_session() as session:
            row = await session.get(AgentTaskModel, task_id)
            return _orm_to_task(row) if row else None

    async def list_tasks(
        self,
        status: Optional[str] = None,
        role: Optional[str] = None,
        task_type: Optional[str] = None,
        limit: int = 50,
    ) -> List[AgentTask]:
        async with get_session() as session:
            q = select(AgentTaskModel).order_by(AgentTaskModel.created_at.desc()).limit(limit)
            if status:
                q = q.where(AgentTaskModel.status == status)
            if role:
                q = q.where(AgentTaskModel.assigned_role == role)
            if task_type:
                q = q.where(AgentTaskModel.task_type == task_type)
            result = await session.execute(q)
            return [_orm_to_task(r) for r in result.scalars().all()]

    # ------------------------------------------------------------------
    # Task Execution: Kimi-plans-Gemma-executes
    # ------------------------------------------------------------------

    async def execute_task(self, task_id: str) -> AgentTask:
        """Execute a task using the assigned role's LLM configuration.

        Two-tier pattern:
        1. If role has execution_llm (e.g. Researcher): Kimi plans, Gemma executes
        2. If role has no execution_llm (e.g. CEO): direct Kimi call
        """
        async with get_session() as session:
            row = await session.get(AgentTaskModel, task_id)
            if not row:
                raise ValueError(f"Task {task_id} not found")
            if row.status not in ("pending", "failed"):
                raise ValueError(f"Task {task_id} is {row.status}, cannot execute")

            # Mark in progress
            now = datetime.now(timezone.utc)
            row.status = "in_progress"
            row.started_at = now
            row.last_heartbeat_at = now
            row.attempt_count = int(row.attempt_count or 0) + 1
            await session.commit()

        # Load role
        role = await self.get_role(row.assigned_role or "ceo")
        if not role:
            await self._fail_task(task_id, "Role not found")
            return await self.get_task(task_id)

        try:
            if role.execution_llm_model:
                # Two-tier: plan with primary LLM, execute with execution LLM
                result = await self._execute_two_tier(role, row)
            else:
                # Direct: single LLM call
                result = await self._execute_direct(role, row)

            # Update task with result
            async with get_session() as session:
                task_row = await session.get(AgentTaskModel, task_id)
                task_row.status = "completed"
                task_row.result = result
                task_row.error = None
                task_row.completed_at = datetime.now(timezone.utc)
                task_row.lease_id = None
                task_row.lease_expires_at = None
                task_row.last_heartbeat_at = datetime.now(timezone.utc)
                # Cost is tracked by unified LLM client in llm_usage table
                await session.commit()

            logger.info("agent_task_completed", task_id=task_id, role=role.id)
            return await self.get_task(task_id)

        except Exception as e:
            logger.error("agent_task_failed", task_id=task_id, error=str(e))
            if self._can_complete_company_internal_fallback(row):
                fallback = self._deterministic_company_result(role, row, str(e))
                await self._complete_task(task_id, fallback)
                logger.warning(
                    "agent_task_completed_with_company_fallback",
                    task_id=task_id,
                    role=role.id,
                    error=str(e)[:300],
                )
                return await self.get_task(task_id)
            await self._fail_task(task_id, str(e))
            return await self.get_task(task_id)

    async def _execute_direct(self, role: AgentRole, task: AgentTaskModel) -> Dict[str, Any]:
        """Direct execution: one LLM call routed via central router or DB override."""
        llm_kwargs = self._llm_kwargs_for(role, phase="primary")
        prompt = self._build_task_prompt(task)

        try:
            result = await self._llm.structured_chat(
                prompt=prompt,
                system=role.system_prompt,
                temperature=role.llm_temperature,
                max_tokens=4096,
                **llm_kwargs,
            )
            return result if isinstance(result, dict) else {"output": result}
        except StructuredOutputError:
            # Fallback to plain chat and wrap
            text = await self._llm.chat(
                prompt=prompt,
                system=role.system_prompt,
                temperature=role.llm_temperature,
                max_tokens=4096,
                **llm_kwargs,
            )
            return {"output": text}

    async def _execute_two_tier(self, role: AgentRole, task: AgentTaskModel) -> Dict[str, Any]:
        """Two-tier: premium model plans structured subtask, cheap model executes it.

        Researcher routes through `agent_researcher_plan` (plan phase) and
        `agent_researcher_execute` (execute phase) via the central router.
        DB overrides (llm_provider/llm_model, execution_llm_provider/execution_llm_model)
        take precedence when set.
        """
        plan_kwargs = self._llm_kwargs_for(role, phase="primary")
        exec_kwargs = self._llm_kwargs_for(role, phase="execute")

        # Step 1: Plan with primary tier
        plan_prompt = (
            f"You are planning a task for the {role.name}.\n\n"
            f"Task: {task.title}\n"
            f"Description: {task.description or 'N/A'}\n"
            f"Context: {json.dumps(task.context or {}, default=str)[:2000]}\n\n"
            "Create a structured execution plan. Return JSON with:\n"
            '{"instructions": "clear step-by-step instructions for executing this task", '
            '"output_schema": {"key": "description of expected output fields"}, '
            '"evaluation_criteria": ["criterion 1", "criterion 2"]}'
        )

        try:
            plan = await self._llm.structured_chat(
                prompt=plan_prompt,
                system=role.system_prompt,
                temperature=0.7,
                max_tokens=2048,
                **plan_kwargs,
            )
        except StructuredOutputError:
            # If planning fails, fall back to direct execution
            return await self._execute_direct(role, task)

        # Step 2: Execute with cheap tier using the structured plan
        exec_prompt = (
            f"Execute the following task precisely as instructed.\n\n"
            f"Task: {task.title}\n"
            f"Instructions: {plan.get('instructions', task.description or task.title)}\n"
            f"Context: {json.dumps(task.context or {}, default=str)[:2000]}\n\n"
            f"Expected output format: {json.dumps(plan.get('output_schema', {}))}\n\n"
            "Return your result as valid JSON."
        )

        try:
            result = await self._llm.structured_chat(
                prompt=exec_prompt,
                system=f"You are a {role.name}. Follow instructions exactly and return structured JSON.",
                temperature=role.llm_temperature,
                max_tokens=4096,
                **exec_kwargs,
            )
        except StructuredOutputError:
            # Exec tier failed; escalate to plan-tier model.
            logger.warning("agent_execute_tier_failed_escalating", task_id=task.id, role=role.id)
            result = await self._llm.structured_chat(
                prompt=exec_prompt,
                system=f"You are a {role.name}. Follow instructions exactly and return structured JSON.",
                temperature=role.llm_temperature,
                max_tokens=4096,
                **plan_kwargs,
            )

        return {
            "plan": plan,
            "execution_result": result if isinstance(result, dict) else {"output": result},
        }

    def _build_task_prompt(self, task: AgentTaskModel) -> str:
        """Build prompt from task fields."""
        canonical = {
            "company": "ADA AI LLC",
            "public_brand": "ADA AI",
            "agent_meaning": "ADA is Adam Doherty's Automated Decision Agent.",
            "llc_status": "Adam confirmed ADA AI LLC has been created.",
            "autonomy": "approval_staged_internal_work",
            "guardrails": [
                "Prepare drafts, packets, checklists, research, questions, and internal task updates.",
                "Do not file, purchase, open accounts, send client/public messages, make tax/legal decisions, or place live trades.",
                "Live trading remains decision-support only unless Adam explicitly approves an external execution step.",
            ],
            "official_sources": {
                "sba_startup_steps": "https://www.sba.gov/business-guide/10-steps-start-your-business",
                "irs_ein": "https://www.irs.gov/businesses/small-businesses-self-employed/get-an-employer-identification-number",
                "florida_sunbiz_llc": "https://dos.fl.gov/sunbiz/start-business/efile/fl-llc/",
                "uspto_trademark_search": "https://www.uspto.gov/trademarks/search",
                "fincen_boi": "https://www.fincen.gov/boi",
            },
        }
        parts = [
            "You are working inside Zero Company OS for ADA AI LLC.",
            f"Canonical facts: {json.dumps(canonical, default=str)}",
            COMPANY_AGENT_PROMPT_POLICY,
            f"Task: {task.title}",
        ]
        if task.description:
            parts.append(f"Description: {task.description}")
        if task.context:
            ctx_str = json.dumps(task.context, default=str)
            if len(ctx_str) > 3000:
                ctx_str = ctx_str[:3000] + "...(truncated)"
            parts.append(f"Context: {ctx_str}")
        parts.append(
            "Respond with valid JSON using these keys: "
            "summary, completed_internal_steps, questions_for_adam, approval_requests, "
            "evidence_links, recommended_task_updates, assumptions_made, quality_checks, "
            "self_improvement_notes, legion_prompt_feedback, confidence, stale_assumption_flags. "
            "questions_for_adam must be an array of zero or one objects. Do not ask generic confirmation questions. "
            "approval_requests must only describe approval-gated external follow-through; never claim you performed it. "
            "If you cannot use a live source, state the stale-assumption risk and prepare the safest internal packet anyway."
        )
        return "\n\n".join(parts)

    @staticmethod
    def _can_complete_company_internal_fallback(task: AgentTaskModel) -> bool:
        """Allow deterministic completion for safe Company OS internal packets.

        This keeps Zero's company agents useful overnight even if a local/remote
        model returns malformed JSON or the LLM router is temporarily unhealthy.
        It is intentionally limited to internal work packets and never applies
        to tasks that can spend money, file documents, contact clients, or make
        public/account changes.
        """
        context = task.context or {}
        if task.project_id != "company":
            return False
        if context.get("external_actions_allowed") is True:
            return False
        return context.get("autonomy") in {None, "internal_work", "write_local", "approval_staged"}

    @staticmethod
    def _role_work_packet(role_id: str, title: str) -> Dict[str, Any]:
        base_packets: Dict[str, Dict[str, Any]] = {
            "legal_compliance": {
                "summary": "Prepared an internal LLC/legal readiness packet for Adam review.",
                "deliverables": [
                    "Confirm legal name availability before filing.",
                    "Prepare registered agent decision notes.",
                    "Collect operating agreement and IP assignment templates for attorney review.",
                    "Queue approvals for any filing, signature, attorney engagement, or public legal change.",
                ],
                "checklist": [
                    "Record ADA AI LLC Sunbiz filing confirmation.",
                    "Choose registered agent option and record rationale.",
                    "Draft operating agreement review notes.",
                    "Draft IP assignment inventory covering code, domains, docs, and brand assets.",
                    "Add Duval LBTR and attorney consult tasks to Formation Sprint.",
                ],
                "approval_notes": [
                    "Zero may prepare packets only.",
                    "Adam must approve or perform Sunbiz filing, EIN, signatures, LBTR, and attorney engagement.",
                ],
            },
            "finance_cpa": {
                "summary": "Prepared a CPA readiness packet and finance evidence checklist.",
                "deliverables": [
                    "Initial bookkeeping category map.",
                    "Receipt and subscription evidence checklist.",
                    "Hardware asset evidence checklist with placed-in-service and business-use fields.",
                    "Open questions for CPA consult.",
                ],
                "checklist": [
                    "Create vendor/subscription registry.",
                    "Create hardware asset register for GPUs, computers, printers, robotics gear.",
                    "Capture home-office photos, square footage, and business-use notes.",
                    "Define monthly close checklist and CPA export format.",
                    "Queue approval before opening bank/card accounts or paying professionals.",
                ],
                "approval_notes": [
                    "Zero cannot make tax elections or represent CPA advice.",
                    "Adam/CPA must approve deductions, filings, accounts, and payments.",
                ],
            },
            "procurement_asset": {
                "summary": "Prepared banking, procurement, asset, and subscription setup checklist.",
                "deliverables": [
                    "Business account setup readiness list.",
                    "Subscription migration checklist.",
                    "Asset registry fields for warranty, serial, renewal, and business-use percentage.",
                    "Procurement approval policy for purchases and renewals.",
                ],
                "checklist": [
                    "List required vendors: email, bookkeeping, password vault, receipt inbox, cloud/dev tools.",
                    "Add renewal date and owner agent for every subscription.",
                    "Track purchase approval state before any spend.",
                    "Record serial numbers, invoices, warranty links, and placed-in-service dates.",
                    "Flag high-risk purchases for Adam approval.",
                ],
                "approval_notes": [
                    "Purchases, subscriptions, account openings, and vendor contracts require Adam approval.",
                ],
            },
            "consulting_revenue": {
                "summary": "Prepared consulting offer launch checklist and CRM starter path.",
                "deliverables": [
                    "ICP draft for AI adoption consulting.",
                    "Service package skeletons.",
                    "Discovery call questionnaire outline.",
                    "CRM follow-up task pattern.",
                ],
                "checklist": [
                    "Define first ICP and painful use cases.",
                    "Draft 2-3 fixed-scope service packages.",
                    "Create discovery questionnaire and proposal/SOW template tasks.",
                    "Add adamdoherty.com update plan.",
                    "Queue approval before sending outreach, proposals, or public website changes.",
                ],
                "approval_notes": [
                    "Client communications and public website changes require Adam approval.",
                ],
            },
            "knowledge_second_brain": {
                "summary": "Prepared company docs and second-brain sync checklist.",
                "deliverables": [
                    "Company docs context map.",
                    "Decision-log update convention.",
                    "Weekly review note outline.",
                    "Stale-doc warning checklist.",
                ],
                "checklist": [
                    "Link company docs under docs/company to related UI routes.",
                    "Mirror summaries into Obsidian weekly review notes.",
                    "Record formation decisions with date, source, owner, and approval state.",
                    "Keep Zero database canonical for tasks and approvals.",
                ],
                "approval_notes": [
                    "Obsidian remains a narrative mirror; Zero remains the operational source of truth.",
                ],
            },
        }
        return base_packets.get(
            role_id,
            {
                "summary": f"Prepared an internal work packet for {title}.",
                "deliverables": [
                    "Task summary.",
                    "Current assumptions.",
                    "Ready/blocked next-action list.",
                    "Approval notes for risky follow-through.",
                ],
                "checklist": [
                    "Review linked company docs.",
                    "Separate safe internal work from approval-gated external actions.",
                    "Create or update related company work items.",
                    "Report blockers and next steps to Zero Operator.",
                ],
                "approval_notes": [
                    "External, legal, financial, client, public, and account-changing actions require approval.",
                ],
            },
        )

    def _deterministic_company_result(self, role: AgentRole, task: AgentTaskModel, error: str) -> Dict[str, Any]:
        context = task.context or {}
        packet = self._role_work_packet(role.id, task.title)
        return {
            "summary": packet["summary"],
            "status": "completed_with_deterministic_fallback",
            "source": "deterministic_company_agent_fallback",
            "role": role.id,
            "role_name": role.name,
            "task_id": task.id,
            "title": task.title,
            "work_packet": context.get("work_packet", "company_internal_work"),
            "autonomy": context.get("autonomy", "internal_work"),
            "deliverables": packet["deliverables"],
            "checklist": packet["checklist"],
            "next_actions": [
                "Review this packet in the Company Operator dashboard.",
                "Convert any missing checklist item into an editable company task.",
                "Queue approval for anything involving money, filings, legal/tax decisions, clients, public sites, or account changes.",
            ],
            "questions_for_adam": [],
            "approval_notes": packet["approval_notes"],
            "assumptions_made": [
                "No external action was taken.",
                "The fallback produced a safe internal packet because the LLM path failed.",
            ],
            "quality_checks": [
                "Question budget respected.",
                "External actions remain approval-gated.",
                "ADA AI LLC canonical company fact preserved.",
            ],
            "self_improvement_notes": [
                "If this fallback fires often, improve the role prompt or structured output schema for this packet type.",
            ],
            "legion_prompt_feedback": {
                "prompt_issue": "LLM execution failed or returned malformed output.",
                "recommended_mutation": "Make company-agent JSON schema stricter and require concrete internal deliverables before questions.",
            },
            "linked_company_task_id": context.get("zero_task_id"),
            "docs_context": [
                "docs/company/INDEX.md",
                "docs/company/task-management-system.md",
                "docs/company/zero-company-operator.md",
                "docs/company/llc-compliance.md",
            ],
            "guardrails": {
                "external_actions_allowed": False,
                "requires_adam_approval_for_high_risk_actions": True,
            },
            "llm_error": error[:800],
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    async def _complete_task(self, task_id: str, result: Dict[str, Any]):
        async with get_session() as session:
            row = await session.get(AgentTaskModel, task_id)
            if row:
                row.status = "completed"
                row.result = result
                row.error = None
                row.completed_at = datetime.now(timezone.utc)
                row.lease_id = None
                row.lease_expires_at = None
                row.last_heartbeat_at = datetime.now(timezone.utc)
                await session.commit()

    async def _fail_task(self, task_id: str, error: str):
        async with get_session() as session:
            row = await session.get(AgentTaskModel, task_id)
            if row:
                row.status = "failed"
                row.error = error[:2000]
                row.completed_at = datetime.now(timezone.utc)
                row.lease_id = None
                row.lease_expires_at = None
                row.last_heartbeat_at = datetime.now(timezone.utc)
                await session.commit()

    # ------------------------------------------------------------------
    # Delegation
    # ------------------------------------------------------------------

    async def delegate_task(
        self,
        parent_task_id: str,
        title: str,
        description: str,
        target_role: str,
        task_type: str = "research",
        context: Optional[Dict[str, Any]] = None,
    ) -> AgentTask:
        """Create a subtask delegated from a parent task to another role."""
        return await self.create_task(AgentTaskCreate(
            title=title,
            description=description,
            task_type=task_type,
            assigned_role=target_role,
            context=context or {},
            parent_task_id=parent_task_id,
        ))

    # ------------------------------------------------------------------
    # CEO: Plan and Delegate Complex Task
    # ------------------------------------------------------------------

    async def ceo_plan_and_delegate(self, task_description: str, context: Optional[Dict] = None) -> Dict[str, Any]:
        """CEO decomposes a complex task and delegates subtasks to specialists.

        Returns the parent task and list of created subtasks.
        """
        # Create parent CEO task
        parent = await self.create_task(AgentTaskCreate(
            title=f"Plan: {task_description[:200]}",
            description=task_description,
            task_type="planning",
            assigned_role="ceo",
            context=context or {},
        ))

        # CEO plans decomposition
        plan_prompt = (
            f"Decompose this task into 2-5 specialist subtasks.\n\n"
            f"Task: {task_description}\n"
            f"Context: {json.dumps(context or {}, default=str)[:2000]}\n\n"
            "Available roles:\n"
            "- researcher: web research, multi-source synthesis, trend analysis\n"
            "- analyst: data analysis, scoring, market sizing, financial projections\n"
            "- engineer: implementation, code generation, prototyping\n"
            "- validator: assumption testing, feasibility checks, risk assessment\n\n"
            "Return JSON array of subtasks:\n"
            '[{"title": "...", "description": "...", "assigned_role": "researcher|analyst|engineer|validator", '
            '"task_type": "research|analysis|validation|implementation|ideation"}]'
        )

        ceo_role = await self.get_role("ceo")
        try:
            subtask_plans = await self._llm.structured_chat(
                prompt=plan_prompt,
                system=ceo_role.system_prompt if ceo_role else "",
                task_type="planning",
                temperature=0.7,
                max_tokens=2048,
            )
        except StructuredOutputError as e:
            await self._fail_task(parent.id, f"CEO planning failed: {e}")
            return {"parent_task": await self.get_task(parent.id), "subtasks": []}

        # Create subtasks
        if isinstance(subtask_plans, dict):
            subtask_plans = subtask_plans.get("subtasks", [subtask_plans])
        if not isinstance(subtask_plans, list):
            subtask_plans = [subtask_plans]

        subtasks = []
        for plan in subtask_plans[:5]:  # Max 5 subtasks
            if not isinstance(plan, dict):
                continue
            st = await self.delegate_task(
                parent_task_id=parent.id,
                title=plan.get("title", "Subtask"),
                description=plan.get("description", ""),
                target_role=plan.get("assigned_role", "researcher"),
                task_type=plan.get("task_type", "research"),
                context=context,
            )
            subtasks.append(st)

        # Mark parent as delegated
        async with get_session() as session:
            row = await session.get(AgentTaskModel, parent.id)
            row.status = "delegated"
            row.result = {
                "plan": subtask_plans,
                "subtask_ids": [s.id for s in subtasks],
            }
            await session.commit()

        logger.info(
            "ceo_delegated_task",
            parent_id=parent.id,
            subtask_count=len(subtasks),
        )
        return {"parent_task": await self.get_task(parent.id), "subtasks": subtasks}

    # ------------------------------------------------------------------
    # Execute All Subtasks for a Parent
    # ------------------------------------------------------------------

    async def execute_subtasks(self, parent_task_id: str) -> List[AgentTask]:
        """Execute all pending subtasks for a parent task."""
        subtasks = await self.list_tasks(status="pending")
        subtasks = [t for t in subtasks if t.parent_task_id == parent_task_id]

        results = []
        for task in subtasks:
            result = await self.execute_task(task.id)
            results.append(result)

        return results

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    async def get_stats(self) -> AiCompanyStats:
        async with get_session() as session:
            # Task counts
            task_result = await session.execute(
                select(AgentTaskModel.status, sql_func.count())
                .group_by(AgentTaskModel.status)
            )
            tasks_by_status = {row[0]: row[1] for row in task_result.all()}

            role_result = await session.execute(
                select(AgentTaskModel.assigned_role, sql_func.count())
                .group_by(AgentTaskModel.assigned_role)
            )
            tasks_by_role = {row[0] or "unassigned": row[1] for row in role_result.all()}

            cost_result = await session.execute(
                select(AgentTaskModel.assigned_role, sql_func.sum(AgentTaskModel.cost_usd))
                .group_by(AgentTaskModel.assigned_role)
            )
            cost_by_role = {row[0] or "unassigned": float(row[1] or 0) for row in cost_result.all()}

            # Experiment counts
            from app.db.models import ExperimentModel
            exp_result = await session.execute(
                select(ExperimentModel.status, sql_func.count())
                .group_by(ExperimentModel.status)
            )
            experiments_by_status = {row[0]: row[1] for row in exp_result.all()}

            # Council decisions count
            from app.db.models import CouncilDecisionModel
            council_count = await session.execute(
                select(sql_func.count()).select_from(CouncilDecisionModel)
            )

            # Research reports count
            from app.db.models import DeepResearchReportModel
            research_count = await session.execute(
                select(sql_func.count()).select_from(DeepResearchReportModel)
            )

            return AiCompanyStats(
                total_tasks=sum(tasks_by_status.values()),
                tasks_by_status=tasks_by_status,
                tasks_by_role=tasks_by_role,
                total_experiments=sum(experiments_by_status.values()),
                experiments_by_status=experiments_by_status,
                total_council_decisions=council_count.scalar() or 0,
                total_research_reports=research_count.scalar() or 0,
                total_cost_usd=sum(cost_by_role.values()),
                cost_by_role=cost_by_role,
            )


@lru_cache()
def get_agent_company_service() -> AgentCompanyService:
    return AgentCompanyService()
