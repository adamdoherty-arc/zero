"""Fix-163: a wedged task must not park the executor forever.

check_and_execute awaits execute_task inline while holding self._lock, and
execute_task was unbounded. One stalled LLM call or subprocess therefore left
_status=EXECUTING and _current_task set for the life of the process: every
later 2-min scheduler tick hit the is_busy() guard and returned. The existing
_reclaim_orphaned_tasks only rescues rows stranded by process DEATH, so a
live-but-hung executor was invisible to it.

test_cleanup_runs_when_cancelled_during_startup_notice is the one that caught a
real hole while this fix was being written: the start-up activity-log/notify/
save-state block used to sit BETWEEN `self._current_task = task` and the main
try, so a cancellation arriving in those awaits skipped the finally and left the
executor busy anyway. Keep that test honest — it pins the ordering, not the
timeout.
"""
import asyncio

import pytest

from app.services.task_execution_service import ExecutionStatus, TaskExecutionService


def _make_service(timeout_s: float, *, fast_io: bool = True) -> TaskExecutionService:
    """Service with a short timeout.

    fast_io stubs the notify/state-save side effects so a sub-second timeout
    reaches the planning phase instead of expiring in the preamble. The
    startup-cancellation test deliberately leaves them real.
    """
    svc = TaskExecutionService()
    svc._settings["task_timeout_seconds"] = timeout_s
    if fast_io:
        async def _noop(*_a, **_kw):
            return None
        svc._notify = _noop
        svc._save_current_state = _noop
    return svc


async def _run_with_bound(svc: TaskExecutionService, task: dict):
    """Apply exactly the bound check_and_execute applies."""
    return await asyncio.wait_for(
        svc.execute_task(task), timeout=svc._settings["task_timeout_seconds"]
    )


@pytest.mark.asyncio
async def test_hung_task_is_cancelled_and_marked_failed():
    """A task that never returns is cancelled and records why."""
    svc = _make_service(0.2)
    task = {"task_id": "hung-1", "title": "Never returns", "description": ""}
    cancelled_inside = asyncio.Event()

    async def hang(_task):
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            cancelled_inside.set()
            raise

    svc._plan_task = hang

    with pytest.raises(asyncio.TimeoutError):
        await _run_with_bound(svc, task)

    assert cancelled_inside.is_set(), "inner work was never actually cancelled"
    # CancelledError is a BaseException, so the generic `except Exception`
    # never saw it; without an explicit handler the task filed to history
    # with no status and no reason.
    assert task["status"] == "failed"
    assert "task_timeout_seconds" in task["result"]["error"]


@pytest.mark.asyncio
async def test_executor_returns_to_idle_after_timeout():
    """The whole point: the executor frees itself for the next tick."""
    svc = _make_service(0.2)
    task = {"task_id": "hung-2", "title": "Never returns", "description": ""}

    async def hang(_task):
        await asyncio.sleep(3600)

    svc._plan_task = hang

    with pytest.raises(asyncio.TimeoutError):
        await _run_with_bound(svc, task)

    assert svc._status == ExecutionStatus.IDLE
    assert svc._current_task is None
    assert svc.is_busy() is False


@pytest.mark.asyncio
async def test_cleanup_runs_when_cancelled_during_startup_notice():
    """Cancellation in the pre-planning awaits must still release the executor.

    Regression pin: with the startup notice outside the main try, this left
    _current_task set and is_busy() True forever.
    """
    svc = TaskExecutionService()
    svc._settings["task_timeout_seconds"] = 0.001
    task = {"task_id": "hung-3", "title": "Cancelled early", "description": ""}

    async def never_reached(_task):
        raise AssertionError("planning should not have been reached")

    svc._plan_task = never_reached

    with pytest.raises(asyncio.TimeoutError):
        await _run_with_bound(svc, task)

    assert svc._current_task is None, "executor stayed busy after early cancel"
    assert svc.is_busy() is False
    assert svc._status == ExecutionStatus.IDLE


@pytest.mark.asyncio
async def test_timeout_setting_has_a_bounded_default():
    """An unset or zeroed setting must not degrade back to unbounded."""
    svc = TaskExecutionService()
    assert svc._settings["task_timeout_seconds"] > 0

    svc._settings["task_timeout_seconds"] = None
    assert (svc._settings.get("task_timeout_seconds") or 1800) == 1800
