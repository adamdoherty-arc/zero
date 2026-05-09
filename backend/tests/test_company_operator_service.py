from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.models.task import Task, TaskCategory, TaskCreate, TaskPriority, TaskSource, TaskStatus, TaskUpdate
from app.services import company_work_item_service as cwis
from app.services.company_operator_service import CompanyOperatorService


def _task(**overrides) -> Task:
    base = {
        "id": "task-1",
        "project_id": "company",
        "title": "Draft internal checklist",
        "description": "",
        "status": TaskStatus.TODO,
        "category": TaskCategory.CHORE,
        "priority": TaskPriority.HIGH,
        "source": TaskSource.MANUAL,
        "created_at": datetime.now(timezone.utc),
    }
    base.update(overrides)
    return Task(**base)


class _FakeTaskService:
    def __init__(self, task: Task, tasks: list[Task] | None = None):
        self.task = task
        self.tasks = tasks or [task]
        self.created: list[TaskCreate] = []
        self.updates: list[TaskUpdate] = []

    async def create_task(self, data: TaskCreate) -> Task:
        self.created.append(data)
        self.task = _task(
            id="created-task",
            project_id=data.project_id,
            title=data.title,
            description=data.description,
            category=data.category,
            priority=data.priority,
            source=data.source,
            source_reference=data.source_reference,
            blocked_reason=data.blocked_reason,
            domain=data.domain,
            owner_agent=data.owner_agent,
            risk_level=data.risk_level,
            approval_state=data.approval_state,
            approval_id=data.approval_id,
            tags=data.tags or [],
            links=data.links or [],
            sort_order=data.sort_order,
            estimate_points=data.estimate_points,
            parent_task_id=data.parent_task_id,
        )
        self.tasks.append(self.task)
        return self.task

    async def list_tasks(self, **kwargs) -> list[Task]:
        return self.tasks

    async def get_task(self, task_id: str) -> Task | None:
        for task in self.tasks:
            if task.id == task_id:
                return task
        return None

    async def update_task(self, task_id: str, updates: TaskUpdate) -> Task | None:
        for index, task in enumerate(self.tasks):
            if task.id == task_id:
                patch = updates.model_dump(exclude_none=True)
                updated = task.model_copy(update=patch)
                self.tasks[index] = updated
                if self.task.id == task_id:
                    self.task = updated
                self.updates.append(updates)
                return updated
        else:
            return None


class _FakeApprovalQueue:
    def __init__(self):
        self.requests: list[dict] = []
        self.pending: list[SimpleNamespace] = []

    async def list(self, *, status: str | None = None, limit: int = 50):
        return [item for item in self.pending if status is None or item.status == status]

    async def request(self, **kwargs):
        self.requests.append(kwargs)
        return SimpleNamespace(id="ap-test", status="pending", **kwargs)


class _FakeCompanyWorkItemService:
    def __init__(self):
        self.events: list[dict] = []

    async def record_event(self, task_id: str, event_type: str, **kwargs):
        event = {"task_id": task_id, "event_type": event_type, **kwargs}
        self.events.append(event)
        return SimpleNamespace(id="event-test", **event)


async def _noop_record_event(self, task_id: str, event_type: str, **kwargs):
    return SimpleNamespace(
        id="event-test",
        task_id=task_id,
        event_type=event_type,
        actor=kwargs.get("actor", "test"),
        summary=kwargs.get("summary"),
        before=kwargs.get("before") or {},
        after=kwargs.get("after") or {},
        created_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_high_risk_task_cannot_be_marked_done_without_approval(monkeypatch):
    task_service = _FakeTaskService(
        _task(title="File Florida LLC on Sunbiz", description="Complete Articles of Organization.")
    )
    approval_queue = _FakeApprovalQueue()
    monkeypatch.setattr(cwis, "get_task_service", lambda: task_service)
    monkeypatch.setattr(cwis, "get_approval_queue", lambda: approval_queue)
    monkeypatch.setattr(cwis.CompanyWorkItemService, "record_event", _noop_record_event)

    result = await CompanyOperatorService().update_company_task(
        "task-1",
        TaskUpdate(status=TaskStatus.DONE),
    )

    assert result is not None
    assert result.status == TaskStatus.BLOCKED
    assert "approval-gated" in (result.blocked_reason or "").lower()
    assert approval_queue.requests
    assert approval_queue.requests[0]["tool_name"] == "company_work_item_completion_gate"


@pytest.mark.asyncio
async def test_high_risk_created_task_starts_blocked(monkeypatch):
    task_service = _FakeTaskService(_task())
    approval_queue = _FakeApprovalQueue()
    monkeypatch.setattr(cwis, "get_task_service", lambda: task_service)
    monkeypatch.setattr(cwis, "get_approval_queue", lambda: approval_queue)
    monkeypatch.setattr(cwis.CompanyWorkItemService, "record_event", _noop_record_event)

    result = await CompanyOperatorService().create_company_task(
        TaskCreate(
            title="Open LLC business bank account",
            description="Use the EIN and LLC documents to create the account.",
            category=TaskCategory.CHORE,
            priority=TaskPriority.HIGH,
        )
    )

    assert result.status == TaskStatus.BLOCKED
    assert result.project_id == "company"
    assert "approval-gated" in (result.blocked_reason or "").lower()
    assert approval_queue.requests == []


@pytest.mark.asyncio
async def test_low_risk_task_can_be_marked_done(monkeypatch):
    task_service = _FakeTaskService(_task())
    approval_queue = _FakeApprovalQueue()
    monkeypatch.setattr(cwis, "get_task_service", lambda: task_service)
    monkeypatch.setattr(cwis, "get_approval_queue", lambda: approval_queue)
    monkeypatch.setattr(cwis.CompanyWorkItemService, "record_event", _noop_record_event)

    result = await CompanyOperatorService().update_company_task(
        "task-1",
        TaskUpdate(status=TaskStatus.DONE),
    )

    assert result is not None
    assert result.status == TaskStatus.DONE
    assert approval_queue.requests == []


@pytest.mark.asyncio
async def test_dashboard_review_tick_uses_lightweight_snapshot(monkeypatch):
    from app.services import company_operator_service as cos

    svc = CompanyOperatorService()
    snapshot_calls: list[bool] = []
    prompt_calls = 0
    execute_calls = 0

    class _FakeDashboardReview:
        async def run_dashboard_review(self, **kwargs):
            return {"actions": [{"type": "reviewed"}]}

    async def fake_get_config():
        return {"paused": False}

    async def fake_roles(actions=None):
        return None

    async def fake_queue(config):
        return [{"type": "approval_checked"}]

    async def fake_recover(config, *, operator_run_id=None):
        return []

    async def fake_execute(config):
        nonlocal execute_calls
        execute_calls += 1
        return []

    async def fake_snapshot(*, include_legion: bool, tolerate_errors: bool = False):
        snapshot_calls.append(include_legion)
        return {
            "generated_at": "2026-05-05T00:00:00+00:00",
            "counts": {"tasks_total": 1, "tasks_blocked": 0, "approvals_pending": 0},
            "formation": {"percent": 100, "ready": 0, "blocked": 0},
            "next_tasks": [],
            "approvals": [],
            "blocked_tasks": [],
            "subagents": [],
            "prompt_lab": {},
            "scheduler": [],
            "legion": {"status": "not_checked"},
        }

    async def fake_record_prompt(*args, **kwargs):
        nonlocal prompt_calls
        prompt_calls += 1
        return "prompt-run"

    async def fake_save(**kwargs):
        return {
            "status": kwargs["status"],
            "summary": kwargs["summary"],
            "report": kwargs["report"],
            "actions": kwargs["actions"],
            "errors": kwargs["errors"],
        }

    monkeypatch.setattr(cos, "get_company_dashboard_review_service", lambda: _FakeDashboardReview())
    monkeypatch.setattr(svc, "get_config", fake_get_config)
    monkeypatch.setattr(svc, "_ensure_company_roles", fake_roles)
    monkeypatch.setattr(svc, "_recover_stale_agent_tasks", fake_recover)
    monkeypatch.setattr(svc, "_queue_company_approvals", fake_queue)
    monkeypatch.setattr(svc, "_execute_safe_agent_tasks", fake_execute)
    monkeypatch.setattr(svc, "_snapshot", fake_snapshot)
    monkeypatch.setattr(svc, "_record_operator_prompt_run", fake_record_prompt)
    monkeypatch.setattr(svc, "_save_run", fake_save)

    result = await svc.run_tick(run_type="dashboard_review", requested_by="test", force=True)

    assert result["status"] == "completed"
    assert snapshot_calls == [False]
    assert prompt_calls == 0
    assert execute_calls == 0
    assert result["report"]["prompt_recording"] == "skipped_for_fast_dashboard_review"


@pytest.mark.asyncio
async def test_agent_work_tick_executes_bounded_safe_agent_work(monkeypatch):
    svc = CompanyOperatorService()
    execute_calls = 0

    async def fake_get_config():
        return {"paused": False, "max_agent_executions_per_tick": 5}

    async def fake_roles(actions=None):
        return None

    async def fake_reconcile(config, requested_by="test"):
        return [{"type": "fact_checked"}]

    async def fake_queue(config):
        return [{"type": "approval_checked"}]

    async def fake_recover(config, *, operator_run_id=None):
        return []

    async def fake_triage(**kwargs):
        return {
            "reviewed": 0,
            "highlighted": 0,
            "dismissed": 0,
            "top_questions": [],
            "summary": "No questions needed triage.",
        }

    async def fake_execute(config, *, operator_run_id=None):
        nonlocal execute_calls
        execute_calls += 1
        assert operator_run_id
        assert config["max_agent_executions_per_tick"] == 5
        return [{"type": "agent_task_executed", "agent_task_id": "agt-1"}]

    async def fake_snapshot(*, include_legion: bool, tolerate_errors: bool = False):
        assert include_legion is False
        return {
            "generated_at": "2026-05-05T00:00:00+00:00",
            "counts": {
                "tasks_total": 1,
                "tasks_blocked": 0,
                "approvals_pending": 0,
                "questions_open": 1,
                "agent_tasks_running": 0,
                "agent_tasks_queued": 1,
            },
            "formation": {"percent": 100, "ready": 0, "blocked": 0},
            "next_tasks": [],
            "approvals": [],
            "questions": [{"question": "Need Adam input?"}],
            "blocked_tasks": [],
            "subagents": [],
            "prompt_lab": {},
            "scheduler": [],
            "legion": {"status": "not_checked"},
        }

    async def fake_record_prompt(*args, **kwargs):
        return "prompt-run"

    async def fake_save(**kwargs):
        return {
            "status": kwargs["status"],
            "summary": kwargs["summary"],
            "report": kwargs["report"],
            "actions": kwargs["actions"],
            "errors": kwargs["errors"],
        }

    monkeypatch.setattr(svc, "get_config", fake_get_config)
    monkeypatch.setattr(svc, "_ensure_company_roles", fake_roles)
    monkeypatch.setattr(svc, "_recover_stale_agent_tasks", fake_recover)
    monkeypatch.setattr(svc, "_reconcile_company_facts", fake_reconcile)
    monkeypatch.setattr(svc, "_queue_company_approvals", fake_queue)
    monkeypatch.setattr(svc, "triage_questions", fake_triage)
    monkeypatch.setattr(svc, "_execute_safe_agent_tasks", fake_execute)
    monkeypatch.setattr(svc, "_snapshot", fake_snapshot)
    monkeypatch.setattr(svc, "_record_operator_prompt_run", fake_record_prompt)
    monkeypatch.setattr(svc, "_save_run", fake_save)

    result = await svc.run_tick(run_type="agent_work", requested_by="scheduler", force=True)

    assert result["status"] == "completed"
    assert execute_calls == 1
    assert [action["type"] for action in result["actions"]] == [
        "fact_checked",
        "approval_checked",
        "agent_task_executed",
    ]
    assert result["report"]["question_queue"] == [{"question": "Need Adam input?"}]


@pytest.mark.asyncio
async def test_monitor_tick_is_heartbeat_only(monkeypatch):
    svc = CompanyOperatorService()
    execute_calls = 0

    async def fake_get_config():
        return {"paused": False}

    async def fake_roles(actions=None):
        assert actions is None
        return None

    async def fake_execute(config, *, operator_run_id=None):
        nonlocal execute_calls
        execute_calls += 1
        return []

    async def fake_snapshot(*, include_legion: bool, tolerate_errors: bool = False):
        return {
            "generated_at": "2026-05-05T00:00:00+00:00",
            "counts": {"tasks_total": 0, "tasks_blocked": 0, "approvals_pending": 0},
            "formation": {"percent": 0, "ready": 0, "blocked": 0},
            "next_tasks": [],
            "approvals": [],
            "questions": [],
            "blocked_tasks": [],
            "subagents": [],
            "prompt_lab": {},
            "scheduler": [],
            "legion": {"status": "not_checked"},
        }

    async def fake_record_prompt(*args, **kwargs):
        return "prompt-run"

    async def fake_save(**kwargs):
        return {"status": kwargs["status"], "actions": kwargs["actions"], "report": kwargs["report"]}

    monkeypatch.setattr(svc, "get_config", fake_get_config)
    monkeypatch.setattr(svc, "_ensure_company_roles", fake_roles)
    monkeypatch.setattr(svc, "_execute_safe_agent_tasks", fake_execute)
    monkeypatch.setattr(svc, "_snapshot", fake_snapshot)
    monkeypatch.setattr(svc, "_record_operator_prompt_run", fake_record_prompt)
    monkeypatch.setattr(svc, "_save_run", fake_save)

    result = await svc.run_tick(run_type="monitor", requested_by="scheduler")

    assert result["status"] == "completed"
    assert execute_calls == 0
    assert result["actions"] == []


def test_agent_output_stale_flags_and_question_extraction():
    svc = CompanyOperatorService()

    flags = svc._stale_agent_output_flags(
        {
            "summary": "If the LLC is created, Doherty Applied AI LLC can submit trades.",
            "stale_assumption_flags": ["manual_flag"],
        }
    )
    questions = svc._extract_agent_questions(
        {
            "questions_for_adam": [
                "Which bank should I prepare the checklist for?",
                {"question": "Should website copy use ADA AI LLC as the legal footer?", "priority": "high"},
            ]
        }
    )

    assert "deprecated_company_identity" in flags
    assert "pre_llc_created_assumption" in flags
    assert "manual_flag" in flags
    assert [item["question"] for item in questions] == [
        "Which bank should I prepare the checklist for?",
        "Should website copy use ADA AI LLC as the legal footer?",
    ]


@pytest.mark.asyncio
async def test_ada_ai_llc_created_fact_reconciles_formation_tasks(monkeypatch):
    from app.services import company_operator_service as cos

    filing_task = _task(
        id="task-file",
        title="File Florida LLC Articles of Organization",
        status=TaskStatus.BLOCKED,
        priority=TaskPriority.CRITICAL,
        approval_state="pending",
    )
    ein_task = _task(
        id="task-ein",
        title="Apply for EIN using LLC name",
        status=TaskStatus.BLOCKED,
        priority=TaskPriority.HIGH,
        approval_state="pending",
    )
    task_service = _FakeTaskService(filing_task, tasks=[filing_task, ein_task])
    work_items = _FakeCompanyWorkItemService()
    monkeypatch.setattr(cos, "get_task_service", lambda: task_service)
    monkeypatch.setattr(cos, "get_company_work_item_service", lambda: work_items)

    actions = await CompanyOperatorService()._reconcile_company_facts(
        {"company_facts": {"llc_created": True, "legal_name": "ADA AI LLC"}},
        requested_by="test",
    )

    assert actions == [{
        "type": "fact_reconciled",
        "task_id": "task-file",
        "title": "File Florida LLC Articles of Organization",
        "fact": "ADA AI LLC created",
    }]
    assert task_service.tasks[0].status == TaskStatus.DONE
    assert task_service.tasks[0].approval_state == "approved"
    assert task_service.tasks[1].status == TaskStatus.BLOCKED
    assert work_items.events[0]["event_type"] == "fact_reconciled"


@pytest.mark.asyncio
async def test_company_approval_queue_links_non_formation_high_risk_tasks(monkeypatch):
    from app.services import company_operator_service as cos

    email_task = _task(
        id="task-email",
        title="Set up business email",
        domain="Operations",
        status=TaskStatus.BLOCKED,
        priority=TaskPriority.CRITICAL,
        risk_level="high",
        approval_state="pending",
    )
    password_task = _task(
        id="task-vault",
        title="Set up password vault",
        domain="Operations",
        status=TaskStatus.BLOCKED,
        priority=TaskPriority.HIGH,
        risk_level="high",
        approval_state="pending",
    )
    done_task = _task(
        id="task-done",
        title="File Florida LLC",
        domain="Formation",
        status=TaskStatus.DONE,
        priority=TaskPriority.CRITICAL,
    )
    task_service = _FakeTaskService(email_task, tasks=[email_task, password_task, done_task])
    approval_queue = _FakeApprovalQueue()
    work_items = _FakeCompanyWorkItemService()
    approvals = iter(["ap-email", "ap-vault"])

    async def fake_request(**kwargs):
        approval_id = next(approvals)
        approval_queue.requests.append(kwargs)
        return SimpleNamespace(id=approval_id, status="pending", **kwargs)

    approval_queue.request = fake_request
    monkeypatch.setattr(cos, "get_task_service", lambda: task_service)
    monkeypatch.setattr(cos, "get_approval_queue", lambda: approval_queue)
    monkeypatch.setattr(cos, "get_company_work_item_service", lambda: work_items)

    actions = await CompanyOperatorService()._queue_company_approvals({"max_approvals_per_tick": 6})

    assert [action["task_id"] for action in actions] == ["task-email", "task-vault"]
    assert [request["tool_name"] for request in approval_queue.requests] == [
        "company_operator_company_gate",
        "company_operator_company_gate",
    ]
    assert all(request["arguments"]["company"] == "ADA AI LLC" for request in approval_queue.requests)
    assert task_service.tasks[0].approval_id == "ap-email"
    assert task_service.tasks[1].approval_id == "ap-vault"
    assert task_service.tasks[2].approval_id is None
    assert [event["event_type"] for event in work_items.events] == ["approval_linked", "approval_linked"]
