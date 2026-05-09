# Plan: schedule a weekly LEGION_OVERVIEW.md refresh + post-review next steps

## Context

We just landed `docs/LEGION_OVERVIEW.md` — a single canonical system overview grounded in the live Legion code (62 routers, 168 services, 28 frontend pages, 40 Alembic migrations, 22 daemons, 10 oneshot tasks, vLLM-only LLM stack). The doc has six sections that drift fast as the codebase evolves: §9 (Background workers), §11 (API surface), §12 (Frontend pages), §13 (Database / migrations), §17 (Honest current state), §19 (Deprecated docs).

The user wants:
1. A **weekly remote agent** that re-audits the live code and refreshes those drift-prone sections.
2. A summary of **what to tackle next** after reviewing everything during this audit.

Prior-art check (Explore agent): `scheduler_service.py` and `git_update_scheduler.py` exist inside the backend, and `product_docs_service.py` auto-updates `.legion/PRODUCT.md` after sprints — but **nothing touches `LEGION_OVERVIEW.md`** and there is no remote routine for doc maintenance. Clear field.

## Approach

Use the **`/schedule`** skill (remote routine on cron). Decouples doc maintenance from Legion's own uptime — if `legion-backend` is down for a day, the doc refresh still runs because it executes in the cloud agent runtime against the git repo. The agent does not need the running stack; it only needs the repo and (optionally) a brief HTTP probe of `/api/health/daily-standup` if the stack happens to be up.

**Cadence:** Mondays at **06:00 UTC** (`0 6 * * 1`). Aligns with the existing daily-standup window (`0 6 * * *`) so the weekly review consumes the freshest standup snapshot if the stack is up.

**Output:** the agent opens a **PR** titled `docs: weekly LEGION_OVERVIEW.md refresh — YYYY-MM-DD` with the diff. PR-not-direct-commit so a human eyeballs structural drifts (e.g., a router being deleted vs renamed) before merge. PR auto-labels `docs`, `automated`.

**Discord summary:** if `DISCORD_WEBHOOK_URL` is configured, the agent posts a one-paragraph summary (counts that changed, sections refreshed, PR URL).

**Failure mode:** if no drift detected, agent posts a no-op summary to Discord and exits without opening a PR. If the repo state is dirty / branch-protected / write fails, agent reports the failure to Discord and exits non-zero so the user sees a notification.

### Weekly agent prompt (what `/schedule` registers)

```
Refresh docs/LEGION_OVERVIEW.md in the c:\code\legion repo against the
live code. Treat the file as canonical and only update sections that have
drifted from the codebase.

Re-enumerate from source of truth:
  §9 Background workers — `task_registry.register(...)` calls in backend/main.py
  §11 API surface — `app.include_router(...)` calls in backend/app/api/router_registry.py
  §12 Frontend pages — `lazy(() => import(...))` in frontend/src/App.tsx + Routes
  §13 Database — file count under backend/alembic/versions/ + recent migration filenames
  §17 Honest current state — pull `/api/health/daily-standup` if backend reachable
                              (curl http://localhost:8005/api/health/daily-standup);
                              fall back to recent commit summary + sprint counts
                              from SELECT FROM sprints WHERE project_id=1
  §19 Deprecated docs — `ls docs/*.md` minus the kept-as-reference allow-list

Update only the drifted lines. Preserve structure, glossary, mission.

Open a PR titled `docs: weekly LEGION_OVERVIEW.md refresh — <today>`
with body listing exactly what counts changed and which sections moved.

If no drift: post a no-op summary to DISCORD_WEBHOOK_URL (if set) and exit.

Do NOT touch any other docs file. Do NOT modify CLAUDE.md, AGENTS.md,
or any of the deprecated topical docs in §19. The only writable target
is docs/LEGION_OVERVIEW.md.
```

### Schedule invocation (what to run)

```
/schedule create
  name: weekly-legion-overview-refresh
  cron: 0 6 * * 1
  prompt: <see prompt block above>
  repo: c:\code\legion
  branch: main
  open_pr: true
  pr_label: docs,automated
```

## Verification

End-to-end test before relying on it:

1. **Manual dry run:** `/schedule run weekly-legion-overview-refresh` to fire it once on demand. Confirm the agent opens a PR (or posts no-op to Discord if nothing changed since the file was just written).
2. **Drift simulation:** add a stub router (`app.include_router(stub.router, ...)` in `router_registry.py`), commit on a throwaway branch, run the routine against that branch, confirm §11 count goes up and the new tag appears in the PR diff. Revert.
3. **List confirmation:** `/schedule list` shows the routine with next-fire timestamp and last-run status.
4. **First production fire:** the next Monday 06:00 UTC, watch for the PR or the no-op Discord post. If neither arrives within 30 min of the slot, `/schedule list` to check for an error trail.

Critical files referenced (read-only by this plan; only the weekly agent ever writes):
- `c:\code\legion\docs\LEGION_OVERVIEW.md` — the file being refreshed
- `c:\code\legion\backend\main.py` — daemon registry source of truth
- `c:\code\legion\backend\app\api\router_registry.py` — router source of truth
- `c:\code\legion\frontend\src\App.tsx` — pages source of truth
- `c:\code\legion\backend\alembic\versions\` — migration source of truth

---

## Post-review: next steps after reviewing everything

Ranked by leverage. Each item is one sprint-sized chunk; numbers are honest priorities, not aspirational.

### Tier 1 — verify the work that already shipped (low cost, high signal)

1. **Verify Audit-Remediation-01 fixes actually moved metrics.** Three fixes landed (grader scoping, swarm `LearningEngine` wiring, LLM-review sanitizer). Each has a measurable counter: (a) sprint `prompt_quality` should now vary across sprints instead of all reading 53.4 — query `sprint_quality_grades` for the last 20 sprints, confirm distribution is non-degenerate; (b) `legion_learning_engine_enrichments_total` should be incrementing on swarm-executed tasks — `curl /metrics | grep '^legion_learning_engine_enrichments_total'`; (c) reviewer schema-parse failures (the `<minimax:tool_call>` leak) should drop to ~0 — query `LLMCallDetail` for recent reviewer rows where `review_score IS NULL`. If any one isn't moving, the fix is wired but inert and needs a follow-up.
2. **Live-verify Fix-46.** `Core Loop` is rated 15/100 specifically because Auto-Sprint tasks now route through middleware but no one has watched them complete end-to-end. Pick one Auto-Sprint task, watch the log chain (`[Middleware] task accepted → executor → grader → committer`) within 5 min of restart. If the spontaneous-fire rule fails, the wiring is broken.
3. **Live-verify the PR end-to-end loop.** Trigger one dependency-review sprint manually, let it run to PR open, manually merge, watch `pr_management_service` close out the sprint to `COMPLETED`. This is what makes Legion deliver value. Do it once with eyes on it before declaring it works.

### Tier 2 — unblock the autonomous mode (the actual product)

4. **Drive Sprint Creation Gate from `safe` → `on`.** The gate is parked at `safe` (only `manual_api` + `dependency_review` create sprints) until 5 consecutive real sprints land cleanly without phantoms. Enumerate the last 10 real sprints from `sprint_quality_grades`, check phantom count = 0 and grades > 50. If yes, flip to `on`. If no, fix the failing class first.
5. **Cleanup the 41 pre-existing test failures** (sprint manager status tests, LLM review mocks). They hide regressions. One sprint of triage; the failures are mostly in two clusters and likely share root causes.

### Tier 3 — strategic (multi-sprint)

6. **Service consolidation pass: 168 → ~80.** Run `/legion-platform-auditor` (already in the skills list) to mechanically find duplicate / dead services. Bundle removals into a single Quality sprint per coherent cluster (e.g., merge `qa_pipeline_service` + `qa_service` + `enhanced_qa_pipeline`). The 168 number is a load-bearing rating drag — taking it down moves Architecture from 35/100 to ~55.
7. **Wire email notifications.** Discord-only is one outage from a missed alert. `notification_service.py` already has the abstraction; needs an SMTP / SES adapter and `NOTIFICATION_EMAIL` already declared in env. One small sprint.
8. **Kick off Builder-01 (Spec Inference).** Roadmap exists in `.legion/plans/BUILDER_MODE_ROADMAP.md`; nothing has shipped. This is the next product unlock — Legion goes from "manages existing projects" to "creates new ones from prompts". One sprint to define `ProjectSpecService` + `POST /api/projects/from-prompt` + the Pydantic schema for `ProjectSpecDB`. Defer Builder-02 onwards until Builder-01 ships clean.

### Not on the list (by design)

- Re-enabling cloud LLM fallback. Operator directive is loud-fail over silent MiniMax billing; respect it.
- Adding new services. The trend is consolidation, not addition. Builder Mode is the only sanctioned new surface.
- Touching the deprecated topical docs in `docs/`. The new master and §19 are sufficient; bulk file edits there are pure churn.

The order above is also a sequencing claim: Tier 1 takes a day total and tells us whether the fixes from the last audit were real. Tier 2 is the gating work for autonomy. Tier 3 is what unlocks the next quality jump. Don't reorder — verifying Tier 1 first prevents building on phantom progress.
