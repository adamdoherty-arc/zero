# Nightly Git Sync Daemon

## Context

Legion manages 5 real projects (ADA, FortressOS, Legion, Zero, AIContentTools) plus 1 virtual (Ollama Manager). Currently, code changes from sprint execution and manual edits can sit uncommitted or unpushed indefinitely. There is no automated daily sync to GitHub. The user wants a nightly daemon that:
1. Detects uncommitted changes across all managed projects
2. Commits and pushes them to GitHub every night
3. Analyzes diffs with AI for learning insights
4. Includes Legion itself (project_id=3)

## Implementation

### 1. Create `backend/app/services/nightly_git_sync_service.py` (~300 lines)

**Core class: `NightlyGitSyncService`**

- `sync_all_projects()` — iterates `MANAGED_PROJECTS` from `legion_config.py`, skips virtual projects (`path=None`), processes each independently with isolated error handling
- `_sync_project(path, result)` — per-project flow:
  1. Validate path exists and has `.git/`
  2. `run_git(["rev-parse", "--abbrev-ref", "HEAD"])` — get current branch
  3. `run_git(["status", "--porcelain"])` — check for uncommitted changes
  4. If changes: `git add .` → `git commit -m "[Nightly Sync DATE] ..."` → push
  5. If no local changes: still check if ahead of remote and push if needed
  6. AI diff analysis via existing `GitSprintService.analyze_diff_with_ai()` (skip on sprint branches — sprint pipeline already handles learning)
- `_push_to_remote(path, branch, result)` — `run_git(["push", "-u", "origin", branch])`, log error on rejection (no auto-rebase — too risky unattended)
- `_analyze_diff(path, result)` — `git show --stat --patch HEAD`, truncate to 10K chars, pass to `analyze_diff_with_ai()`
- `_record_learnings(results)` — write `SprintLearningDB` records with `learning_type="code_change"`, `sprint_id=None`, `project_id` from DB lookup
- `_send_summary_notification(results)` — Discord via `NotificationService.notify()`
- `get_last_sync_status()` — returns cached results for API endpoint

**Daemon entry point: `start_nightly_git_sync_daemon()`**
- Sleep-until-target-time pattern (same as `ollama_manager_service.py`)
- Default 2 AM UTC, configurable via `GIT_SYNC_HOUR_UTC` env var
- Initial 90s delay on startup to let system settle

**Key reuse:**
- `run_git()` from [async_subprocess.py](backend/app/services/async_subprocess.py) (line 79)
- `GitSprintService.analyze_diff_with_ai()` from [git_sprint_service.py](backend/app/services/git_sprint_service.py)
- `NotificationService.notify()` from [notification_service.py](backend/app/services/notification_service.py)
- `SprintLearningDB` from [sprint_execution.py](backend/app/models/sprint_execution.py) (line 883)
- `MANAGED_PROJECTS` from [legion_config.py](backend/app/core/legion_config.py) (line 70)

**Commit message format:**
```
[Nightly Sync 2026-04-02] Auto-commit 5 file(s)

Branch: main
Files:
  M backend/app/services/foo.py
  M frontend/src/pages/Bar.tsx
  ... (first 20 files from git status --porcelain)

Co-Authored-By: Legion Git Sync <noreply@legion.ai>
```

**Prometheus metrics (module-level):**
- `legion_git_sync_projects_total` Counter (labels: project, result)
- `legion_git_sync_duration_seconds` Histogram

### 2. Create `backend/app/api/endpoints/git_sync.py` (~60 lines)

Two endpoints with Pydantic response models:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/git-sync/status` | GET | Last sync timestamp + per-project results |
| `/api/git-sync/trigger` | POST | Manually trigger sync (calls `sync_all_projects()`) |

### 3. Modify `backend/app/api/router_registry.py`

- Add `git_sync` to the import list (line 14)
- Add `app.include_router(git_sync.router, prefix=_api, tags=["Git Sync"])` in the "Git & PRs" section (after line 70)

### 4. Modify `backend/main.py` (after line 475)

Register the daemon using `_supervised_task` pattern:
```python
_git_sync_enabled = os.getenv("ENABLE_GIT_SYNC", "true").lower() in ("true", "1", "yes")
if _git_sync_enabled:
    from app.services.nightly_git_sync_service import start_nightly_git_sync_daemon
    t = asyncio.create_task(_supervised_task("nightly_git_sync", start_nightly_git_sync_daemon))
    task_registry.register("nightly_git_sync", t, kind="daemon")
```

### 5. Modify `docker-compose.yml`

Add env vars to backend service:
```yaml
ENABLE_GIT_SYNC: ${ENABLE_GIT_SYNC:-true}
GIT_SYNC_HOUR_UTC: ${GIT_SYNC_HOUR_UTC:-2}
```

### 6. Create `backend/tests/services/test_nightly_git_sync.py` (~150 lines)

Test cases with mocked `run_git`:
- No changes (porcelain empty) → status "no_changes"
- Successful commit + push → status "committed", push_success=True
- Commit ok, push rejected → logs error, moves to next project
- Non-git-repo → status "error"
- Sprint branch detection → `is_sprint_branch=True`, skip AI analysis
- `_parse_stat_line()` parsing edge cases
- Virtual project skipped (ollama_manager)

## Design Decisions

| Decision | Rationale |
|----------|-----------|
| Commit to current branch (not force-switch to main) | Avoids disrupting active sprint branches |
| No auto-rebase on push rejection | Unattended rebase can create merge conflicts requiring human intervention |
| Skip AI analysis on sprint branches | Sprint pipeline already records learnings — avoid double-learning |
| `git push -u origin <branch>` directly (not `push_to_main()`) | `push_to_main()` is gated by ALLOW_DIRECT_PUSH and includes merge logic we don't need |
| One failure doesn't block other projects | Each project wrapped in try/except, results collected independently |
| No code review agent integration (deferred) | Expensive (ReAct loop per file), dormant infrastructure, better suited for a follow-up sprint |

## Verification

1. `docker-compose build legion-backend && docker-compose up -d`
2. `curl http://localhost:8005/health | jq '.background_tasks.nightly_git_sync'` — confirm daemon registered
3. `curl -X POST http://localhost:8005/api/git-sync/trigger | jq` — manual sync, check per-project results
4. `curl http://localhost:8005/api/git-sync/status | jq` — confirm results cached from trigger
5. `cd backend && python -m pytest tests/services/test_nightly_git_sync.py -v` — all tests pass
6. Check Discord for sync summary notification

## Sprint Tracking

```sql
INSERT INTO sprints (name, description, project_id, status, priority, total_tasks, created_at, updated_at)
VALUES ('Infra-03: Nightly Git Sync', 'Daemon that commits and pushes uncommitted changes across all managed projects to GitHub nightly at 2 AM UTC, with AI diff analysis and learning', 3, 'PLANNED', 1, 6, NOW(), NOW());
```
