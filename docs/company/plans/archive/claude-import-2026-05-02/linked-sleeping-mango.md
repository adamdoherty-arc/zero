# Plan: Post-Plan Execution Verification Hook

## Context

Currently, when Claude Code exits plan mode and executes a plan, there's no automated gate ensuring the work was actually completed correctly, tested, and verified before the session ends. The existing `gsd-verify-gate.sh` Stop hook only checks GSD `.planning/` phases — it doesn't cover Claude Code's native plan mode (`~/.claude/plans/`).

The goal is a **Stop hook** that detects plan-mode work was executed, runs fast health checks, and blocks session end until verification passes.

## What Already Exists (Reuse, Don't Duplicate)

| System | What It Does | Gap |
|--------|-------------|-----|
| `gsd-verify-gate.sh` | Blocks stop if `.planning/` PLAN.md lacks VERIFICATION.md | Only covers GSD phases, not Claude plan mode |
| `gsd-verifier` agent | Goal-backward codebase verification | Only runs inside `gsd:execute-phase` |
| `gsd:verify-work` skill | Conversational UAT with user | Manual invocation only |
| `docker-health` skill | 16-check Docker audit with auto-fix | Manual invocation, too slow for hook |
| CLAUDE.md rules | Mandatory backend restart + verification | Advisory only, not enforced |

## Implementation Plan

### File 1: Create `/c/code/claude/scripts/plan-verify-gate.sh`

New Stop hook script that runs in ~5-10 seconds. Logic:

1. **Guard clauses** — No-op if not in ADA project (`CLAUDE.md` + `backend/` must exist)
2. **Override check** — Skip if `.claude/plan-verify-skip` exists (one-shot, deleted after use)
3. **Detect plan-mode work** — Find `~/.claude/plans/*.md` files modified in last 2 hours
4. **Detect git changes** — `git diff --name-only HEAD` + `git status --porcelain`
5. **If both exist**, run checks:
   - **Backend health** (if `backend/*.py` or `src/*.py` changed): `curl -s -m 5 http://localhost:8006/api/health` — blocks if fails
   - **Frontend health** (if `frontend/*.tsx` changed): `curl -s -m 5 http://localhost:5420/` — blocks if HTTP != 200
   - **Uncommitted changes** — warns if `git status --porcelain` is non-empty
6. **Output** — `{"decision":"block","reason":"..."}` if checks fail, or silent exit 0 if all pass

Pattern follows existing [gsd-verify-gate.sh](/c/code/claude/scripts/gsd-verify-gate.sh) for JSON escaping and error handling.

### File 2: Modify `~/.claude/settings.json` — Add hook to Stop array

Insert `plan-verify-gate.sh` as the **first** Stop hook (before gsd-verify-gate.sh):

```json
"Stop": [
  {
    "matcher": "",
    "hooks": [
      {
        "type": "command",
        "command": "bash /c/code/claude/scripts/plan-verify-gate.sh",
        "timeout": 15
      },
      // ... existing hooks unchanged
    ]
  }
]
```

### File 3: Create `.claude/hookify.plan-verify.local.md` (optional advisory)

Hookify warn rule that fires on Stop when transcript mentions plan execution. This is a lightweight reminder — the shell script is the actual gate.

```markdown
---
name: plan-verify-reminder
enabled: true
event: stop
action: warn
---
Plan verification: Ensure backend restarted, health checks pass, and changes committed.
```

## What the Hook Does NOT Do (By Design)

These exceed the 15-second timeout or require Claude interaction:

- Full QA run (`POST /api/qa/run`) — 30+ seconds
- Playwright smoke test — 10-30 seconds
- Plan content comparison against git diff — too fragile in shell
- Grade card updates — requires Claude
- Code review run — 60+ seconds

The hook catches the **most common failures** (forgot restart, service down, uncommitted work) and leaves deeper verification to Claude skills invoked during the session.

## User Override

| Method | How | Scope |
|--------|-----|-------|
| Touch file | `touch .claude/plan-verify-skip` | One-shot (auto-deleted) |
| Env var | `SKIP_PLAN_VERIFY=1` | Session-wide |

## Integration

- **Complements gsd-verify-gate.sh** — GSD checks `.planning/` phases, this checks `~/.claude/plans/` + ADA health
- **Both can fire** in the same session if both GSD phases and plan-mode were used
- **Fail-open** — Script errors or timeout result in allowing stop (never traps user)

## Files to Create/Modify

| File | Action |
|------|--------|
| `/c/code/claude/scripts/plan-verify-gate.sh` | **Create** |
| `C:\Users\hadam\.claude\settings.json` (Stop hooks) | **Modify** — insert new hook entry at position 0 |
| `c:\code\ADA\.claude\hookify.plan-verify.local.md` | **Create** (optional advisory) |

## Verification

1. Start Claude Code in ADA project, make no changes, exit — hook should be silent
2. Create a plan, modify a backend `.py` file, do NOT restart — hook should block with "backend health" message
3. Restart backend, retry exit — hook should pass
4. Test override: `touch .claude/plan-verify-skip` then exit — should bypass
5. Confirm gsd-verify-gate.sh still works independently alongside new hook
