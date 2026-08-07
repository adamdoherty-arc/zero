---
created: 2026-08-07
run_id: accfba3b-7f15-4640-aa98-82b9485d7a7e
mode: DRIVE+COVERAGE
project: zero
prior_score: 87.7
final_score: 87.1
tags: [claude-session, supervise, zero]
---

# Zero supervise run accfba3b

## Summary

Bare `/supervise zero`, so DRIVE+COVERAGE (blind_spots carried three domains at
missed >= 2). The run never got to the planned coverage sweep, because preflight
found the entire Zero stack dead.

It had been down **12.1 hours**: stopped 2026-08-06T19:56:50Z, still down when
this run probed at 08:03Z. Nine containers. Nothing had noticed.

Backlog 3 -> 2. Score 87.7 -> **87.1** (drain and coverage rotation both partial;
the infra result was the strongest part of the run).

## Shipped

- `ccfe53c` (zero) **fix: make the API able to shut down, and bound task execution**
- `6ced16b7` (legion) **feat: page when a project stops heart-beating**

Sprint 13564 / **Fix-163** completed through the retro gate. Sprint 10375
cancelled. Sprint 13302 went 4/9 -> 6/9 tasks complete.

### Why it was down, and why it stayed down

Two independent defects, one per repo.

**zero-api could not shut down at all.** The lifespan called
`loop.add_signal_handler(SIGTERM, ...)` during startup, but uvicorn installs its
own handlers in `Server.serve()` *before* it runs the lifespan. Ours replaced
uvicorn's, so `should_exit` was never set. On SIGTERM the API ran
`graceful_shutdown()` and closed the DB pool while uvicorn kept serving and
background loops kept polling a disposed pool — the `RuntimeError: Database not
initialized` lines in that stop. The process then never exited.

The first hypothesis was simpler and wrong: docker's 10s grace vs a scheduler
that drains in-flight jobs for up to 30s. Measuring killed it. `docker stop -t 60
zero-api` against the pre-fix image took the full **62s and still exited 137**,
which only happens if the process never exits at all. After removing the
override: **2s, exit 0**, clean drain through `Application shutdown complete`.
`stop_grace_period: 45s` shipped anyway, since it is genuinely needed once
shutdown works.

**Legion had every signal and no consumer.** `project_heartbeats` stopped
receiving rows at 19:56:44 and `health_score_computer._heartbeat_freshness` was
already scoring that gap as "heartbeat gone". Nothing turned it into an alert.
What an operator could actually see was `dependency_health: healthy` for the
whole blackout — that column is written by the dependency-freshness reviewer and
has nothing to do with uptime. `ProjectLiveness-01` now polls every 2 min and
pages when an active project goes quiet past 10 min, then pages again on
recovery. Only projects that have *ever* heartbeat are eligible; 9 of the 12
registered ones never have, and alerting on those would train the operator to
mute the channel.

**Task execution was unbounded.** `TaskExecutionService` (946 lines) had zero
`wait_for`/timeout/`CancelledError` handling, and `check_and_execute` awaits
`execute_task` inline while holding `self._lock`. One wedged task parked the
executor permanently — every later 2-min tick returned at the `is_busy()` guard.
`_reclaim_orphaned_tasks` only rescues rows stranded by process *death*, so a
live-but-hung executor was invisible to it.

## Key Lesson

A plausible root cause that explains the symptom is not the root cause. Docker's
10s grace against a 30s drain explained exit 137 perfectly and was wrong. One
60-second measurement separated them.

The companion lesson came from the regression test, which failed on first run and
was right to. `execute_task` assigned `self._current_task` and *then* awaited the
start-up notice outside the main `try` — so a cancellation landing in those awaits
skipped the `finally` and left the executor wedged anyway, which is the exact
state the new timeout exists to prevent. The fix was incomplete until the test
said so.

## Next-Run Lead

1. **content-loop is now missed=5**, the longest-standing coverage debt, displaced
   again (correctly) by the outage. Two dead ends to skip: the production status
   path is not `/api/character-content/production/status` (404), and `loop_runs`
   has no `job_name` column — it is `loop_id` into `loops`, so join first.
2. **Sprint 13302's last 3 tasks** (repository interfaces, DI container,
   testcontainers) are genuine XL refactors across a 457-module backend. They need
   a dedicated run, not a tail-end slot. 6 of 9 are now done.
3. **Sprint 13303 needs one operator sentence.** 17 live Eightfold/JIRA/Workday
   action items are landing in project 7's *engineering* sprint backlog. The
   destination already exists (`personal_work_item_service` + its router) and the
   seam is `_run_email_to_tasks` at `scheduler_service.py:2895`. Not re-routed
   unilaterally because it changes where the operator looks for real work.
4. `v2-playbook-candidate:` a library that installs process-wide signal handlers
   owns them. Registering your own from inside a lifespan/startup hook silently
   replaces the framework's, and the failure mode is not an error — it is a
   process that serves traffic forever and dies to SIGKILL.
5. `v2-playbook-candidate:` when adding a timeout to a long function, check what
   runs between the first mutation of shared state and the `try` that cleans it
   up. Anything in that window is uncancellable-safe only by accident.

## Coverage

Audited: **infra** (95), **act-with-approval** (93), **reason** (92, carried
R1/R2 re-verified as STALE — 6/6 council vote-vs-propose cases pass).

Still blind: content-loop (5), respond (4), index (2), retrieve (2), capture (1),
reflect (1), learn (1).

## Metrics

- Tests: **1181 passed, 30 skipped** (baseline 1177 + 4 new).
- Critic: no external critic; no subagents spawned (session instruction). Three
  self-verify catches recorded in `run_state.json`.
- Codegraph: 14 orchestrator calls (status/search/node/callers). Grep used only
  for logs, config and compose.
- skill_version: `unified-supervisor-v2.2`.
