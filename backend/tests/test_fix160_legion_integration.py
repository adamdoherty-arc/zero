"""
Fix-160 regression tests: the Legion integration service.

Context: `legion_integration_service` was overwritten on 2026-02-22 by a stub that
imported a package which has never existed (`app.enums`). Five scheduler jobs
raised ModuleNotFoundError on every fire for ~5.5 months, each swallowed by an
`except Exception` that let `_run_with_audit` record status="completed".

These tests pin the three things that were wrong and are cheap to regress:
  1. the module imports and exposes the factory its callers use,
  2. SCAN_PROJECTS maps to the REAL Legion project ids (every one was previously
     off by one into a neighbouring project),
  3. `_extract_action_items` accepts every shape `structured_chat` returns --
     a single action item comes back as a bare dict, and dropping it made the
     whole email->task job a silent no-op.
"""

import pytest


def test_module_imports_and_exposes_factory():
    """The stub had no factory; all five callers import exactly this symbol."""
    from app.services.legion_integration_service import (
        get_legion_integration_service,
        LegionIntegrationService,
    )

    svc = get_legion_integration_service()
    assert isinstance(svc, LegionIntegrationService)
    # Singleton: callers import it per-call and must not get a fresh cache each time.
    assert get_legion_integration_service() is svc


def test_callers_find_the_methods_they_invoke():
    """
    The stub exposed only `handle_signal`. These three names are what
    scheduler_service and autonomous_orchestration_service actually call.
    """
    from app.services.legion_integration_service import get_legion_integration_service

    svc = get_legion_integration_service()
    for name in (
        "auto_create_enhancement_tasks",
        "convert_emails_to_tasks",
        "escalate_blocked_tasks",
    ):
        assert callable(getattr(svc, name, None)), f"missing {name}"


def test_scan_projects_legion_ids_are_real():
    """
    Verified against Legion's projects table:
      1 Legion | 5 ADA Trading Platform | 6 FortressOS Job Platform | 7 Zero Personal Assistant

    The previous values (zero=8, ada=6, fortressos=7, legion=3) each pointed at a
    DIFFERENT REAL PROJECT, so signals would have been filed into someone else's
    backlog rather than failing loudly.
    """
    from app.services.enhancement_service import SCAN_PROJECTS

    assert SCAN_PROJECTS["zero"]["legion_id"] == 7
    assert SCAN_PROJECTS["ada"]["legion_id"] == 5
    assert SCAN_PROJECTS["fortressos"]["legion_id"] == 6
    assert SCAN_PROJECTS["legion"]["legion_id"] == 1


def test_archived_code_is_excluded_from_signal_scan():
    """
    `_archive` / `attic` hold retired code. Scanning them files TODO signals
    against code nobody runs, and the auto-fix loop then edits archived files --
    which is how two archived tdd-guide scripts ended up modified in the working
    tree. 40 of 741 live signals pointed into `_archive` before this exclusion.
    """
    import inspect
    from app.services.enhancement_service import EnhancementService

    src = inspect.getsource(EnhancementService._scan_directories_sync)
    assert '"_archive"' in src
    assert '"attic"' in src


class _Email:
    subject = "Invoice overdue"
    snippet = "Please pay invoice 4471 by Friday."
    from_address = "billing@example.com"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "llm_return, expected",
    [
        # A single action item arrives as a BARE DICT, not a 1-element list.
        # This is the shape that made the job a silent no-op: verified live
        # against a plainly actionable email, which extracted 0 items.
        ({"action": "Pay invoice 4471", "priority": 1}, 1),
        # Multiple items come back as a list.
        ([{"action": "a"}, {"action": "b"}], 2),
        # Some models wrap the array in an object.
        ({"action_items": [{"action": "a"}]}, 1),
        ({"items": [{"action": "a"}, {"action": "b"}]}, 2),
        # No action items -> empty, and a wrapper object with no recognised key
        # must not be mistaken for an item.
        ([], 0),
        ({"summary": "nothing to do"}, 0),
        # Junk entries inside a good list are dropped, not passed through as
        # tasks with an empty title.
        ([{"action": "a"}, {"note": "no action key"}, "garbage"], 1),
    ],
)
async def test_extract_action_items_handles_every_llm_shape(monkeypatch, llm_return, expected):
    from app.services import legion_integration_service as lis

    class _FakeLLM:
        async def structured_chat(self, **kwargs):
            return llm_return

    monkeypatch.setattr(
        "app.infrastructure.unified_llm_client.get_unified_llm_client",
        lambda: _FakeLLM(),
    )

    svc = lis.LegionIntegrationService()
    items = await svc._extract_action_items(_Email())
    assert len(items) == expected
    assert all(isinstance(i, dict) and i.get("action") for i in items)


@pytest.mark.asyncio
async def test_extract_action_items_swallows_llm_failure(monkeypatch):
    """An LLM outage must degrade to 'no action items', never propagate."""
    from app.services import legion_integration_service as lis

    class _BoomLLM:
        async def structured_chat(self, **kwargs):
            raise RuntimeError("all providers exhausted")

    monkeypatch.setattr(
        "app.infrastructure.unified_llm_client.get_unified_llm_client",
        lambda: _BoomLLM(),
    )

    svc = lis.LegionIntegrationService()
    assert await svc._extract_action_items(_Email()) == []


def test_escalation_cache_is_bounded():
    """
    The cooldown cache is keyed by task id and only consulted for 24h. Without
    pruning, a long-lived process accumulates one entry per blocked task ever seen.
    """
    from datetime import datetime, timedelta
    from app.services import legion_integration_service as lis

    svc = lis.LegionIntegrationService()
    now = datetime.utcnow()

    # Expired entries are dropped outright.
    svc._blocked_task_cache = {i: now - timedelta(hours=48) for i in range(10)}
    svc._prune_escalation_cache(now)
    assert svc._blocked_task_cache == {}

    # Live entries beyond the cap are trimmed oldest-first.
    svc._blocked_task_cache = {
        i: now - timedelta(seconds=i) for i in range(lis._ESCALATION_CACHE_MAX + 50)
    }
    svc._prune_escalation_cache(now)
    assert len(svc._blocked_task_cache) == lis._ESCALATION_CACHE_MAX


def test_removed_jobs_are_fully_unregistered():
    """
    `legion_enhancement_sync` (enabled:False, superseded) and `smart_suggestions`
    (duplicate of briefing_service._generate_ai_suggestions) were removed. A job
    left in the config with no handler -- or vice versa -- is a KeyError at
    registration, so both sides must stay in sync.
    """
    from app.services.scheduler_service import DAILY_SCHEDULE, JOB_CATEGORIES

    assert "legion_enhancement_sync" not in DAILY_SCHEDULE
    assert "smart_suggestions" not in DAILY_SCHEDULE
    # The two that carry real, unduplicated behaviour stay.
    assert "email_to_tasks" in DAILY_SCHEDULE
    assert "blocked_task_escalation" in DAILY_SCHEDULE

    # The UI groups jobs by category; a removed job left here renders a job that
    # can never run.
    categorised = {job for jobs in JOB_CATEGORIES.values() for job in jobs}
    assert "legion_enhancement_sync" not in categorised
    assert "smart_suggestions" not in categorised
