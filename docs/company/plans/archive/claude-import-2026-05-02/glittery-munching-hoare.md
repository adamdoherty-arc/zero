# Plan: Make GitHub Repos / Git Sync Visible and Verified

## Context
The user built a GitHub Repos page (`/github-repos`) that tracks all projects and when they were last pushed. A nightly git sync daemon commits and pushes changes daily at 2 AM UTC. **Both work**, but the user can't find them because:
- The sidebar has 14 items in OPERATIONS before the SYSTEM section starts
- GitHub Repos and Git Updates are in the SYSTEM section, buried below the fold
- The user landed on Pull Requests (wrong page) because it's the closest-sounding option in the visible area

## Changes

### 1. Move GitHub Repos higher in the sidebar
**File**: [Sidebar.tsx](frontend/src/components/Sidebar.tsx)

Move `{ to: '/github-repos', icon: FolderGit2, label: 'GitHub Repos' }` from the `systemItems` array (line 43) into the `operationItems` array, positioned right after Pull Requests (line 33). This puts it in the visible area alongside the related Pull Requests link.

Also move `{ to: '/git', icon: GitBranch, label: 'Git Updates' }` from `systemItems` (line 46) to right after GitHub Repos in `operationItems`, since they're related.

### 2. Remove the unnecessary LLM call from nightly sync
**File**: [nightly_git_sync_service.py](backend/app/services/nightly_git_sync_service.py)

The `_analyze_diff()` method (lines ~346-371) calls `GitSprintService.analyze_diff_with_ai()` after every commit, consuming LLM tokens for a simple "what changed" summary. The user correctly notes this isn't needed — the git commit message already lists all changed files.

- Remove the `_analyze_diff()` call from the post-commit flow (around line 264-266)
- Keep the method in place (dead but available) in case it's wanted later, OR delete it entirely
- The `_record_learnings()` call can still fire with the git stats (files changed, insertions, deletions) without the AI summary

### 3. Verify nightly sync covers all projects
**Verification only** (no code changes): Confirm the daemon is running and all 5 managed projects (Legion, ADA, FortressOS, Zero, AIContentTools) have recent `[Nightly Sync]` commits by checking:
```bash
curl -s http://localhost:8005/git-sync/status | python -m json.tool
```

## Files Modified
1. `frontend/src/components/Sidebar.tsx` — move 2 nav items from systemItems to operationItems
2. `backend/app/services/nightly_git_sync_service.py` — remove LLM diff analysis call

## Verification
1. **Sidebar**: Rebuild frontend, confirm GitHub Repos and Git Updates appear in the OPERATIONS section without scrolling
2. **Nightly sync**: Rebuild backend, trigger manual sync via `POST /git-sync/trigger`, confirm commits happen without LLM calls
3. **Git sync status**: `GET /git-sync/status` returns recent sync results for all projects
