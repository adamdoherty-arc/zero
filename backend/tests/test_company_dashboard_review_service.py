from __future__ import annotations

from datetime import datetime, timezone

from app.models.task import Task, TaskCategory, TaskPriority, TaskSource, TaskStatus
from app.services.company_dashboard_review_service import CompanyDashboardReviewService


def _task(**overrides) -> Task:
    base = {
        "id": "task-1",
        "project_id": "company",
        "title": "Set up business email",
        "description": "Seeded from docs/company/task-backlog.md (Admin Sprint).",
        "status": TaskStatus.BACKLOG,
        "category": TaskCategory.CHORE,
        "priority": TaskPriority.MEDIUM,
        "source": TaskSource.MANUAL,
        "domain": "Operations",
        "owner_agent": "zero-company-operator",
        "risk_level": "medium",
        "approval_state": "none",
        "tags": [],
        "links": [],
        "created_at": datetime.now(timezone.utc),
    }
    base.update(overrides)
    return Task(**base)


def test_review_packet_scores_placeholder_and_adds_completion_steps():
    svc = CompanyDashboardReviewService()

    packet = svc._build_review_packet(_task(), event_count=0, has_agent_task=False)

    assert 0 <= packet["score"] <= 100
    assert packet["score"] < 75
    assert packet["recommendation"] == "enrich"
    assert "actionable_description" in packet["missing_info"]
    assert len(packet["action_steps"]) >= 3
    assert len(packet["acceptance_criteria"]) >= 3


def test_review_archives_zero_dashboard_bootstrap_tasks():
    svc = CompanyDashboardReviewService()
    task = _task(
        id="task-2",
        title="Scaffold Next.js dashboard app",
        domain="Dashboard",
    )

    packet = svc._build_review_packet(task, event_count=1, has_agent_task=True)

    assert packet["recommendation"] == "archive"
    assert packet["score"] == 100


def test_priority_normalization_promotes_launch_critical_tasks():
    svc = CompanyDashboardReviewService()

    assert svc._normalized_priority(_task(title="Verify name on Sunbiz", domain="Formation")) == "critical"
    assert svc._normalized_priority(_task(title="Define service packages", domain="Consulting")) == "high"
    assert svc._normalized_priority(_task(title="Create consumables ledger", domain="Robotics")) == "low"
