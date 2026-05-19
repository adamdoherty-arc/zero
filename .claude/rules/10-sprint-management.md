# 10 — Sprint management (always loaded)

Legion (the agentic management system at `host.docker.internal:8005`) is the single source of truth for Zero sprints. Zero's `/api/sprints/*` API forwards lifecycle writes to Legion. Each sprint also gets a living markdown doc auto-rendered to `/vault/legion/Sprints/<hub>/<NN>-<slug>.md`.

Zero's `project_id` in Legion is **7** (`Zero Personal Assistant`). Verified 2026-05-17 — `backend/app/infrastructure/config.py:53` was previously hardcoded to 8 (wrong); now corrected.

## When to open a Sprint vs make a plain commit

A **Sprint** is required for:
- New feature (router, service, agent, voice flow, Reachy capability)
- Enhancement to existing feature (new endpoints, UI surfaces, daily-brief sections, etc.)
- Refactor that crosses ≥3 files or changes a public surface
- Migration (Alembic schema changes, dep major bumps, vault layout changes)
- Anything described as "build / wire / add / extend / overhaul"

A **plain commit** (no Sprint) is fine for:
- Pure bug fix for a regression (something that was working broke)
- Single-file typo / log-level / config tweak
- Doc-only edits to existing pages

Rule of thumb: if it would have a `Goal`, it's a Sprint.

## Naming convention (matches Legion's taxonomy)

`{Category}-NN: Description` — Category ∈ {`Feature`, `Enhancement`, `Refactor`, `Migration`, `Perf`, `Fix`}.

## The five-step lifecycle (mandatory)

**Step 1 — Plan.** Scratch plan in `~/.claude/plans/<slug>.md`. Disposable.

**Step 2 — Create.** POST to Zero's API (proxies to Legion, project_id=7):
```bash
curl -X POST http://localhost:18792/api/sprints \
  -H "Content-Type: application/json" \
  -d '{"name":"Feature-NN: Title","goal":"One-sentence statement","planned_points":5}'
```

**Step 3 — Add tasks.** One per atomic unit:
```bash
curl -X POST http://localhost:18792/api/sprints/{id}/tasks \
  -d '{"title":"...","category":"feature","priority":3,"story_points":3,
       "files_affected":["backend/app/services/..."],"acceptance_criteria":["..."]}'
```

**Step 4 — Move tasks** as work progresses (`in_progress` → `done`):
```bash
curl -X POST http://localhost:18792/api/sprints/tasks/{tid}/move \
  -d '{"status":"in_progress"}'
```

**Step 5 — Complete with retrospective.** `POST /complete` REJECTS with 422 if any of the five retro fields is missing — hard gate, not advisory. Required fields: `goal` (string), `work_completed` (list of `{task_id,title,files[],verified}`), `testing` (`{regression_status, tests_added[], smoke_verified}`), `improvements_found` (list), `deferred` (list — MUST be empty unless a "Fix on sight" carve-out applies).

### `deferred` carve-outs (reconciles with Fix-on-sight)

`deferred` is allowed ONLY for:
- Hard external blocker (vendor API not live, hardware unplugged, paid SaaS with no key)
- Genuinely irreversible destructive action that needs explicit confirmation

Each `deferred` entry MUST be `{"item": "...", "reason": "..."}` and the reason MUST quote which carve-out applies. The retro gate rejects string-only entries.

## Banned shortcuts (hard gates)

- **Don't skip Step 2.** A feature commit without an associated `/api/sprints` row violates policy.
- **Don't commit without moving tasks.** Tasks must be moved to `in_progress` before code, `done` after verify.
- **Don't bypass the retro gate.** `?force=true` on `/complete` is logged for audit and is reserved for emergency cleanup, not normal completion.

## Where to look

- **Live sprint state**: `GET http://localhost:18792/api/sprints/{id}` (Legion-backed)
- **Human-readable doc**: `/vault/legion/Sprints/<hub>/<NN>-<slug>.md` (auto-rendered)
- **Legion dashboard**: `http://localhost:8005/sprints/{id}` for the cross-project view
- **Direct Legion API** (scripts): `http://localhost:8005/api/sprints/?project_id=7&source_system=zero`
