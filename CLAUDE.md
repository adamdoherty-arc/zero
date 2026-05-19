# Zero — Claude Code Operating Rules

> This file is the always-loaded baseline. Topic-specific rules live in `.claude/rules/`. Active learnings tracked in `.claude/MEMORY.md`.
> Updated weekly by the `claude-md-curator` skill.

## What Zero is

Zero is a **personal assistant + Reachy voice UX + autonomous research/trading + content-loop** project. Python/FastAPI backend + React/Vite frontend, PostgreSQL, shared LiteLLM for cross-project LLM infra, Bifrost client at shared-bifrost:4445 for routing. Sprints sync to **Legion** (the management system at host.docker.internal:8005) — Zero's `project_id` in Legion is **7** (corrected 2026-05-17 from previous 8).

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
| LLM architecture (Bifrost)  | `.claude/rules/50-llm.md`                               |
| Database patterns           | `.claude/rules/60-database.md`                          |
| Backend/Frontend/Voice/UX   | `.claude/rules/70-architecture.md`                      |
| Backend-only patterns       | `.claude/rules/path-scoped/backend.md` (lazy)           |
| Frontend-only patterns      | `.claude/rules/path-scoped/frontend.md` (lazy)          |
| Reachy + voice + realtime   | `.claude/rules/path-scoped/reachy.md` (lazy)            |

## Recent architectural shifts (last 30 days)

- **OpenHands integration** — `feat: OpenHands integration` — autonomous coding agent backbone
- **Bifrost client + skills registry** — `feat: Bifrost client + skills registry` — shared LLM gateway at shared-bifrost:4445, skill registry for cross-project discovery
- **openhuman adoption** — `feat: openhuman adoption` — human-in-the-loop pattern for sensitive autonomous actions
- **Reachy phases 1-8** — `feat(reachy): ship phases 1-8` — voice UX with realtime, robot interaction, character content
- **Infrastructure pivot (2026-05-17)** — Removed all autostart logic, NSSM service, scheduled tasks. Containers use `restart: unless-stopped`. Legacy autostart scripts moved to `attic/`. User-launched UI replaces scheduled jobs.
- **vLLM provider refactor + realtime config** — backend refactor, realtime LLM routing config
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

## Quick reference

- **Backend health**: `curl http://localhost:18792/api/health`
- **Sprint DB sync**: Zero's proxy forwards to Legion at host.docker.internal:8005, project_id=7
- **Latest models** (verify, don't cache): Opus 4.7 | Gemini 3.1 Pro/Flash | GPT-5/o-series
- **Vision default**: `gemini-3.1-flash` via LiteLLM (`gemini-flash-latest` alias preferred)
- **Bifrost client**: shared-bifrost:4445 for LLM routing
- **Restart policy**: `restart: unless-stopped` (no autostart, no NSSM)
