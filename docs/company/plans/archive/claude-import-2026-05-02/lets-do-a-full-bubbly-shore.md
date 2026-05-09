# Ecosystem audit + "Legion as meta-architecture owner" — 2026-04-28

## Context

Adam invoked `/ecosystem-audit` with three layered asks:

1. **Full review** of the three-pillar ecosystem against the 12-week plan
   (`review-the-two-lively-cascade.md`) and the canonical docs
   (`c:\code\ArchitectureMaster\docs\`).
2. **Per-project blockers** for the three things he is actively trying to ship:
   - **Ada** — daily/weekly reports that "look to not be happening."
   - **Zero** — Sally (personal companion) added, carousel pipeline reinforced,
     trying to actually publish content; new MCP servers just stood up so
     Zero can navigate his projects.
   - **Legion** — big code update (the llm_ops birth), needs to actually start
     doing its job: headless project ops, cross-project improvement,
     dependency updates, and being the API/MCP backbone Zero calls into.
3. **A new structural change**: make this audit (and the meta-architecture
   itself) a **first-class project inside Legion**, so the canonical docs in
   `c:\code\ArchitectureMaster\docs\` are owned by Legion, updated by Legion's
   subgraphs, and published as a **daily architecture report**. Today the
   audit lives in this skill; the user wants Legion to take it over.

This run is the **first ever** invocation of the ecosystem-audit skill — the
state directory does not exist. So this run also bootstraps the baseline.

Plan-mode constraint: this run **cannot execute** anything. It writes the plan,
captures the findings inline (so they don't get lost), and on approval the
follow-up run will execute the auto-heal whitelist + scaffold the new Legion
project.

---

## Findings — what's actually true on disk today (2026-04-28)

### Ada — `c:\code\ADA`

| Check | Result |
|---|---|
| Mandate parity | ✅ Verbatim match against `docs/MANDATE.md` |
| Daily-briefing scheduler | Exists at [backend/services/daily_briefing_scheduler.py](c:/code/ADA/backend/services/daily_briefing_scheduler.py); started in `main.py:1263–1270` |
| Enhanced post-market report scheduler | Exists at [backend/services/enhanced_daily_report_scheduler.py](c:/code/ADA/backend/services/enhanced_daily_report_scheduler.py); started in `main.py:1481–1482` (5:30 PM ET weekdays) |
| **Why reports aren't firing** | (1) APScheduler is **in-memory** (`AsyncIOScheduler`, no `SQLAlchemyJobStore`), so every backend restart wipes the cron jobs. (2) Both `start_*` calls are inside broad `try/except Exception` swallowers, so init failures log but don't surface. (3) No code path writes report output to the vault — output goes to the database only |
| `interrupt()` gate on live orders | ❌ **MANDATE violation.** [backend/routers/broker_orders.py:262–306](c:/code/ADA/backend/routers/broker_orders.py#L262-L306) gates only on `os.getenv("ROBINHOOD_PAPER_TRADING")`. No LangGraph `interrupt()`. With `ROBINHOOD_PAPER_TRADING=false`, `order_service.sell_cash_secured_put()` runs unattended |
| `ada-mcp` | Not built. Stage-2 work per the 12-week plan |
| Recent activity (30d) | weekly-planner skill, theta advisor improvements, confidence-bias learning. **No commits to broker code, live-order gates, or report scheduling** |

### Zero — `c:\code\zero`

| Check | Result |
|---|---|
| Mandate parity | ✅ Verbatim match |
| **Sally (personal companion)** | ✅ Wired. Persona at [backend/app/data/reachy_profiles/sally/character.json](c:/code/zero/backend/app/data/reachy_profiles/sally/character.json), routes to `qwen3-heretic-9b` (local), integrated into Reachy voice loop, vault writes go through `vault_writer_service.py` |
| **Carousel pipeline (V2)** | Feature-complete: 12-stage Temporal workflow at [backend/app/workflows/carousel_workflow.py](c:/code/zero/backend/app/workflows/carousel_workflow.py); recent overhaul commits 2026-04-15 → 2026-04-17 |
| **Why carousel can't publish** | 🔴 **Missing TikTok OAuth creds.** `ZERO_TIKTOK_CLIENT_KEY` and `ZERO_TIKTOK_CLIENT_SECRET` not in `c:\code\zero\.env`. [activities/publish.py:101](c:/code/zero/backend/app/workflows/activities/publish.py#L101) defaults `ZERO_TIKTOK_DRY_RUN=true`, returns mock `dryrun-…` publish IDs |
| MCP servers | ✅ Two stood up at [c:/code/zero/mcp_servers/](c:/code/zero/mcp_servers/): `zero_api_mcp.py` (48 tools — sprints, vault search, tiktok pipeline, scene description) and `kimi_mcp.py` (5 Kimi delegation tools). Both stdio. Registered in `c:\code\.mcp.json` |
| Vault writer choke point | ✅ [backend/app/services/vault_writer_service.py](c:/code/zero/backend/app/services/vault_writer_service.py) intact; enforces `00_Meta/_agent/**`, audit footers, partition tags |
| Recent activity (30d) | Reachy waves 1–17 (8 commits, 100 motion clips, 12 personas), content brain v2, vision/observability |

### Legion — `c:\code\Legion`

| Check | Result |
|---|---|
| Mandate parity | ✅ Verbatim. Note: mandate text says llm-ops is "to be created"; it was created 2026-04-24 — phrasing now stale |
| **The big code update** | Commit `123d4d76` (2026-04-24): **llm_ops subgraph birth** — +42 files, 3,922 insertions. Adds [backend/app/agents/llm_ops/](c:/code/Legion/backend/app/agents/llm_ops/) with `LLMStackMonitorAgent`, `ModelResearcherAgent`, `LLMResponseCuratorAgent`, `LLMReportGeneratorAgent`, `LLMOpsPlannerAgent`. Also: dependency scanner hardening (3 commits), audit/safety fixes (commit `9e648f90`, 12 files). Continuous nightly auto-syncs (244 files across 6 commits) |
| `legion-mcp` | ✅ Operational at [c:/code/Legion/mcp_servers/legion_mcp.py](c:/code/Legion/mcp_servers/legion_mcp.py); registered in `c:\code\.mcp.json` |
| MANAGED_PROJECTS registry | At [backend/app/core/legion_config.py:71–176](c:/code/Legion/backend/app/core/legion_config.py#L71-L176): `ada`, `fortressos`, `legion`, `zero`, `aicontenttools`, `profstudio`. All `auto_learn: True` except `aicontenttools` |
| Headless project ops | Infrastructure exists (`autonomous_executor.py`, `script_executor.py`, `async_subprocess.py`). **No evidence in logs/vault/DB that any cross-project change has been auto-shipped** |
| Dependency updater | [dependency_scanner_daemon.py](c:/code/Legion/backend/app/services/dependency_scanner_daemon.py) wired in `main.py:1073–1082` with 24h interval. Hardened 2026-04-24. **Creates remediation sprints but those sprints aren't auto-executed** |
| **llm_ops scheduler** | 🔴 [backend/app/scheduler/llm_ops_jobs.py](c:/code/Legion/backend/app/scheduler/llm_ops_jobs.py) defines 7 cron jobs (monitor `:05` hourly, researcher `08:10 UTC` daily, curator `:15` hourly, report `08:30`, planner `08:40`). `register_llm_ops_jobs()` is **NOT called from `main.py` startup** — only from the CLI at `app/cli/llm_ops.py:88–92`. **Jobs don't auto-start.** Mandate's "every 5 min health" and "03:00 ET research" cadences are not implemented |
| Swap proposals | Two filed (`model-swap-qwen3.6-27b-dense.md`, `model-swap-qwen3.6-moe.md`), both "open", both written by the audit skill — not by llm_ops |

### Skill state

- `state/ecosystem-audit/` does not exist. Lib files are present and current.
- This is a true first run. Need to scaffold INSIGHTS / ACTION_QUEUE / EVOLUTION
  / runs / research / baseline.

### Cross-cutting patterns

1. **Schedulers exist, schedulers don't fire.** Three independent
   confirmations (Ada daily reports, Legion llm_ops, Legion remediation
   sprints). All three have the same root pattern: code is shipped,
   `register_*_jobs` not called at startup, no runtime visibility into the
   silence.
2. **No "did the daemon actually run?" surface.** Nothing writes to vault,
   Discord, or even a dashboard table when a scheduled job runs successfully.
   Failures are swallowed by broad try/except.
3. **The active 12-week plan's "Status" section claims Stage 0 shipped.** It
   did. But Stage 1+ is not happening because the daemons that would do it
   aren't started.

---

## What this run will do (after approval)

### Self-heal whitelist (Phase H — auto, no further approval)

Tier `write_local`, all to local skill state and local vault `_agent/` namespace.

1. **Scaffold skill state** at `c:\code\ArchitectureMaster\.claude\skills\ecosystem-audit\state\ecosystem-audit\`:
   - `INSIGHTS.md` (with Run 1 baseline header + the cross-cutting pattern above)
   - `ACTION_QUEUE.md` (populated with the queued items below)
   - `EVOLUTION.md` (empty placeholder)
   - `runs/2026-04-28-<HHMM>.md` (this run's report)
   - `research/{models,pkm,desktop-control,supply-chain}/` (created with .gitkeep)
   - `baseline/snapshot-2026-04-28.json` (mandate-quote SHA-256s, port table,
     `docker ps`, `:4444/v1/models` if reachable)
2. **Scaffold the new Legion project files** under `c:\code\Legion\projects\architecture-master\` (NEW directory, agent-owned). See "New work" below.
3. **Mirror canonical docs into the new Legion project** (read-only copies, not moves — original `c:\code\ArchitectureMaster\docs\` stays). The mirror lives at `c:\code\Legion\projects\architecture-master\docs\` and gets refreshed each daily run.
4. **Vault propose: Legion as architecture owner** — write a proposal to `c:\code\vault\ObsidianZero\00_Meta\_agent\proposals\2026-04-28-legion-architecture-project.md` describing the takeover.
5. **Update the active plan's Status section** in `C:\Users\hadam\.claude\plans\review-the-two-lively-cascade.md` only to add an inline note: "Stage 1+ daemons present but not auto-registered — see `lets-do-a-full-bubbly-shore.md`." No structural changes to the plan.

### Queued (Phase H — `write_external`, requires human approval)

The audit will write these to `ACTION_QUEUE.md` with severity, location, and
suggested fix. No code edits. They become work items for the next
non-plan-mode session — many of them are the heart of "Legion needs to start
doing its job."

| # | Tier | Item | Where | Severity |
|---|---|---|---|---|
| Q1 | `write_external` | **Auto-register `register_llm_ops_jobs()` at Legion startup** | [Legion/backend/app/main.py](c:/code/Legion/backend/app/main.py) startup lifespan | high |
| Q2 | `write_external` | **Move Ada APScheduler to `SQLAlchemyJobStore`** so daily/weekly reports survive restarts | [ADA/backend/services/daily_briefing_scheduler.py](c:/code/ADA/backend/services/daily_briefing_scheduler.py), [ADA/backend/services/enhanced_daily_report_scheduler.py](c:/code/ADA/backend/services/enhanced_daily_report_scheduler.py) | high |
| Q3 | `write_external` | **Pipe Ada daily/weekly report output to vault** through Zero's `vault_writer_service` MCP — not direct filesystem write | new code in Ada services; uses `zero_api_mcp` | high |
| Q4 | `financial` (top tier) | **Replace env-var gate with `interrupt()` in `broker_orders.py`** before any live `place_*_order` path | [ADA/backend/routers/broker_orders.py:262–306](c:/code/ADA/backend/routers/broker_orders.py#L262-L306) | **critical** |
| Q5 | `write_external` | **Add TikTok OAuth creds + flip dry-run off** to unblock first carousel publish | `c:\code\zero\.env` (creds), [activities/publish.py:101](c:/code/zero/backend/app/workflows/activities/publish.py#L101) | high (Adam-blocking) |
| Q6 | `write_external` | **Wire Legion remediation-sprint auto-execution** behind the existing approval middleware (so `dependency_scanner_daemon` actually closes the loop) | `Legion/backend/app/services/autonomous_executor.py` + new approval routing | medium |
| Q7 | `write_external` | **Add a "did this daemon run?" heartbeat surface** — every supervised daemon writes its last-run timestamp + status to a Postgres `daemon_heartbeats` table; Legion `/api/daemon-status` reads it; vault daily note `## System Health` block reads it via the morning brief | new table migration + tiny middleware in `supervised_daemon.py` | medium |
| Q8 | `write_external` | **Fix llm_ops cron timezones** — mandate says ET, code uses UTC. Either convert or document the offset | [Legion/backend/app/scheduler/llm_ops_jobs.py](c:/code/Legion/backend/app/scheduler/llm_ops_jobs.py) | low |
| Q9 | `write_external` | **Refresh Legion mandate prose** — "to be created" → "running since 2026-04-24" for llm_ops | `Legion/MANDATE.md` | low |
| Q10 | `write_external` | **Run `register_morning_brief.ps1` + `install-services.ps1` as Administrator** + reboot to close the Stage 0 verification gate | already-shipped scripts | high |

The audit explicitly does NOT auto-apply any of Q1–Q10. Q4 is `financial`-tier
and never originates from Legion or this skill.

---

## New work — make Legion the meta-architecture owner

This is the structural change Adam asked for. Today the canonical docs live in
`c:\code\ArchitectureMaster\docs\` and the audit runs out of a Claude Code skill.
The user wants Legion to own this loop.

### Approach (recommended)

**Mirror, don't move.** `c:\code\ArchitectureMaster\docs\` stays as the
source-of-truth (the plan-mode-friendly editable copy that humans edit). Legion
gets a read-mirror + a daily refresh job + a daily report. This is reversible,
keeps the existing plan workflow intact, and gives Legion the operational
ownership without making the docs a Legion-internal artifact you can't grep
from outside.

The reason to **not move** the docs into Legion:
- Today the docs are reachable from any project (Zero, Ada, this skill, future
  agents). Burying them inside Legion's repo would force every consumer
  through a Legion call.
- The active 12-week plan in `~/.claude/plans/` already references
  `c:\code\ArchitectureMaster\docs\` paths.
- If Legion is down, the canonical architecture should still be readable.

### New files (all auto-scaffolded by this run)

```
c:\code\Legion\projects\architecture-master\
  README.md                 — what this project is
  config.yml                — schedule (daily 06:30 ET), source dir, output paths
  docs/                     — mirror of c:\code\ArchitectureMaster\docs\
                              (refreshed each run; SHA-256 manifest committed)
  reports/
    daily/<YYYY-MM-DD>.md   — daily architecture report
    weekly/<YYYY-W##>.md    — weekly synthesis (Sunday)
  manifest.json             — last refresh timestamp, source SHAs, drift flags
```

The new project also gets registered in
[Legion/backend/app/core/legion_config.py](c:/code/Legion/backend/app/core/legion_config.py)
`MANAGED_PROJECTS` as `architecture-master` with `auto_learn: True`,
`legion_may_pr: False` (it's a doc project, not a code project), and a custom
`tier: meta` flag the lib registry can use to skip its dependency scan.

### The daily architecture report

Generated by a new Legion subgraph `architecture_master` (sibling to
`llm_ops`), scheduled at **06:30 ET** so it lands before the morning brief
reads `## System Health`.

Daily report contents (one markdown file per day):
1. **TL;DR** (5 lines max)
2. **Doc drift since yesterday** — diff `docs/MANDATE.md`, `docs/ARCHITECTURE.md`,
   `README.md` SHA-256s against `manifest.json`. Flag any change.
3. **Project mandate parity** — Zero/Legion/Ada `MANDATE.md` blockquotes vs canonical
4. **Daemon heartbeat status** — pulls from `daemon_heartbeats` table (Q7 above
   needs to ship first; until then, this section reads "blocked on Q7")
5. **Plan progress** — read `~/.claude/plans/review-the-two-lively-cascade.md`
   and surface checkbox state changes vs yesterday's manifest
6. **Open queue** — count of items in `ACTION_QUEUE.md` by tier
7. **Footer** — `<!-- agent-run-id: ... source: architecture-master at: ... -->`

Output goes to **two surfaces**:
- `c:\code\Legion\projects\architecture-master\reports\daily\<date>.md` (canonical archive)
- `c:\code\vault\ObsidianZero\00_Meta\_agent\architecture\<date>.md` (vault — read-only for humans)
- A 3-bullet summary appended to today's daily note `## Architecture` block via `vault_writer_service` MCP

### Migration of the audit skill into Legion (eventual — not today)

Today: this skill (`ecosystem-audit`) keeps running from Claude Code at user-invocation. It writes to its own `state/` directory.

In ~2 weeks (after Q1, Q7, and the `architecture_master` subgraph ship):
- Move the skill's auto-heal logic into Legion's `architecture_master` subgraph.
- Skill becomes a thin entry point that calls `legion-mcp` `audit.run()`.
- All findings, queue, insights, runs move to Postgres tables under the
  `legion` DB.
- Vault output stays where it is.

This isn't part of today's plan — it's queued as a future-state pointer in `EVOLUTION.md`.

---

## Plans-in-Legion (the third part of the user's ask)

User wants "the plans in the docs folder should be in Legion as Legion should
eventually take this over and needs to run daily to report on."

The docs the user means:
- `c:\code\ArchitectureMaster\docs\MANDATE.md`
- `c:\code\ArchitectureMaster\docs\ARCHITECTURE.md`
- `c:\code\ArchitectureMaster\docs\AgenticOs.md` (50KB+ strategy doc)
- `c:\code\ArchitectureMaster\docs\SecondBrain.md` (50KB+ strategy doc)

The active 12-week plan is at `C:\Users\hadam\.claude\plans\review-the-two-lively-cascade.md`
— this is owned by Adam's plans dir, not the docs folder. We mirror it into
the new Legion project's `plans/` subdirectory so the daily report can
diff plan checkbox state, but **we do not move it** out of `~/.claude/plans/`
because the plan workflow is what keeps it editable.

Result: Legion now has read-access to all four canonical docs + the active plan,
runs a daily diff against them, and reports on changes. Adam keeps editing
both the docs (in `c:\code\ArchitectureMaster\docs\`) and the plan
(in `~/.claude/plans/`) the same way he does today.

---

## Critical files to read on the next (execution) run

- [c:/code/Legion/backend/app/main.py](c:/code/Legion/backend/app/main.py) — find the lifespan block where `register_llm_ops_jobs` belongs
- [c:/code/Legion/backend/app/scheduler/llm_ops_jobs.py](c:/code/Legion/backend/app/scheduler/llm_ops_jobs.py) — the function that needs to be called
- [c:/code/Legion/backend/app/core/legion_config.py](c:/code/Legion/backend/app/core/legion_config.py) — `MANAGED_PROJECTS` registration site
- [c:/code/ADA/backend/services/enhanced_daily_report_scheduler.py](c:/code/ADA/backend/services/enhanced_daily_report_scheduler.py) — APScheduler init (needs `SQLAlchemyJobStore`)
- [c:/code/ADA/backend/routers/broker_orders.py](c:/code/ADA/backend/routers/broker_orders.py) — the `interrupt()` insertion point (Q4 only)
- [c:/code/zero/.env](c:/code/zero/.env) — TikTok credential gap
- [c:/code/zero/backend/app/workflows/activities/publish.py](c:/code/zero/backend/app/workflows/activities/publish.py) — dry-run flag

---

## Verification (how to know this worked)

After the execution run completes:

1. **Skill state exists.** `ls c:/code/ArchitectureMaster/.claude/skills/ecosystem-audit/state/ecosystem-audit/` returns INSIGHTS.md, ACTION_QUEUE.md, EVOLUTION.md, runs/, research/, baseline/.
2. **Run report on disk.** `c:\code\ArchitectureMaster\.claude\skills\ecosystem-audit\state\ecosystem-audit\runs\2026-04-28-*.md` exists and has the audit footer.
3. **New Legion project exists.** `ls c:/code/Legion/projects/architecture-master/` returns `README.md`, `config.yml`, `docs/`, `reports/`, `manifest.json`.
4. **Vault proposal filed.** `c:\code\vault\ObsidianZero\00_Meta\_agent\proposals\2026-04-28-legion-architecture-project.md` exists, has audit footer, status `open`.
5. **ACTION_QUEUE.md has 10 items.** Q1–Q10 from the table above, each with severity, file path, and suggested fix.
6. **No code edited in zero/, Legion/, ADA/ backends.** `git status` in each repo shows no working-tree changes from this skill (the new file under `Legion/projects/architecture-master/` is the only addition; Legion's `MANDATE.md` is **not** auto-edited despite Q9 — that's queued).
7. **Sanity diff.** Run `diff c:/code/ArchitectureMaster/docs/MANDATE.md c:/code/Legion/projects/architecture-master/docs/MANDATE.md` — should be identical.
8. **Manifest.** `c:\code\Legion\projects\architecture-master\manifest.json` records SHA-256 of each mirrored doc + the run UUID.

After the next morning (06:30 ET), additionally:
- A daily report at `Legion/projects/architecture-master/reports/daily/2026-04-29.md`
- A `## Architecture` block in that day's vault daily note (3 bullets)

If verification 1–7 don't pass after one execution turn, the skill has bugs
and the queue items remain unaddressed.

---

## Out of scope (deliberately not in this plan)

- Editing any code under `zero/backend`, `Legion/backend`, `ADA/backend`. All
  ten queued items require a separate non-plan session.
- Touching `.obsidian/` config (community-plugins.json, etc.). Plugin
  proposals are part of the routine Phase D pass; nothing missing today
  warrants escalating ahead of Q1–Q10.
- Anything financial-tier. Q4 (the `interrupt()` gate) is queued for human
  review and explicit confirm — never auto.
- `docker compose up/down/restart`. The audit observes; it never restarts.
- Pushing or PR'ing anything. No `git push`, no `gh pr create`.

<!-- agent-run-id: 2026-04-28-plan-mode source: ecosystem-audit at: 2026-04-28T-plan-mode -->
