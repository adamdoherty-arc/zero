---
name: zero-employee-checkin
description: Daily stand-up for Zero's 24/7 employee loop AND active remediation. Pulls grades, writes per-subsystem cards to .claude/memory/grades/, then investigates and fixes every issue found — driving each subsystem toward 100. Not just reporting. For the deep weekly audit use /zero-deep-review.
---

# /zero-employee-checkin

Zero's daily stand-up **and fix-it loop**. Answers: "what did the 24/7 employee accomplish, how is each subsystem trending, what's stuck — and now let's fix it."

Claude Code has full build access to this repo. This skill is not a reporter. Every issue surfaced must be investigated and addressed in the same session, or explicitly deferred with a reason.

**Legion is not used on Zero.** Do not create Legion tasks, do not reference Legion, do not import `LegionClient`. Ignore any stale references.

## When to use

- Starting a session and you want to know what Zero did overnight, then close the loop on regressions.
- Investigating a suspected regression in any subsystem.
- Before planning the day — so the day's work is shaped by what's actually broken.

## Flow

### Phase 1: Pulse (fast)

1. Call the backend check-in endpoint:
   ```bash
   curl -s -X POST \
     -H "Authorization: Bearer $ZERO_GATEWAY_TOKEN" \
     "http://localhost:18792/api/employee/checkin/run?window_hours=24"
   ```
   Persists a snapshot in `employee_checkins` and returns ops + carousel + research + reference-video + audit subsystems.

2. Pull 7-day history for trend lines:
   ```bash
   curl -s -H "Authorization: Bearer $ZERO_GATEWAY_TOKEN" \
     "http://localhost:18792/api/employee/checkin/history?days=7"
   ```

3. Write per-subsystem grade cards to `.claude/memory/grades/<subsystem>.md` (overwrite each run):
   ```markdown
   # <Subsystem> — <Grade>/100

   **Trend (7d):** 72 → 74 → 71 → 68 → 70 → 69 → 71

   ## Issues
   - <issue 1>

   ## Wins
   - <win 1>

   ## Fixes this run
   - <what was changed, or "deferred: reason">

   ## Last check-in: <ISO timestamp>
   ```

### Phase 2: Triage & Fix (the point of this skill)

For each issue in the response, do not stop at reporting. Work through this loop:

1. **Classify**: is it (a) a code bug, (b) a data/ingest failure, (c) a prompt/LLM regression, (d) a metric/grade formula bug, or (e) a throughput/scheduler gap?

2. **Investigate the root cause** — read logs, grep the relevant service, check recent commits:
   ```bash
   docker logs --tail 200 zero-api 2>&1 | grep -iE "error|fail|warn"
   git log --oneline -20 -- backend/app/services/<subsystem>_service.py
   ```

3. **Fix it in code**. Build access is available — edit the service, fix the prompt, cap the grade formula, retry failed ingests, etc. Rebuild the affected container per CLAUDE.md's mandatory deploy rules:
   ```bash
   docker compose -f docker-compose.sprint.yml build --no-cache zero-api \
     && docker compose -f docker-compose.sprint.yml up -d zero-api
   ```

4. **Verify** by re-running the check-in (or a targeted endpoint) and confirming the issue drops off or the grade moves.

5. **Record** what changed in the subsystem's grade card under a "Fixes this run" section.

### Phase 3: Only defer when justified

An issue may be deferred only if one of:
- It requires a decision from the user (ambiguous product question).
- Fix is larger than the session budget — in which case stash a one-line TODO in the subsystem's grade card, no external tracker.
- It is already known broken and tracked in an active plan file under `.claude/plans/`.

## Known issue playbook

Map common issues to their fix pattern so the loop converges on 100:

| Symptom | Likely fix |
|---|---|
| Carousel Stage 2 avg score well below threshold | Prompt drift — inspect [content_swarm_service.py](../../backend/app/services/content_swarm_service.py) and character prompt seeds; diff against last known-good commit |
| Low carousel throughput | Check scheduler job cadence in [scheduler_service.py](../../backend/app/services/scheduler_service.py); verify queue isn't blocked on a single failing character |
| Reference video ingest failures | Inspect failed rows in DB, re-run yt-dlp manually for one URL, check `character_reference_video_service.py` error paths |
| Research grade uncapped (>100) | Cap the formula in [employee_checkin_service.py](../../backend/app/services/employee_checkin_service.py) |
| Audit idle (0 audited in window) | Check re-audit scheduler job is registered and running |
| Ops grade < 80 | Run `daily_report_service` manually and inspect job failure list |

## How to run it

Invoke `/zero-employee-checkin` — the skill drives Phases 1-3. Or manually via the `/employee` dashboard "Run check-in now" button.

Scheduler job `employee_checkin` runs at 08:00 daily producing the snapshot unattended; it does not auto-fix. Only this skill closes the loop.

## Related

- Dashboard UI: `/employee` ([frontend/src/pages/EmployeeDashboardPage.tsx](../../frontend/src/pages/EmployeeDashboardPage.tsx))
- Backend service: [backend/app/services/employee_checkin_service.py](../../backend/app/services/employee_checkin_service.py)
- Scheduler job: `employee_checkin` (08:00 daily) in [backend/app/services/scheduler_service.py](../../backend/app/services/scheduler_service.py)
- Deep audit: `/zero-deep-review` (weekly, not daily)
- Per-subsystem history: `GET /api/employee/checkin/history?days=30`
