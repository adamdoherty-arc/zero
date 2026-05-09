# Turn Off Deep Research Autopilot

## Context

The Deep Research page is filling up with auto-generated queries the user didn't ask for ("Self-Hosted AI Automation", "AI Chat UIs", "AI Skills & Plugins", LangGraph/pgvector/Reachy voice topics, plus character biographies). Several are failing. The user doesn't recognize where they come from and considers the feature unneeded.

Root cause: **four scheduler jobs** fire research automatically — two drive an older `research_service` (the "AI Chat UIs" / "Self-Hosted AI Automation" queries), and two drive a newer `autonomous_research_loop_service` + `deep_research_service` (LangGraph / pgvector / etc). They run without user input.

Goal: silence the autopilot so no new research is dispatched on its own. Leave the UI and API intact so existing reports remain viewable and manual runs still work — we're stopping the firehose, not deleting the feature.

## Scope decision

Two options the user can pick between at the ExitPlanMode gate:

- **A. Silence autopilot only (recommended).** Disable the four scheduler jobs. UI, API, and old reports remain. Fully reversible by flipping flags back.
- **B. Hide the feature entirely.** Everything in A, plus remove the sidebar link and `/deep-research` route so the page is no longer reachable. Backend untouched.

I'm planning **A** as the default. We can escalate to B in one edit if desired.

## Files to modify

### 1. Disable the four scheduler jobs

**File:** [backend/app/services/scheduler_service.py](backend/app/services/scheduler_service.py)

Flip `"enabled": True` → `"enabled": False` at four locations:

- [scheduler_service.py:138-142](backend/app/services/scheduler_service.py#L138-L142) — `research_daily` (11 AM daily). Drives the "AI Chat UIs" / "Self-Hosted AI Automation" / "AI Skills & Plugins" queries via `research_service.run_daily_cycle()`.
- [scheduler_service.py:143-147](backend/app/services/scheduler_service.py#L143-L147) — `research_weekly_deep_dive` (Sat 10 AM). Same service, weekly deep dive.
- [scheduler_service.py:410-414](backend/app/services/scheduler_service.py#L410-L414) — `ai_company_deep_research` (every 6h). Runs the STORM pipeline on the highest-priority queued topic.
- [scheduler_service.py:416-420](backend/app/services/scheduler_service.py#L416-L420) — `autonomous_research_tick` (every 15 min). 24/7 driver that picks a topic, dispatches deep research, writes results into the Obsidian vault.

**Leave enabled** (product-facing, distinct from "Deep Research" page):
- `tiktok_shop_research`, `tiktok_shop_deep_research`, `tiktok_continuous_research`, `tiktok_niche_deep_dive`, `tiktok_niche_rotation` — all TikTok Shop product discovery, not the generic research page.

### 2. Belt-and-suspenders feature flag

**File:** `.env` (user-managed; document the variable in the plan but don't write it)

Add `ZERO_AUTONOMOUS_RESEARCH_ENABLED=false`. The autonomous research loop checks this at [config.py:62](backend/app/infrastructure/config.py#L62) before dispatching. Even if someone re-enables the scheduler job by accident, this gate short-circuits the tick handler.

### 3. (Optional — escalate to scope B) Hide the page

**File:** [frontend/src/components/layout/AppSidebar.tsx](frontend/src/components/layout/AppSidebar.tsx#L95)
Remove the `{ label: 'Deep Research', href: '/deep-research', icon: BookOpen }` entry.

**File:** [frontend/src/App.tsx](frontend/src/App.tsx#L132)
Remove the `<Route path="/deep-research" ... />` line and the `DeepResearchPage` import at line 45.

Not doing this by default — keeping the UI accessible means old reports remain viewable and manual runs from the search box still work.

## What we are NOT doing

- Not deleting [backend/app/routers/deep_research.py](backend/app/routers/deep_research.py) or [deep_research_service.py](backend/app/services/deep_research_service.py). Manual POSTs to `/api/research/deep` still work.
- Not dropping the `deep_research_reports` or `research_topics` tables. Existing reports remain queryable.
- Not touching the orchestration route `deep_research` in [orchestration_graph.py](backend/app/services/orchestration_graph.py) — if someone asks Zero "deep research X", it still works on demand.
- Not investigating why the failing reports failed. The user wants it off, not fixed. If they later want to fix it, the failure points are catalogued in `deep_research_service.py` lines 163, 186, 217, 239, 286 (all wrap `structured_chat()` calls).

## Deployment

Backend code is COPY'd per [CLAUDE.md](CLAUDE.md), so scheduler changes need a rebuild:

```bash
docker compose -f docker-compose.sprint.yml build --no-cache zero-api && docker compose -f docker-compose.sprint.yml up -d zero-api
```

If the `.env` flag is added, same rebuild picks it up (env is read at startup).

## Verification

1. **Confirm jobs removed from scheduler:** `docker logs zero-api 2>&1 | grep -E "scheduler_job_registered|scheduler_job_skipped" | grep -E "research_daily|research_weekly|autonomous_research|ai_company_deep_research"` — should show `skipped` (enabled=False) for all four, not `registered`.
2. **Watch for silence:** `docker logs -f zero-api 2>&1 | grep -E "autonomous_research_tick|ai_company_deep_research|research_daily"` — should print nothing for 20+ min (15-min tick should have already fired).
3. **Open the page:** `/deep-research` in the UI. New research should not appear. Existing reports still list and open.
4. **Pending reports:** Any reports currently in `status=researching` in the screenshot ("Self-Hosted AI Automation", top "AI Chat UIs") will stay stuck. Optional cleanup query (run manually if they clutter the list):
   ```sql
   UPDATE deep_research_reports SET status='failed', error='Cancelled - autopilot disabled' WHERE status='researching';
   ```
   Not doing this automatically — it's the user's call whether to mark them failed or leave them.
