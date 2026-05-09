# Plan: ADA — master documentation, audit, and fix-loop (mirrors the Legion audit)

## Context

The user just walked Legion through a full audit cycle: produced a master `docs/LEGION_OVERVIEW.md`, found 9 divergences from the doc, fixed all 9 with passing tests, scheduled a weekly auto-refresh. They want **the same treatment for ADA**.

ADA is a **24/7 financial advisor employee** that manages the user's portfolio. Per the user: it has a weekly planner that produces weekly + daily reports; an orchestration system; calls LLMs; uses scanners for market state + news; "every financial tool available." The user wants:

1. **Confirm whether ADA has all-encompassing master documentation** (like `LEGION_OVERVIEW.md`). If yes, audit reality vs that doc. If no, write one.
2. **Audit the live code** for divergences from that doc — services, agents, scanners, financial integrations, planner system, LLM orchestration, 24/7 mechanism.
3. **Online research** on financial APIs / data tools / news services to identify gaps (anything ADA might be missing).
4. **Record the audit IN ADA** (not in `~/.claude/plans/`). The user does not want to re-write this — it should live with the codebase as a durable, refreshable artifact.
5. **Fix all findings** to closure, with tests, like the Legion run.
6. **24/7 constraint**: ADA cannot go down. Any fix must preserve uptime — feature flags, gradual rollouts, no big-bang restarts where avoidable.

Phase-1 Explore agent already mapped the surface (read-only). Key facts established:

| Item | Value |
|---|---|
| Repo root | `c:\code\ADA\` (backend + frontend monorepo) |
| Backend | FastAPI, Python 3.11+, **911 .py files**, **465 services**, **244 routers**, **61 Alembic migrations** |
| Frontend | React 19 + TS + Vite + pnpm, **86 pages**, 959 .ts/.tsx files |
| Docs (master candidates) | `CLAUDE.md` (27 KB, the de-facto authority), `docs/product/01-overview.md`, `PRODUCT.md`, `ORCHESTRATION_COMPONENTS_SUMMARY.md` |
| Stale docs | `~300 files in .archive/` (sprint reports, old migration guides) |
| 24/7 mechanism | `ADAEmployeeService` (151 KB) + ~15 startup-initialized schedulers (`premium_scanner_scheduler`, `batch_data_scheduler`, `langgraph_checkpoint_scheduler`, `options_hub_scheduler`, `earnings_sync_service`, etc.) — event-driven + WebSocket streaming, NOT cron-interval like Legion |
| Weekly planner system | `WeeklyStrategicPlanService` (Friday 5:30 PM ET v1, Sunday 7:00 PM ET v2) → `weekly_strategic_plans` DB table; `DailyPlannerService` derives daily plan; `EnhancedDailyReportScheduler` produces daily report |
| Docker stack | ada-backend, ada-frontend, ada-redis, ada-qdrant, ada-neo4j, ada-prometheus, ada-grafana, ada-alertmanager, ada-jaeger, ada-firecrawl-playwright, ada-arq-worker, ada-postgres-exporter, ada-init. **PostgreSQL 17 runs natively on host** (migrated out of Docker 2026-03-17). |
| Open questions surfaced by Phase-1 | (a) Only 4 model files found — almost certainly wrong, models live elsewhere. (b) Only 3 agent files found, but docs claim **18 specialized agents** — gap to investigate. (c) No `OVERVIEW.md` analogous to `LEGION_OVERVIEW.md` exists — there is no single all-encompassing system doc. |

**The audit will mirror Legion's, scaled up.** ADA is ~3x Legion's surface area (244 routers vs 70, 465 services vs 159, 86 pages vs 29, 61 migrations vs 41) so the audit takes longer and the master doc will be longer (~700–900 lines vs Legion's 480).

## Approach

Six sequential phases. Each phase produces a durable artifact in ADA. The fix-loop runs after the doc + audit are written, exactly like Legion.

### Phase A — Deep inventory (read-only, ~1 hour)

Spawn 2–3 parallel Explore agents to map subsystems Phase 1 didn't cover:

1. **Financial integrations & scanners** — enumerate every external API: market data (Polygon, Alpaca, IEX, AlphaVantage, Tiingo, Yahoo, Bloomberg, Refinitiv, FactSet), options (Tradier, CBOE, ORATS), news (Benzinga, Marketaux, NewsAPI, Tiingo news, Polygon news), social (Twitter/StockTwits, Reddit/WSB), earnings (Estimize, Earnings Whispers, Visible Alpha), fundamentals (FRED, EDGAR, FMP, Quiver), crypto (CoinGecko, CoinMarketCap, CryptoCompare). For each: file path, env var, current usage. Inventory all `*_scanner.py` / `scanner_*.py` services.
2. **LLM orchestration** — find the LLM router, model registry, fallback chain, cost tracking. Compare against Legion's pattern. Identify which models ADA uses and on what task types.
3. **Agents + the "18 specialized agents"** — locate them. Phase-1 found only 3 in `backend/agents/`; the 18 may live in `openclaw/`, `backend/services/agent_*`, or scattered. Build the actual roster.

### Phase B — Online research (web, ~30 min)

Use WebSearch/WebFetch to enumerate **what financial tooling exists today** in the categories above, focusing on **what ADA might be missing**. Output: a comparison table — "ADA has it" vs "ADA missing it, here's why it'd help (or wouldn't)". Skip premium-only tools the user can't afford (Bloomberg Terminal, Refinitiv full feed) unless their cheaper alternatives are on the missing list.

### Phase C — Write `c:\code\ADA\docs\ADA_OVERVIEW.md` (~1 hour, ~700–900 lines)

Mirror the structure of Legion's master doc (`docs/LEGION_OVERVIEW.md`) but adapted for ADA:

1. Mission (24/7 financial advisor)
2. What ADA actually does (advice loop: scan → analyze → plan → execute or recommend → review → learn)
3. High-level architecture (with diagram)
4. The portfolio (what's tracked, where, schemas)
5. LLM architecture (router, models, costs, providers — is local vLLM in use? cloud-only?)
6. The weekly planner + daily report system (THE biggest recent addition — get this right)
7. Scanners (market scanner, news scanner, options scanner, etc.)
8. Financial integrations (every API, every env var, what data flows from where)
9. Agents (real list, not the doc-claim of 18 if reality is different)
10. 24/7 operation (`ADAEmployeeService`, schedulers, WebSocket streams, ARQ worker)
11. API surface (244 routers, grouped)
12. Frontend (86 pages, grouped)
13. Database (61 migrations, model files, Postgres 17 native + Neo4j + Qdrant)
14. Observability (Prometheus, Grafana, Jaeger, Alertmanager — actual ports)
15. Configuration (every env var)
16. Deployment (Docker compose + native Postgres)
17. Honest current state (an audit-derived score per dimension, like Legion's 38/100)
18. Glossary
19. Deprecated docs (the ~300 files in `.archive/`)

### Phase D — Write `c:\code\ADA\docs\AUDIT_REPORT.md` (~30 min)

Mirror Legion's audit findings table. For each subsystem in Phase C: probe the live system, compare to documented behavior, record divergences. Each finding: severity (CRITICAL / HIGH / MEDIUM / LOW), evidence (curl output, log line, DB row), proposed fix.

Likely divergences to find (informed prediction, will be verified):

- **vLLM / local LLM** — Legion's vLLM is shared with ADA. After the Legion fix (max_model_len 24576→16384, gpu_memory_utilization 0.78→0.72), ADA may also be affected. Verify ADA's LLM transport works.
- **Endpoint paths** — likely `/api/llm/health` not `/llm/health`; same path-mismatch class as Legion.
- **Doc count drifts** — services/routers/pages may not match any internal count.
- **Silent cloud fallback** — does ADA have the same Kimi/MiniMax fallback risk Legion had? Likely yes; the operator directive should apply to ADA too.
- **Failed weekly/daily plans** — the `weekly_strategic_plans` table likely has failures; daily reports likely have gaps.
- **18 agents claim** — verify or correct.
- **Scheduler health** — 15 startup schedulers; some may be stuck like Legion's ProfStudio bug.
- **Observability ports** — Legion's ada-prometheus collision suggests ADA owns port 9090; verify Legion docs are consistent now.

### Phase E — Fix-loop (iterative, no time limit but bounded by "audit findings closed or hit blocker")

Same protocol as Legion run:
1. Pick highest-impact finding from `AUDIT_REPORT.md`.
2. Fix it. Apply via `Edit`.
3. Write a test. Validate via `docker exec ada-backend python -m pytest ...`.
4. `docker cp` the changes into the running container OR rebuild the image (preserve 24/7 by hot-reloading where possible).
5. Re-audit. Update `AUDIT_REPORT.md` with the closure.
6. Loop until no more findings or hit a finding that needs user judgment.

**24/7 constraint enforcement:**
- Use `LEGION_ALLOW_CLOUD_FALLBACK`-style env-var gates for behavior changes that could break uptime.
- Hot-copy code changes (`docker cp`) before rebuilding, so the fix is live before the rebuild risk.
- Do NOT touch the live `weekly_strategic_plans` or `daily_plans` DB rows — read-only against production data unless user approves.
- Schedulers that are stuck or wrong: pause/restart one at a time, verify, then proceed to the next.

### Phase F — Schedule a weekly ADA refresh routine

Mirror the Legion schedule routine. Create `weekly-ada-overview-refresh` cron `0 7 * * 1` (Mon 07:00 UTC, one hour after Legion's so they don't both fire at once). Same shape: re-enumerate counts, refresh §17 (current state) and §19 (deprecated docs) only, open a PR, no-op if no drift.

## Files to be created or modified

**Created (in ADA, durable):**
- `c:\code\ADA\docs\ADA_OVERVIEW.md` — master canonical doc
- `c:\code\ADA\docs\AUDIT_REPORT.md` — point-in-time audit + remediation log

**Modified during fix-loop (will be discovered by audit):**
- `backend/services/unified_llm_service.py` (or ADA's equivalent — Phase A finds the path)
- `backend/services/weekly_strategic_plan_service.py` (if findings require)
- `backend/services/daily_planner_service.py` (if findings require)
- Various router/service files per finding

**Read-only (during planning + during phase A inventory):**
- `c:\code\ADA\CLAUDE.md` — current authoritative source for rules + architecture
- `c:\code\ADA\docs\product\01-overview.md` — product vision
- `c:\code\ADA\docker-compose.yml` — infra source of truth
- `c:\code\ADA\backend\services\ada_employee_service.py` — 24/7 mechanism
- `c:\code\ADA\backend\services\weekly_strategic_plan_service.py` — weekly planner
- `c:\code\ADA\backend\services\daily_planner_service.py` — daily planner
- `c:\code\ADA\backend\services\enhanced_daily_report_scheduler.py` — daily report
- `c:\code\ADA\.claude\memory\topics\` — feature deep-dives

## Lessons applied from the Legion audit

These are policy choices the user implicitly endorsed by accepting the Legion run; carrying them forward:

1. **No "100% test coverage" promise.** Coverage tests only what fixes touch. Legion's project targets 15%; ADA's likely similar. Writing 1500+ tests for 465 services is weeks of work, not a session.
2. **No "all UI text matches backend" sweep.** Fix UI text divergence opportunistically when it's adjacent to a backend fix; don't do a separate UI walk in this audit.
3. **Honest current-state score.** ADA gets a 0–100 score per dimension in §17 of the master doc, computed from real metrics. No aspirational numbers.
4. **Endpoint path verification.** Every doc'd path gets a `curl` smoke test in the audit.
5. **Silent cloud fallback gate.** If found, gate behind `ADA_ALLOW_CLOUD_FALLBACK` env var, default off — same pattern as Legion's `LEGION_ALLOW_CLOUD_FALLBACK`.
6. **GPU/vLLM constraints are shared.** Legion's vLLM fix (lower max_model_len, lower gpu_memory_utilization) already affects ADA. No further GPU work without confirming ADA's needs.
7. **Spontaneous-fire verification rule.** New code paths must fire within ~60s of restart in a busy system. Don't wait for hourly cycles.
8. **Pre-existing test failures are not regressions.** ADA likely has dozens; document the count, don't fix them in this audit.

## Verification

End-to-end checks before declaring success:

1. `c:\code\ADA\docs\ADA_OVERVIEW.md` exists, ~700–900 lines, all 19 sections present, all counts match live code.
2. `c:\code\ADA\docs\AUDIT_REPORT.md` exists, every finding has severity + evidence + closure status.
3. Every fix has at least one passing test (`docker exec ada-backend python -m pytest tests/...`).
4. Live LLM call: `curl -X POST http://localhost:8006/api/llm/generate -d '{...}'` returns a response from the documented model + provider.
5. Live weekly planner trigger: `curl -X POST http://localhost:8006/api/planner/weekly/generate` produces a plan that lands in `weekly_strategic_plans` table.
6. Live daily report trigger: `curl http://localhost:8006/api/planner/daily/today` returns the day's plan.
7. ADA stayed up throughout (24/7 constraint): `docker inspect ada-backend --format '{{.RestartCount}}'` did not increase by more than necessary for one rebuild.
8. Master doc + audit committed to ADA's git repo as a single PR (or per-fix series of small PRs).
9. Weekly refresh routine registered, manually fired once, no-op result confirmed.
10. Re-audit: fewer findings remain than the initial audit, OR all critical/high findings closed (medium/low can carry over with explicit deferral notes).

## Out of scope (explicit non-goals)

- Rebuilding any subsystem from scratch.
- Adding new financial APIs (Phase B research informs future sprints; no new integrations land in this audit).
- Editing `CLAUDE.md`, `docs/product/01-overview.md`, or `PRODUCT.md` (those are authored by the user). The new master doc is `docs/ADA_OVERVIEW.md`.
- Touching `.archive/` deprecated docs.
- Frontend rework — only fix UI text where it's adjacent to a backend fix that changes user-facing strings.
- Migrating PostgreSQL back into Docker.
- Reorganizing the 244 routers or 465 services. Consolidation is its own multi-sprint roadmap, not this audit.

## Sequencing claim

Phase A → B → C → D → E → F is the right order and should not be reordered. Specifically:

- **A before C**: writing the master doc without the deep inventory produces another aspirational doc. Phase A grounds it.
- **B before C**: research informs §8 (financial integrations) of the master doc — knowing what's missing changes how the section is framed.
- **D before E**: fix-loop without an audit list devolves into unbounded scope. The audit report is the kill criterion.
- **E before F**: scheduling a weekly refresh of a doc that's known to be wrong just propagates wrong-ness. Get the doc right, then automate its maintenance.

Estimate: Phase A ~1h, Phase B ~30 min, Phase C ~1h, Phase D ~30 min, Phase E variable (1–4h depending on findings), Phase F ~5 min. Total: 3–6 hours of work, single session feasible if the fix-loop is bounded.
