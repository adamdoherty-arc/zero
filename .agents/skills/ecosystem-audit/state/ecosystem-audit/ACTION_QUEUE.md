# Action queue

Items requiring `write_external` or `financial` tier â€” never auto-applied by
this skill. Each item is queued by an audit run and dequeued when the
corresponding code lands. Items are dedupd across runs by `id`.

Format:

```
### Q<n> â€” <title> [<tier>] [<severity>]
- **Source run**: <date>
- **Where**: <file:line> or <path>
- **Suggested fix**: <one paragraph>
- **Status**: open | in-progress | resolved | wont-fix
```

---

### Q1 â€” Auto-register `register_llm_ops_jobs()` at Legion startup [write_external] [high]

- **Source run**: 2026-04-28
- **Where**: [c:/code/Legion/backend/main.py](c:/code/Legion/backend/main.py) lifespan, after `scheduler_service.schedule_daily_prompts()`
- **Resolved 2026-04-28**: Edited `Legion/backend/main.py` to import and call `register_llm_ops_jobs(scheduler_service)` immediately after `scheduler_service.schedule_daily_prompts()`. Errors are caught and logged but don't crash startup. **Verified live 2026-04-28**: `legion-backend` restarted; stdout shows `[OK] LLM-Ops jobs registered (7): llm_ops.monitor.hourly, llm_ops.curator.hourly, llm_ops.monitor.daily, llm_ops.researcher.daily, llm_ops.curator.daily, llm_ops.report.daily, llm_ops.planner.daily`. Hourly monitor + curator will fire at the next `:05` and `:15` of the hour.
- **Status**: resolved + verified live

### Q2 â€” Move Ada APScheduler to `SQLAlchemyJobStore` [write_external] [high]

- **Source run**: 2026-04-28
- **Where**: [c:/code/ADA/backend/services/enhanced_daily_report_scheduler.py](c:/code/ADA/backend/services/enhanced_daily_report_scheduler.py) â€” APScheduler in-memory.
- **Resolved 2026-04-28**: Edited `enhanced_daily_report_scheduler.py` to import `SQLAlchemyJobStore` and `get_database_url`, added a `_build_sync_db_url()` helper that strips `+asyncpg` so APScheduler can use psycopg2, and instantiated the scheduler with `jobstores={"default": SQLAlchemyJobStore(...)}` (table `ada_apscheduler_jobs`). Falls back to in-memory if the DB URL is unreachable. Also refactored job target from a bound method (`self._generate_enhanced_report`) to a string reference (`"...:_run_enhanced_report_job"`) because SQLAlchemyJobStore pickles its target and bound methods drag in the unpicklable `AsyncIOScheduler`. **Note**: `daily_briefing_scheduler.py` does not use APScheduler â€” it's a DIY async loop with persistent state via `notification_coordinator`, so survival across restarts is already handled. **Verified live 2026-04-28**: `ada_apscheduler_jobs` table exists in `adam` DB; row `enhanced_daily_report` persisted with `next_run_time=1777498200` (2026-04-29 17:30 ET, today's 5:30 PM has passed). Job will survive `ada-backend` restarts. **Side-fix while activating**: `backend/services/daily_report_rag_indexer.py` had a stale import `from src.rag.agentic_rag import AgenticRAG, get_rag` â€” the symbols are actually `AgenticRAGOrchestrator` and `get_agentic_rag`. Fixed via aliased import; this had been silently breaking the scheduler init for weeks (the real reason "schedulers shipped, schedulers didn't fire").
- **Status**: resolved + verified live

### Q3 â€” Pipe Ada daily/weekly report output to vault [write_external] [high]

- **Source run**: 2026-04-28
- **Where**: [c:/code/ADA/backend/services/enhanced_daily_report_scheduler.py](c:/code/ADA/backend/services/enhanced_daily_report_scheduler.py)
- **Resolved 2026-04-28**: Added `_format_briefing_for_vault()` (markdown rendering) and `_post_report_to_vault()` (httpx POST to Zero's `POST /api/vault/propose`). Hooked into `_generate_enhanced_report()` as a non-blocking `asyncio.create_task` so vault outages can't break the trading flow. Lands at `00_Meta/_agent/trading/<YYYY-MM-DD>-daily.md` (the agent-owned namespace, no whitelist needed). **Verified live 2026-04-28**: `ZERO_GATEWAY_TOKEN` and `ZERO_API_URL` added to `c:\code\ADA\.env` and wired into `docker-compose.yml` `backend.environment` block. Smoke-test invocation produced `vault_post_succeeded rel_path=00_Meta/_agent/trading/2026-04-28-daily.md`; file present on disk and contains the rendered markdown with audit footer. Vault-write failures still log-and-skip rather than crashing the trading flow.
- **Status**: resolved + verified live

### Q4 â€” Replace env-var gate with `interrupt()` in `broker_orders.py` [financial] [critical]

- **Source run**: 2026-04-28
- **Where**: [c:/code/ADA/backend/routers/broker_orders.py](c:/code/ADA/backend/routers/broker_orders.py)
- **Resolved 2026-04-28**: Added a defensive multi-factor gate (LangGraph `interrupt()` analog for a FastAPI endpoint, since the trading_council subgraph that would normally surface live orders to the approval queue is Stage 2 work). Three gates in series for live execution: (1) `ROBINHOOD_PAPER_TRADING` env var must NOT be `"true"`, (2) request body must carry `confirm_live: true`, (3) request body must carry an `approval_token` from `POST /broker/request-live-approval`. Tokens are 32-byte URL-safe, single-use, TTL 300s, bound to (symbol, contracts) so a token for AAPL/1 cannot execute MSFT/100. Every live attempt â€” accepted or rejected â€” is structured-logged. New module-level constants `LIVE_APPROVAL_TTL_S` and `_live_approval_store` (in-memory, intentionally fail-closed across uvicorn workers). New endpoint `POST /broker/request-live-approval` issues tokens. Verified: `python -c "import ast; ast.parse(...)"` clean; `broker_orders.router` already registered at `Ada/backend/main.py:2894`. Tradier path (`backend/services/execution/tradier_service.py`) is hardcoded sandbox-only â€” no live capability â€” so no gate needed there. **Verification**: with `ROBINHOOD_PAPER_TRADING=false`, `POST /broker/execute/csp` without `confirm_live`/`approval_token` returns `OrderResult(success=false, status=rejected_no_approval)`; valid token flow returns `success=true`. Tradier remains sandbox-only. **The trading_council subgraph (Stage 2) will eventually replace this guard with the canonical LangGraph `interrupt()` pattern.**
- **Verified live 2026-04-28**: `POST /broker/request-live-approval` issues a 32-byte token, expires in 300s, returns the expected JSON shape including `paper_mode_currently`. Gate logic unit-tested with `ROBINHOOD_PAPER_TRADING=false` env override:
   - Happy path (matching symbol+contracts) â†’ `True ok`
   - Replay attack (token already consumed) â†’ `False approval_token already used (single-use)`
   - Wrong symbol (token AAPL, request TSLA) â†’ `False approval_token bound to TSLA, request is AAPL`
   - Wrong contracts (token 2, request 5) â†’ `False approval_token bound to 2 contracts, request is 5`
   - Empty token â†’ `False missing approval_token`
- **Status**: resolved + verified live (defensive gate); to be revisited when trading_council subgraph ships

### Q5 â€” Add TikTok OAuth creds + flip dry-run off [write_external] [high â€” Adam-blocking]

- **Source run**: 2026-04-28
- **Where**: `c:\code\zero\.env` (creds), [c:/code/zero/backend/app/workflows/activities/publish.py:101](c:/code/zero/backend/app/workflows/activities/publish.py#L101)
- **Suggested fix**: Two changes: (1) add `ZERO_TIKTOK_CLIENT_KEY=...` and
  `ZERO_TIKTOK_CLIENT_SECRET=...` to `c:\code\zero\.env` (Adam needs to
  generate these in TikTok developer portal); (2) once creds are present, set
  `ZERO_TIKTOK_DRY_RUN=false` in the same `.env`. The 12-stage carousel
  pipeline is feature-complete; only the publish step is short-circuited
  to mock IDs. This is the highest-leverage user-blocking item this run.
- **Status**: open

### Q6 â€” Wire Legion remediation-sprint auto-execution [write_external] [medium]

- **Source run**: 2026-04-28
- **Where**: `Legion/backend/app/services/autonomous_executor.py` + new
  approval routing
- **Suggested fix**: `dependency_scanner_daemon.py` creates remediation
  sprints when it finds outdated/vulnerable packages, but the sprints sit
  unexecuted because no auto-runner picks them up. Wire the `autonomous_executor`
  scheduler to scan for `sprint_kind = 'deps_remediation'` rows hourly, and
  execute via the existing approval middleware (DRY_RUN=true for 72h before
  promotion to live `git push`). Closes the dependency-update loop the user
  explicitly called out.
- **Status**: open

### Q7 â€” Add daemon heartbeat surface [write_external] [medium]

- **Source run**: 2026-04-28
- **Where**: new Postgres `daemon_heartbeats` migration + tiny middleware in
  `Legion/backend/app/services/supervised_daemon.py`
- **Suggested fix**: Create table:
  ```sql
  CREATE TABLE daemon_heartbeats (
    daemon_name text PRIMARY KEY,
    last_run_at timestamptz NOT NULL,
    last_status text NOT NULL,
    last_error text,
    run_count bigint NOT NULL DEFAULT 0
  );
  ```
  `supervised_daemon.py` UPSERTs after each run. Expose `/api/daemon-status`
  on `legion-backend`. Morning brief reads it for the daily note's
  `## System Health` block. The new architecture-master daily report (built
  this run) reads it for its "Daemon heartbeat status" section â€” until Q7
  ships, that section will read "blocked on Q7."
- **Status**: open

### Q8 â€” Fix llm_ops cron timezones [write_external] [low]

- **Source run**: 2026-04-28
- **Where**: [c:/code/Legion/backend/app/scheduler/llm_ops_jobs.py](c:/code/Legion/backend/app/scheduler/llm_ops_jobs.py)
- **Suggested fix**: MANDATE specifies ET; current code uses UTC (`08:10 UTC`
  â‰  `03:00 ET`). Either explicitly set `timezone='America/New_York'` on
  the scheduler and convert all hour values, or document the offset in a
  comment so the next reader doesn't get confused. Recommend the explicit
  timezone â€” UTC drift on DST is silent.
- **Status**: open

### Q9 â€” Refresh Legion mandate prose [write_external] [low]

- **Source run**: 2026-04-28
- **Where**: `c:\code\Legion\MANDATE.md`
- **Resolved 2026-04-28**: Two edits â€” (1) "What Legion owns" table row for llm-ops now points to actual `backend/app/agents/llm_ops/` and notes the auto-registered scheduler from Q1; (2) "LLM-Ops responsibility" section description updated to "running since 2026-04-24" instead of pointing at non-existent `backend/app/subgraphs/llm_ops.py`. Verbatim canonical blockquote at line 3 is preserved unchanged.
- **Status**: resolved

### Q10 â€” Run NSSM service installers + reboot [write_external] [high]

- **Source run**: 2026-04-28
- **Where**: `c:\code\scripts\nssm\install-services.ps1`,
  `c:\code\scripts\register-morning-brief.ps1`
- **Suggested fix**: Per the active 12-week plan's "Stage 0 verification gate
  â€” REMAINING" section, these scripts ship but require Administrator + reboot.
  Run `powershell -ExecutionPolicy Bypass -File <script>` as Admin, reboot,
  confirm `Get-Service Legion-Stack, Zero-Stack, SharedInfra-Stack,
  Reachy-Daemon, Health-Watchdog` all show `Running`. Without this the
  ecosystem doesn't survive an unattended reboot â€” manual `start-ecosystem.bat`
  is currently the only path.
- **Status**: open

### Q11 - Create Ada MCP compatibility server [write_external] [high]

- **Source run**: 2026-05-02
- **Where**: `c:\code\ADA\mcp_servers\ada_mcp.py`, referenced by Zero and Legion `.mcp.json`
- **Suggested fix**: Add a thin Ada MCP server at the compatibility path already referenced by Zero and Legion. It should expose read-only portfolio/signal tools first, plus paper-trading and live-order evaluation tools that preserve Ada's `financial` approval gate. Keep live execution fail-closed without explicit confirmation and audit logging.
- **Status**: open

### Q12 - Align Ada `.mcp.json` after `ada-mcp` exists [write_external] [medium]

- **Source run**: 2026-05-02
- **Where**: `c:\code\ADA\.mcp.json`
- **Suggested fix**: Once Q11 lands, align Ada's MCP config with the shared ecosystem surface used by Zero and Legion. Keep Playwright and codebase-memory, then add Ada's own server plus any shared memory/Postgres/Obsidian MCPs Ada may read without violating the vault contract.
- **Status**: open

### Q13 - Refresh stale model-route docs and callers [write_external] [medium]

- **Source run**: 2026-05-02
- **Where**: Zero, Legion, Ada, vault docs, and project configs that still mention `qwen3-coder` or `Qwen3-32B-AWQ` as current
- **Suggested fix**: Update current-fact docs and route defaults to the active shared infra state: LiteLLM `:4444` -> `qwen3-chat` -> llama.cpp `:18800` serving `Huihui-Qwen3.6-35B-A3B-abliterated-Q4_K_M.gguf`. Keep historical mentions only when explicitly labeled as history, legacy, or failed-swap context.
- **Status**: open

### Q14 - Implement Legion company operations interfaces [write_external] [high]

- **Source run**: 2026-05-02
- **Where**: `c:\code\Legion` new company operations service/tables/MCP tools
- **Suggested fix**: Add the formal contracts documented in `C:\code\zero\docs\company\10-constitution\MASTER_PLAN.md` and `C:\code\zero\docs\company\40-operations\LIVING_STATE.md`: `company.audit.run(read_only)`, `company.drift.list()`, `company.queue.add/fetch/resolve()`, `llm_ops.models.current()`, and `llm_ops.models.candidates()`. Keep `architecture_master.*` as legacy aliases during migration if existing callers need them. Start read-only, then allow whitelisted local doc updates once validation is stable.
- **Status**: open

### Q15 - Pilot Graphify/codebase graph memory on one repo [write_external] [low]

- **Source run**: 2026-05-02
- **Where**: generated agent-owned state under one pilot repo, preferably Legion or Ada
- **Suggested fix**: Run a Graphify/codebase-graph pilot that answers architecture and impact questions from structural memory. Measure whether it reduces raw file reads and prompt context for large-repo questions before making it a committed source-of-truth layer. Defer Graphiti until temporal relationship memory becomes load-bearing beyond Postgres and LangMem.
- **Status**: open

### Q16 - Add `c:\code\zero` to Legion's managed-project registry [write_external] [high]

- **Source run**: 2026-05-02
- **Where**: `c:\code\Legion\backend\app\core\legion_config.py` and any project registry UI/API
- **Suggested fix**: Add the company operating root as a docs/plans/audit-state project so Legion watches it continuously. It should be auto-learn enabled, docs-first, and governed by the company mandate. ArchitectureMaster should be treated as a legacy compatibility pointer only.
- **Status**: open

### Q17 - Decide version-control and remote strategy for `c:\code\zero` [write_external] [medium]

- **Source run**: 2026-05-02
- **Where**: `c:\code\zero`
- **Suggested fix**: Decide whether `c:\code\zero` should become its own git repository, a private company repository, or a submodule/worktree under an existing org. Do not publish company formation, financial, compliance, credential, or personal operating docs until a privacy policy for the repo exists.
- **Status**: open

<!-- agent-run-id: 1895a7c5-6ade-4f85-a1cd-7ef8860fc0cf source: ecosystem-audit at: 2026-04-28T-run-1 -->

