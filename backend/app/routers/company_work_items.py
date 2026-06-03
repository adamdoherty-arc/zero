"""Company work-item API.

This is the task-management surface for ADA AI LLC Company OS. It is
separate from `/api/company/tasks`, which is already used for agent-task records.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.infrastructure.auth import require_auth
from app.models.company_facts import CompletionOutput
from app.models.task import TaskCategory, TaskCreate, TaskPriority, TaskSource, TaskStatus, TaskUpdate
from app.services.company_completion_review_service import get_company_completion_review_service
from app.services.company_dashboard_review_service import get_company_dashboard_review_service
from app.services.company_progress_checkin_service import get_company_progress_checkin_service
from app.services.company_setup_progress_service import get_company_setup_progress_service
from app.services.company_walkthroughs import walkthrough_for
from app.services.company_work_item_service import get_company_work_item_service


router = APIRouter(
    prefix="/api/company/work-items",
    tags=["company-work-items"],
    dependencies=[Depends(require_auth)],
)


class ActorRequest(BaseModel):
    actor: str = Field(default="user", max_length=100)


class CompletionReviewRequest(BaseModel):
    actor: str = Field(default="dashboard", max_length=100)
    auto_create_followups: bool = True


class CompleteWorkItemRequest(BaseModel):
    actor: str = Field(default="user", max_length=100)
    completion_note: Optional[str] = None
    outputs: list[CompletionOutput] = Field(default_factory=list)


class TaskNoteRequest(BaseModel):
    actor: str = Field(default="user", max_length=100)
    note: str = Field(..., min_length=1, max_length=4000)


@router.get("")
async def list_work_items(
    status: Optional[str] = Query(default=None),
    domain: Optional[str] = Query(default=None),
    owner_agent: Optional[str] = Query(default=None),
    risk_level: Optional[str] = Query(default=None),
    approval_state: Optional[str] = Query(default=None),
    filter_name: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None),
    limit: int = Query(default=300, ge=1, le=1000),
):
    return await get_company_work_item_service().list_work_items(
        status=status,
        domain=domain,
        owner_agent=owner_agent,
        risk_level=risk_level,
        approval_state=approval_state,
        filter_name=filter_name,
        search=search,
        limit=limit,
    )


@router.get("/seed-status")
async def seed_status():
    return await get_company_work_item_service().seed_status()


@router.get("/setup-progress")
async def setup_progress():
    return await get_company_setup_progress_service().progress()


@router.get("/progress-checkin")
async def progress_checkin():
    return await get_company_progress_checkin_service().run_checkin(requested_by="dashboard")


@router.post("/progress-checkin/run")
async def run_progress_checkin(req: ActorRequest | None = None):
    actor = req.actor if req else "dashboard"
    return await get_company_progress_checkin_service().run_checkin(requested_by=actor)


@router.get("/reviews/summary")
async def review_summary():
    return await get_company_dashboard_review_service().summary()


@router.get("/reviews")
async def list_reviews(limit: int = Query(default=500, ge=1, le=1000)):
    return await get_company_dashboard_review_service().list_reviews(limit=limit)


@router.post("/reviews/run")
async def run_dashboard_review(req: ActorRequest | None = None):
    return await get_company_dashboard_review_service().run_dashboard_review(
        reviewed_by=(req.actor if req else "dashboard"),
        auto_apply=True,
    )


@router.post("/import-seed")
async def import_seed(req: ActorRequest | None = None):
    return await get_company_work_item_service().import_seed_backlog(actor=(req.actor if req else "user"))


CEO_SEED_SOURCE = "ceo-essentials-2026-06"


# IMPORTANT: static /seed-ceo* and /seed-tax-calendar paths are declared BEFORE
# the dynamic /{task_id} capture so FastAPI route ordering stays unambiguous.
@router.get("/seed-ceo/status")
async def seed_ceo_status():
    """Tell the Command Center whether the CEO-essentials backlog is seeded."""
    svc = get_company_work_item_service()
    existing = await svc.list_work_items(limit=1000)
    titles = {t.title.strip().lower() for t in existing}
    seed_titles = [item["title"] for item in _ceo_essentials_seed_tasks()]
    present = sum(1 for t in seed_titles if t.strip().lower() in titles)
    return {
        "has_ceo_tasks": present >= max(1, len(seed_titles) // 2),
        "present": present,
        "total": len(seed_titles),
        "source": CEO_SEED_SOURCE,
    }


@router.post("/seed-ceo")
async def seed_ceo(req: ActorRequest | None = None):
    """Idempotently seed the new-CEO essentials backlog (Finance / Tax / Home Office).

    Dedupes by title against existing company tasks, so re-running is safe.
    High-risk items (equipment purchase, tax-classification decision) auto-block
    into the approval lane via create_work_item.
    """
    actor = req.actor if req else "user"
    svc = get_company_work_item_service()
    existing = await svc.list_work_items(limit=1000)
    existing_titles = {t.title.strip().lower() for t in existing}

    created = []
    skipped = 0
    for index, item in enumerate(_ceo_essentials_seed_tasks()):
        title = item["title"]
        if title.strip().lower() in existing_titles:
            skipped += 1
            continue
        payload = TaskCreate(
            title=title,
            description=item["description"],
            category=TaskCategory.CHORE,
            priority=item.get("priority", TaskPriority.MEDIUM),
            source=TaskSource.MANUAL,
            source_reference=CEO_SEED_SOURCE,
            domain=item["domain"],
            owner_agent=item.get("owner_agent", "finance_cpa"),
            due_at=item.get("due_at"),
            risk_level=item.get("risk_level"),
            tags=item.get("tags", []),
            sort_order=item.get("sort_order", index + 1),
        )
        task = await svc.create_work_item(payload, actor=actor)
        initial_status = item.get("status")
        # Don't override the auto-block on high-risk tasks.
        if initial_status and task.status not in (initial_status, TaskStatus.BLOCKED):
            updated = await svc.update_work_item(task.id, TaskUpdate(status=initial_status), actor=actor)
            task = updated or task
        created.append(task)
        existing_titles.add(title.strip().lower())

    return {"created": len(created), "skipped": skipped, "tasks": created}


@router.post("/seed-tax-calendar")
async def seed_tax_calendar(req: ActorRequest | None = None):
    """Idempotently seed recurring tax/compliance deadlines as dated Tax tasks."""
    actor = req.actor if req else "user"
    return await get_company_work_item_service().seed_tax_calendar(actor=actor)


@router.get("/{task_id}")
async def get_work_item(task_id: str):
    task = await get_company_work_item_service().get_work_item(task_id)
    if not task:
        raise HTTPException(404, f"Company work item {task_id} not found")
    return task


@router.get("/{task_id}/events")
async def events(task_id: str, limit: int = Query(default=100, ge=1, le=500)):
    task = await get_company_work_item_service().get_work_item(task_id)
    if not task:
        raise HTTPException(404, f"Company work item {task_id} not found")
    return await get_company_work_item_service().events(task_id, limit=limit)


@router.get("/{task_id}/review")
async def review(task_id: str):
    task = await get_company_work_item_service().get_work_item(task_id)
    if not task:
        raise HTTPException(404, f"Company work item {task_id} not found")
    item = await get_company_dashboard_review_service().get_review(task_id)
    if not item:
        # Build a minimal review on the fly so the walkthrough is still surfaced
        walkthrough = walkthrough_for(task.title, task.description or "")
        if walkthrough is None:
            raise HTTPException(404, f"Company work item review {task_id} not found")
        return {
            "id": f"adhoc-{task.id}",
            "task_id": task.id,
            "score": 0,
            "recommendation": "keep",
            "summary": None,
            "missing_info": [],
            "action_steps": [],
            "acceptance_criteria": [],
            "automation_plan": {},
            "source_links": [],
            "walkthrough": walkthrough,
            "completion_review": None,
            "reviewed_by": "walkthrough-only",
            "operator_run_id": None,
            "created_at": task.created_at.isoformat() if task.created_at else None,
            "updated_at": None,
        }
    return item


@router.get("/{task_id}/walkthrough")
async def get_walkthrough(task_id: str):
    task = await get_company_work_item_service().get_work_item(task_id)
    if not task:
        raise HTTPException(404, f"Company work item {task_id} not found")
    walkthrough = walkthrough_for(task.title, task.description or "")
    if walkthrough is None:
        raise HTTPException(404, f"No curated walkthrough for task {task_id}")
    return walkthrough


@router.post("/{task_id}/completion-review")
async def run_completion_review(task_id: str, req: CompletionReviewRequest | None = None):
    request = req or CompletionReviewRequest()
    task = await get_company_work_item_service().get_work_item(task_id)
    if not task:
        raise HTTPException(404, f"Company work item {task_id} not found")
    return await get_company_completion_review_service().review_completion(
        task_id,
        actor=request.actor,
        auto_create_followups=request.auto_create_followups,
    )


@router.post("")
async def create_work_item(task: TaskCreate):
    return await get_company_work_item_service().create_work_item(task, actor="user")


@router.patch("/{task_id}")
async def update_work_item(task_id: str, updates: TaskUpdate):
    task = await get_company_work_item_service().update_work_item(task_id, updates, actor="user")
    if not task:
        raise HTTPException(404, f"Company work item {task_id} not found")
    return task


@router.post("/{task_id}/complete")
async def complete_work_item(task_id: str, req: CompleteWorkItemRequest | None = None):
    request = req or CompleteWorkItemRequest()
    task = await get_company_work_item_service().complete_work_item(
        task_id,
        actor=request.actor,
        completion_note=request.completion_note,
        outputs=[output.model_dump() for output in request.outputs],
    )
    if not task:
        raise HTTPException(404, f"Company work item {task_id} not found")
    return task


@router.delete("/{task_id}/notes/{event_id}")
async def delete_company_note(task_id: str, event_id: str):
    """Remove a note. Only event_type='note' rows are deletable — audit
    history (created/updated/blocked/approval_queued/etc.) is untouchable."""
    from app.db.models import CompanyTaskEventModel
    from app.infrastructure.database import get_session
    async with get_session() as session:
        row = await session.get(CompanyTaskEventModel, event_id)
        if not row or row.task_id != task_id or row.event_type != "note":
            raise HTTPException(404, "Note not found (or not a note)")
        await session.delete(row)
        await session.flush()
    return {"status": "deleted", "event_id": event_id}


@router.post("/{task_id}/notes")
async def add_note(task_id: str, req: TaskNoteRequest):
    """Append a free-text note. Same notes panel feeds personal + company boards.
    Stored as a company_task_events row with event_type='note'."""
    service = get_company_work_item_service()
    existing = await service.get_work_item(task_id)
    if not existing:
        raise HTTPException(404, f"Company work item {task_id} not found")
    event = await service.record_event(
        task_id, "note", actor=req.actor, summary=req.note.strip(),
    )
    return event


@router.post("/{task_id}/reopen")
async def reopen_work_item(task_id: str, req: ActorRequest | None = None):
    task = await get_company_work_item_service().reopen_work_item(task_id, actor=(req.actor if req else "user"))
    if not task:
        raise HTTPException(404, f"Company work item {task_id} not found")
    return task


@router.post("/{task_id}/duplicate")
async def duplicate_work_item(task_id: str, req: ActorRequest | None = None):
    task = await get_company_work_item_service().duplicate_work_item(task_id, actor=(req.actor if req else "user"))
    if not task:
        raise HTTPException(404, f"Company work item {task_id} not found")
    return task


@router.delete("/{task_id}")
async def delete_work_item(task_id: str):
    deleted = await get_company_work_item_service().delete_work_item(task_id, actor="user")
    if not deleted:
        raise HTTPException(404, f"Company work item {task_id} not found")
    return {"status": "deleted", "task_id": task_id}


# -----------------------------------------------------------------------------
# New-CEO essentials seed — the handful of tasks the user explicitly asked for
# (AI-spend accounting, business checking, home office, taxes, business loan)
# that aren't already on the company board. create_work_item applies risk
# auto-block, approval gating, and the audit trail. Living-doc tasks carry a
# "narrative" tag (their description is the evolving doc the user edits).
# -----------------------------------------------------------------------------


def _ceo_essentials_seed_tasks() -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)

    def due(days: int) -> datetime:
        return now + timedelta(days=days)

    return [
        # ---- (i) Business checking recorded + bookkeeping go-live ----------------
        {
            "title": "Record business-checking-opened and go live on the books",
            "description": (
                "**You opened ADA AI LLC business checking — capture it and switch the books on.**\n\n"
                "1. Complete this task with structured outputs so it lands in the company facts registry:\n"
                "   - `business_checking` — bank name + last 4 (mark **sensitive**), evidence = account-opening confirmation.\n"
                "2. Classify the first deposit as an **owner contribution** (not revenue) so the opening balance is clean.\n"
                "3. From here, every ADA-paid charge runs through the books (Finance tab → bookkeeper).\n\n"
                "See `docs/company/finance-setup-kit.md` Steps 2 & 4. Nothing here is tax advice — CPA reviews categories."
            ),
            "domain": "Finance",
            "priority": TaskPriority.HIGH,
            "owner_agent": "finance_cpa",
            "due_at": due(3),
            "tags": ["finance", "ceo-essentials", "bookkeeping"],
            "sort_order": 2,
        },
        {
            "title": "Stand up the monthly bookkeeping cadence (reconcile + categorize)",
            "description": (
                "**LIVING DOC — your repeatable monthly close checklist. Edit as the routine settles.**\n\n"
                "Each month:\n"
                "- [ ] Reconcile business checking against the ledger.\n"
                "- [ ] Categorize every transaction (AI/API, cloud, software, hardware, office, professional services).\n"
                "- [ ] Attach receipts; flag anything needing CPA review.\n"
                "- [ ] Run the recurring AI-spend draft (Finance tab → Record this month's expenses) and accept it.\n"
                "- [ ] Snapshot P&L + estimated tax.\n\n"
                "Cross-links the recurring-expense registry and the bookkeeper draft flow."
            ),
            "domain": "Finance",
            "priority": TaskPriority.MEDIUM,
            "owner_agent": "finance_cpa",
            "due_at": due(7),
            "tags": ["finance", "ceo-essentials", "narrative"],
            "sort_order": 3,
        },
        # ---- (ii) Monthly AI spend as a recurring expense ------------------------
        {
            "title": "Track monthly AI/subscription spend as a recurring business expense",
            "description": (
                "**LIVING DOC — registry of the AI tools you pay for monthly.** Mirror these into the "
                "Finance tab's recurring-expense registry (vendor, amount, billing day, paid-from).\n\n"
                "| Vendor | Monthly | Billing day | Paid from | Business purpose |\n"
                "|---|---|---|---|---|\n"
                "| Anthropic Claude Max | $? | ? | ? | primary dev + ops assistant |\n"
                "| OpenAI / ChatGPT | $? | ? | ? | research / drafting |\n"
                "| Cursor / other | $? | ? | ? | coding |\n\n"
                "Each active row emits a reviewable monthly expense draft under `Expenses:Software:AI`. "
                "Flag any subscriptions paid **personally before** ADA banking went live — CPA decides on reimbursement. "
                "This is the ongoing accrual process (the category itself is defined in the chart of accounts)."
            ),
            "domain": "Finance",
            "priority": TaskPriority.HIGH,
            "owner_agent": "finance_cpa",
            "due_at": due(5),
            "tags": ["finance", "ceo-essentials", "ai-spend", "narrative"],
            "sort_order": 4,
        },
        # ---- (iii) Home office deduction + purchases -----------------------------
        {
            "title": "Build the home-office purchase list (what to buy)",
            "description": (
                "**LIVING DOC — shopping list for the home office.** For each item: est. cost, business purpose, "
                "buy-from-ADA-account note, and deduction/depreciation flag (de minimis vs Section 179 — CPA confirms).\n\n"
                "- [ ] Desk\n- [ ] Ergonomic chair\n- [ ] Monitor + arm\n- [ ] Dock / hub\n- [ ] Lighting\n"
                "- [ ] Networking (router/switch)\n- [ ] Storage / shelving\n\n"
                "No purchases happen from this task — the buy step is a separate approval-gated task. "
                "See `docs/company/finance-setup-kit.md` Step 5/6."
            ),
            "domain": "Home Office",
            "priority": TaskPriority.MEDIUM,
            "owner_agent": "procurement_asset",
            "due_at": due(10),
            "tags": ["home-office", "ceo-essentials", "narrative"],
            "sort_order": 5,
        },
        {
            "title": "Purchase approved home-office equipment from the ADA account",
            "description": (
                "**Approval-gated.** After the purchase list is approved, buy the items **from the ADA business "
                "account/card**. For each: save the receipt, record placed-in-service date, and add to the asset "
                "register with business-use %. Pay from ADA only — keep it off personal cards once banking is live."
            ),
            "domain": "Home Office",
            "priority": TaskPriority.MEDIUM,
            "owner_agent": "procurement_asset",
            "due_at": due(21),
            "risk_level": "high",  # money leaving the account — gate it
            "tags": ["home-office", "ceo-essentials", "purchase"],
            "sort_order": 6,
        },
        {
            "title": "Finalize home-office deduction method with evidence",
            "description": (
                "Fill the home-office worksheet on the Finance tab (exclusive sq ft, total sq ft, % business use, "
                "rent/mortgage, utilities, internet + business %, insurance, repairs). The summary shows both the "
                "**simplified** ($5/sqft, $1,500 cap) and **actual** estimates — the CPA elects the method at tax "
                "time (IRS Pub 587). Confirm the space is used **regularly and exclusively** for business."
            ),
            "domain": "Home Office",
            "priority": TaskPriority.MEDIUM,
            "owner_agent": "finance_cpa",
            "due_at": due(30),
            "tags": ["home-office", "ceo-essentials"],
            "sort_order": 7,
        },
        # ---- (iv) Tax prep for next year -----------------------------------------
        {
            "title": "Set up the quarterly estimated-tax calendar (Form 1040-ES)",
            "description": (
                "**LIVING DOC — your estimated-tax plan.** Click **Seed tax calendar** on the Finance tab to create "
                "the dated deadlines (Q2/Q3/Q4 + next Q1, Duval LBTR renewal, annual return, FL Annual Report).\n\n"
                "Florida has **no state income tax**; federal estimates use Form 1040-ES (Apr 15 / Jun 15 / Sep 15 / "
                "Jan 15). The Finance tab shows your estimated quarterly payment (net × 22% ÷ 4 — a placeholder until "
                "the CPA confirms safe-harbor). No payment is made from here."
            ),
            "domain": "Tax",
            "priority": TaskPriority.HIGH,
            "owner_agent": "finance_cpa",
            "due_at": due(7),
            "tags": ["tax", "ceo-essentials", "narrative"],
            "sort_order": 8,
        },
        {
            "title": "Build the annual-return readiness checklist (Schedule C)",
            "description": (
                "**LIVING DOC — what the CPA needs at year end** for a single-member LLC (disregarded entity → "
                "Schedule C):\n\n"
                "- [ ] Year P&L + general ledger export\n- [ ] Home-office worksheet\n- [ ] Asset register + receipts\n"
                "- [ ] 1099s issued/received\n- [ ] Mileage log\n- [ ] AI/API + software totals\n"
                "- [ ] Owner contributions/draws\n\n"
                "Cross-links the CPA setup packet."
            ),
            "domain": "Tax",
            "priority": TaskPriority.MEDIUM,
            "owner_agent": "finance_cpa",
            "due_at": due(45),
            "tags": ["tax", "ceo-essentials", "narrative"],
            "sort_order": 9,
        },
        {
            "title": "Maintain the year-1 deduction tracker",
            "description": (
                "**LIVING DOC — running list of likely deductions** with doc status + CPA-review flag:\n\n"
                "AI/API spend · cloud/hosting · software tools · hardware/equipment · home office · professional "
                "services (CPA/attorney/registered agent) · startup & organizational costs · business mileage · "
                "dues & subscriptions. Ordinary, necessary, documented, CPA-reviewed (finance-setup-kit stance)."
            ),
            "domain": "Tax",
            "priority": TaskPriority.MEDIUM,
            "owner_agent": "finance_cpa",
            "due_at": due(14),
            "tags": ["tax", "ceo-essentials", "narrative"],
            "sort_order": 10,
        },
        {
            "title": "Confirm federal tax classification stance with CPA (no S-corp yet)",
            "description": (
                "**Approval-gated decision.** Document the default treatment — single-member LLC = disregarded "
                "entity for 2026, **no S-corp election** until durable profit justifies payroll + added filings "
                "(finance-setup-kit stance). No election is filed without Adam + CPA sign-off."
            ),
            "domain": "Tax",
            "priority": TaskPriority.MEDIUM,
            "owner_agent": "finance_cpa",
            "due_at": due(30),
            "risk_level": "high",  # tax position — gate it
            "tags": ["tax", "ceo-essentials"],
            "sort_order": 11,
        },
        # ---- (v) Business-loan research ------------------------------------------
        {
            "title": "Research business-financing options for ADA AI LLC",
            "description": (
                "**LIVING DOC — finance the company the right way.** Produce / maintain "
                "`docs/company/business-financing-options.md` comparing **SBA 7(a)**, **business line of credit**, "
                "**business credit card**, and **term loan** across APR/term, eligibility (time-in-business, revenue, "
                "credit), required docs, personal guarantee/lien, and best-fit-for-ADA. End with a recommended next "
                "step + open CPA/banker questions. **No application is filed** — research only."
            ),
            "domain": "Finance",
            "priority": TaskPriority.MEDIUM,
            "owner_agent": "finance_cpa",
            "due_at": due(14),
            "tags": ["finance", "ceo-essentials", "loan", "narrative"],
            "sort_order": 12,
        },
        {
            "title": "Assemble the lender-readiness document packet",
            "description": (
                "Checklist of what a lender will ask for, with where each lives:\n\n"
                "- [ ] EIN confirmation letter\n- [ ] Articles of Organization\n- [ ] Operating agreement\n"
                "- [ ] Business bank statements\n- [ ] P&L / books export\n- [ ] Personal financial statement\n"
                "- [ ] Use-of-funds summary\n\n"
                "Reuses formation + finance artifacts you already have."
            ),
            "domain": "Finance",
            "priority": TaskPriority.LOW,
            "owner_agent": "finance_cpa",
            "due_at": due(30),
            "tags": ["finance", "ceo-essentials", "loan"],
            "sort_order": 13,
        },
        # ---- CEO orientation anchor (pinned, top of board) -----------------------
        {
            "title": "CEO onboarding checklist — am I doing everything a new CEO needs?",
            "description": (
                "**PINNED — open this first. One page that links everything.**\n\n"
                "You're a new CEO; here's the whole path and where you stand. Work the Command Center top-to-bottom.\n\n"
                "**Money & books**\n"
                "- Business checking recorded + books live → *Record business-checking-opened*\n"
                "- Monthly AI spend as an expense → *Track monthly AI/subscription spend* (Finance tab registry)\n"
                "- Monthly close cadence → *Stand up the monthly bookkeeping cadence*\n\n"
                "**Taxes (for next year)**\n"
                "- Quarterly estimates calendar → *Set up the quarterly estimated-tax calendar* (Seed tax calendar)\n"
                "- Annual-return readiness → *Build the annual-return readiness checklist*\n"
                "- Deduction tracker → *Maintain the year-1 deduction tracker*\n"
                "- Tax classification → *Confirm federal tax classification stance with CPA*\n\n"
                "**Home office**\n"
                "- What to buy → *Build the home-office purchase list*\n"
                "- Deduction worksheet → *Finalize home-office deduction method*\n\n"
                "**Financing**\n"
                "- Options comparison → *Research business-financing options* (`business-financing-options.md`)\n"
                "- Lender packet → *Assemble the lender-readiness document packet*\n\n"
                "**Reference:** `docs/company/finance-setup-kit.md`, `docs/company/llc-compliance.md`. "
                "Everything money/legal/tax stays approval-gated and CPA/attorney-reviewed. This is not tax advice."
            ),
            "domain": "Operations",
            "priority": TaskPriority.HIGH,
            "owner_agent": "ceo",
            "status": TaskStatus.IN_PROGRESS,
            "tags": ["ceo-essentials", "narrative", "pinned"],
            "sort_order": 1,
        },
    ]
