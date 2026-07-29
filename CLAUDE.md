# Zero — Claude Code Operating Rules

> This file is the always-loaded baseline. Topic-specific rules live in `.claude/rules/`. Active learnings tracked in `.claude/MEMORY.md`.
> Updated weekly by the `claude-md-curator` skill.

## What Zero is

Zero is a **personal assistant + autonomous research/trading + content-loop** project. Python/FastAPI backend + React/Vite frontend, PostgreSQL, shared LiteLLM for cross-project LLM infra, Bifrost client at shared-bifrost:4445 for routing. Sprints sync to **Legion** (the management system at host.docker.internal:8005) — Zero's `project_id` in Legion is **7** (corrected 2026-05-17 from previous 8).

Robot/Reachy hardware control (Cockpit, daemon, motion library, teleop, camera, realtime voice) moved to a separate app, **Zero Studio**, on 2026-07-11. Zero is now text/task-focused — no voice or camera surface. Don't re-add Reachy UI, routers, or `host_agent` here; that's Zero Studio's scope now.

## The three rules that override everything

1. **AUTONOMOUS EXECUTION.** Execute commands without asking. Docker/npm/pip/git/tests/builds — all autonomous. Only pause on unresolvable blockers. Details in `.claude/rules/00-critical.md`.
2. **FIX ON SIGHT.** Any broken thing — dead service, 500, stale config, missing dep, wrong model — fix it immediately. Banned phrases listed in `.claude/rules/00-critical.md`.
3. **100% COMPLETION.** Never defer to "future session". The job is done when every phase done, every toggle flipped, every UI touched, every endpoint verified end-to-end.

## Where to look

| Topic                       | File                                                    |
|-----------------------------|---------------------------------------------------------|
| Critical rules + autonomy   | `.claude/rules/00-critical.md`                          |
| Sprint lifecycle            | `.claude/rules/10-sprint-management.md`                 |
| Git workflow                | `.claude/rules/20-git-workflow.md`                      |
| Docker + restart-policy     | `.claude/rules/30-docker.md`                            |
| Testing + troubleshooting   | `.claude/rules/40-testing.md`                           |
| LLM architecture (Bifrost)  | `.claude/rules/50-llm.md` (path-scoped: backend/** only) |
| Database patterns           | `.claude/rules/60-database.md` (path-scoped: backend/** only) |
| Backend/Frontend/Voice/UX   | `.claude/rules/70-architecture.md`                      |
| Backend-only patterns       | `.claude/rules/path-scoped/backend.md` (lazy)           |
| Frontend-only patterns      | `.claude/rules/path-scoped/frontend.md` (lazy)          |

## Recent architectural shifts (last 30 days)

> Capped at 5 most recent. Older entries archived to `CLAUDE_HISTORY.md` by the weekly curator.

- **Robot/Reachy removal (2026-07-11)** — `refactor: remove Zero Cockpit and robot subsystem` — hard-deleted all Reachy/robot surface (Cockpit, daemon, motion library, teleop, camera, realtime voice) plus `host_agent/`; moved to Zero Studio.
- **Infrastructure pivot (2026-05-17)** — Removed NSSM/autostart. Containers use `restart: unless-stopped`. Legacy scripts moved to `attic/`.
- **Bifrost client + skills registry** — shared LLM gateway at shared-bifrost:4445, skill registry for cross-project discovery
- **OpenHands integration** — autonomous coding agent backbone
- **CI: golden-set carousel V2** — automated testing of the carousel/content flow

## Cross-project

- **Legion** (`c:\code\legion`) — autonomous sprint system at host.docker.internal:8005, source of truth for sprint state
- **ADA** (`c:\code\ADA`) — trading platform
- **Zero** (this project, `c:\code\zero`)
- Shared skills: `general-*`, `deep-review`, `platform-auditor`, `docker-health`, `mesh-coordinator`
- Mesh-coordinator (Agent 0) dispatches skills across all three projects
- Reuse-first culture: check GitHub before building anything new

## Self-update

This file is curated by the `claude-md-curator` skill (cron: weekly Sunday 05:00 UTC).
On-demand: invoke `/claude-md-curator` skill.
The curator audits stale file refs, detects new patterns from recent commits, and proposes updates to `.claude/MEMORY.md`.

## Code intelligence (codegraph) — ALWAYS, never grep code

**Binding rule: every code/symbol question goes through codegraph FIRST — never Grep, never Glob-then-read as the first move.** This applies to ALL source, `.py` AND `.tsx`/`.ts` AND `.js`/`.kt` (the Zero index covers all of them — 23K nodes, 1170 files, tsx + python + typescript indexed). "What/where is symbol X", "who calls X", "what does X call", "blast radius of X", "is X dead", "all references to X", "what's in module/dir Y", and any value-pattern lookup inside source — these are codegraph calls, not Grep. Grep is ONLY for free-text/logs/config/non-code, or a genuine codegraph miss (uncommitted file, index offline, 0 hits). See user-scope `~/.claude/CLAUDE.md` for the full decision tree.

**Subagents inherit this rule.** Every spawned agent (Explore / Plan / general-purpose / executor) MUST be told to use codegraph first, MUST run `mcp codegraph call codegraph_status` as its first codegraph call to warm per-project state, and MUST report `codegraph_tools_used: N` in its final output. `N=0` on a code-symbol task = the subagent failed self-verify.

Self-test before any Grep on code: did I try `codegraph_search` / `codegraph_context` / `codegraph_callers` first? If no, switch to codegraph.

Per-project CLI:

```bash
mcp codegraph call codegraph_status                                # warm-up / health (run first)
mcp codegraph call codegraph_search --arg query=<symbol>           # what/where is X
mcp codegraph call codegraph_context --arg query=<feature-area>    # survey a feature/area
mcp codegraph call codegraph_callers --arg name=<symbol>           # who calls X
mcp codegraph call codegraph_callees --arg name=<symbol>           # what X calls
mcp codegraph call codegraph_impact --arg name=<symbol>            # blast radius of changing X
mcp codegraph call codegraph_files --arg path=<dir>                # what's in a directory
```

For "find all references / is this dead / rename" use serena (LSP): `mcp serena call find_referencing_symbols`. For in-file diagnostics after an edit: `mcp serena call get_diagnostics_for_file`.

## Quick reference

- **Backend health**: `curl http://localhost:18792/health`
- **Sprint DB sync**: Zero's proxy forwards to Legion at host.docker.internal:8005, project_id=7
- **Latest models** (verify, don't cache): Opus 4.7 | Gemini 3.1 Pro/Flash | GPT-5/o-series
- **Vision default**: `gemini-3.1-flash` via LiteLLM (`gemini-flash-latest` alias preferred)
- **Bifrost client**: shared-bifrost:4445 for LLM routing
- **Restart policy**: `restart: unless-stopped` (no autostart, no NSSM)
