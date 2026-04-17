---
name: "zero-docker-health"
description: "Infrastructure-level Docker health audit with auto-fix for the Zero platform. 4-phase execution: Learn, Diagnose (18 parallel checks), Auto-Fix (severity-tiered), Self-Learn."
version: "1.0.0"
metadata:
  zero:
    category: "operations"
    triggers:
      - "docker health"
      - "docker logs"
      - "system health"
      - "container health"
      - "is zero running"
      - "check containers"
      - "backend audit"
      - "scheduler check"
      - "check errors"
      - "health check"
    requires:
      services: ["zero-api", "zero-postgres"]
    autonomous: true
    capabilities:
      - "3-container Docker health monitoring (postgres, api, ui)"
      - "18 parallel diagnostic checks (API-first, Docker CLI fallback)"
      - "Zero-specific: 66-job scheduler health, multi-provider LLM router, budget tracking"
      - "Severity-tiered auto-fix (CRITICAL/HIGH/MEDIUM/LOW)"
      - "Circuit breaker management"
      - "Self-learning via LEARNINGS.md (pattern recognition + fix promotion)"
---

# Zero Docker Health Audit Skill

Infrastructure-level Docker health audit for the Zero Personal AI Assistant. Diagnoses container failures, scheduler stalls, LLM provider issues, budget exhaustion, and circuit breaker problems -- then auto-fixes what it can.

## Usage

```
/zero-docker-health              -- Full 4-phase loop: Learn + Diagnose + Fix + Learn
/zero-docker-health --check      -- Read-only: Phases 0-1 only, no fixes applied
/zero-docker-health --fix        -- Full loop with MEDIUM code-level fixes enabled
```

Use this skill when:
- After a deployment, rebuild, or restart
- The frontend is unresponsive or shows errors
- You suspect the backend is frozen or scheduler is stalled
- LLM calls are timing out or failing
- You want a periodic infrastructure heartbeat
- Docker containers appear unhealthy
- Scheduler jobs are failing

## Auth Setup

All API calls require the gateway token. Extract it at the start of every audit:

```bash
TOKEN=$(grep ZERO_GATEWAY_TOKEN /c/code/zero/.env | cut -d= -f2)
```

Then use on every curl: `-H "Authorization: Bearer $TOKEN"`

## Execution Protocol

Run the audit in four phases: **Learn** (read prior knowledge) -> **Diagnose** (read-only, parallel) -> **Auto-Fix** (targeted corrections) -> **Self-Learn** (record new patterns).

### Phase 0: Read Learning Log

Before running any diagnostics, read `.claude/skills/zero-docker-health/LEARNINGS.md` if it exists. Use its entries to:
- Recognize previously-seen patterns instantly (skip exploration, apply known fix)
- Check if previous fixes held (same issue reappearing = incomplete fix)
- Prioritize recurring issues first

If `LEARNINGS.md` doesn't exist, create it from the template in Phase 3 after the audit completes.

### Phase 1: Diagnose (Run ALL checks in parallel)

Execute these diagnostic checks simultaneously. Each provides a different view of system health. All checks use **API-first approach** (prefer `curl` to backend API), with Docker CLI as fallback only where needed.

#### Group A: Container and Infrastructure (Checks 1-5)

##### Check 1: Container Status
```bash
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" --filter "name=zero"
```
**Look for**: Any container not showing `(healthy)`, any with status `Exited` or `Restarting`.
**Expected containers**: zero-postgres, zero-api, zero-ui. Optional: zero-ui-dev (profile: dev).

##### Check 2: Backend Readiness Endpoint
```bash
curl -s --max-time 10 http://localhost:18792/health/ready -H "Authorization: Bearer $TOKEN"
```
**Look for**: Non-200 response, any dependency check failing (database, ollama, searxng, legion). If this times out, the backend is frozen or down.

##### Check 3: Operations Dashboard (single-call health overview)
```bash
curl -s --max-time 15 http://localhost:18792/api/system/operations-dashboard -H "Authorization: Bearer $TOKEN"
```
**Look for**: `success_rate_24h < 80%`, `active_alerts > 0`, LLM spend approaching budget, failed providers, open circuit breakers. This single endpoint aggregates 10+ subsystems.

##### Check 4: Disk Space
```bash
curl -s --max-time 5 http://localhost:18792/api/system/disk -H "Authorization: Bearer $TOKEN"
```
**Look for**: `percent_used > 85%` (HIGH), `> 95%` (CRITICAL). Backups and workspace are the biggest consumers.

##### Check 5: System Status (auth validation)
```bash
curl -s --max-time 5 http://localhost:18792/api/system/status -H "Authorization: Bearer $TOKEN"
```
**Look for**: Non-200 response means gateway token is invalid or backend is down. If this fails, all subsequent API checks will also fail. Switch to Docker CLI fallback mode.

#### Group B: Scheduler and Job Health (Checks 6-9)

##### Check 6: Scheduler Status
```bash
curl -s --max-time 10 http://localhost:18792/api/system/scheduler/status -H "Authorization: Bearer $TOKEN"
```
**Look for**: `running: false` (CRITICAL -- scheduler is dead), disabled jobs that should be enabled, jobs with no `next_run_time` (orphaned). Zero runs 66+ scheduler jobs; the scheduler being down means all autonomous activity stops.

##### Check 7: Scheduler Dashboard (success rates)
```bash
curl -s --max-time 10 http://localhost:18792/api/system/scheduler/dashboard -H "Authorization: Bearer $TOKEN"
```
**Look for**: Jobs with `success_rate < 50%` (HIGH), jobs with 0 executions in 24h (stale), jobs with average duration > 300s (slow). Focus on failures and anomalies across the 66+ jobs.

##### Check 8: Scheduler Audit Log (recent failures)
```bash
curl -s --max-time 10 "http://localhost:18792/api/system/scheduler/audit?limit=20" -H "Authorization: Bearer $TOKEN"
```
**Look for**: Recent job failures, error messages, patterns (same job failing repeatedly). Group failures by job name. If one job has 3+ failures in a row, flag as HIGH.

##### Check 9: Daily Report (autonomous activity summary)
```bash
curl -s --max-time 15 http://localhost:18792/api/system/daily-report -H "Authorization: Bearer $TOKEN"
```
**Look for**: Missing/skipped subsystem sections, failures reported, stale data (no activity for a subsystem that should be active).

#### Group C: LLM and Provider Health (Checks 10-13)

##### Check 10: LLM Router Config
```bash
curl -s --max-time 5 http://localhost:18792/api/llm/config -H "Authorization: Bearer $TOKEN"
```
**Look for**: `current_spend_usd` approaching `daily_budget_usd`. Flag at 80% (HIGH), 95% (CRITICAL). Check `default_model` is set correctly. Check task routing overrides are present.

##### Check 11: LLM Provider Health
```bash
curl -s --max-time 10 http://localhost:18792/api/llm/providers -H "Authorization: Bearer $TOKEN"
```
**Look for**: Any provider with `status: unhealthy`. All providers degraded = CRITICAL. Ollama specifically down = HIGH (it's the local backbone for coding + workflow tasks). Check Kimi health (primary brain for 8/10 task types).

##### Check 12: LLM Daily Spend
```bash
curl -s --max-time 10 http://localhost:18792/api/llm/usage/today -H "Authorization: Bearer $TOKEN"
```
**Look for**: `remaining_budget_usd < 0.50` (HIGH), spend rate vs hours remaining in day, provider cost distribution anomalies (unexpected provider getting heavy use).

##### Check 13: Circuit Breaker Status
```bash
curl -s --max-time 5 http://localhost:18792/api/system/circuit-breakers -H "Authorization: Bearer $TOKEN"
```
**Look for**: Any breaker in OPEN state (HIGH), breakers with high failure counts. Track which external services are having issues. Common breakers: gmail, ollama, kimi, searxng, legion.

#### Group D: Logs and Ancillary Services (Checks 14-18)

##### Check 14: Backend Error Logs (last 30 min)
```bash
docker logs zero-api --since 30m 2>&1 | grep -iE '"level":"error"|exception|traceback' | tail -30
```
**Fallback** (Windows clock skew -- use if `--since` returns empty despite healthy container):
```bash
docker logs zero-api --tail 3000 2>&1 | grep -iE '"level":"error"|exception|traceback' | tail -30
```
**Look for**: Recurring error patterns, `ImportError`/`NameError` (code bugs), `asyncpg` errors (DB issues), `TimeoutError` (LLM/queue), connection pool errors.

##### Check 15: Backend Warning Patterns (last 30 min)
```bash
docker logs zero-api --since 30m 2>&1 | grep -iE '"level":"warning"|circuit.*open|budget.*exceeded|slow' | tail -20
```
**Look for**: Budget warnings, circuit breaker transitions, scheduler warnings, slow operations, rate limit warnings.

##### Check 16: Restart Loop Detection
```bash
docker logs zero-api --since 30m 2>&1 | grep -c "Application startup complete"
```
**Look for**: Count > 1 means backend restarted in last 30 min. Count > 3 = restart loop (HIGH severity). DO NOT auto-restart -- investigate the error logs first.

##### Check 17: Log Volume (noise check)
```bash
docker logs zero-api --since 30m 2>&1 | wc -l
```
**Look for**: > 5000 lines in 30 min = excessive logging. > 10000 = noise problem masking real errors. Identify noisiest sources:
```bash
docker logs zero-api --tail 5000 2>&1 | grep -oP '"event":"[^"]*"' | sort | uniq -c | sort -rn | head -10
```

##### Check 18: Ancillary Service Health
**SearXNG** (research/enhancement dependency):
```bash
curl -s --max-time 5 http://localhost:8888/healthz
```
**Ollama** (local LLM backbone):
```bash
curl -s --max-time 5 http://localhost:11434/api/tags
```
**Look for**: SearXNG down (MEDIUM -- research and enhancement jobs will fail silently). Ollama unreachable (HIGH -- coding and workflow LLM tasks will fail). Note which Ollama models are loaded.

### Phase 2: Auto-Fix (Apply based on findings)

After diagnosing, classify findings and apply fixes in priority order.

#### CRITICAL Fixes (container/service down)

**IMPORTANT**: ALWAYS ask user confirmation before container restarts. Zero has 66 scheduler jobs with in-flight state.

| Finding | Proposed Fix | Safety |
|---------|-------------|--------|
| Backend container unhealthy/exited | `docker compose -f docker-compose.sprint.yml build zero-api && docker compose -f docker-compose.sprint.yml up -d zero-api` | **ASK USER** first. Wait 2 min. Re-check health. |
| Frontend container unhealthy/exited | `docker compose -f docker-compose.sprint.yml up -d zero-ui` | **ASK USER** first. |
| Database container unhealthy/exited | `docker compose -f docker-compose.sprint.yml up -d zero-postgres` | **ASK USER** first. Confirm no active transactions. |
| Backend restart loop (>3 in 30m) | Inform user: check error logs for root cause | **DO NOT auto-restart.** Investigate first. |
| LLM budget 100% exhausted | Inform user: all LLM-dependent jobs will fail until midnight reset or manual budget increase | Cannot auto-fix. Suggest increasing `ZERO_LLM_DAILY_BUDGET_USD` in `.env`. |

#### HIGH Fixes (degraded service)

| Finding | Auto-Fix | Safety |
|---------|----------|--------|
| Circuit breaker stuck OPEN (> 5 min) | `curl -s -X POST http://localhost:18792/api/system/circuit-breakers/{name}/reset -H "Authorization: Bearer $TOKEN"` | Safe (idempotent API call). Only reset breakers OPEN > 5 minutes. |
| Ollama unreachable | Inform user: check Ollama on host (`ollama list`, check if process is running). Cannot restart from Docker context. | Informational. |
| LLM budget > 80% with hours remaining | Inform user: consider pausing non-essential scheduler jobs or increasing budget | Informational only. |
| Scheduler not running | Inform user: backend may need restart to recover scheduler | **ASK USER** before restart. |
| Specific job failing 3+ times consecutively | `curl -s -X POST http://localhost:18792/api/system/scheduler/jobs/{job_name}/trigger -H "Authorization: Bearer $TOKEN"` | Safe (one-shot manual trigger to test). |
| Kimi provider unhealthy | Check API key validity. Inform user if `ZERO_KIMI_API_KEY` needs rotation. | Informational. |
| Frontend proxy errors while backend healthy | `docker compose -f docker-compose.sprint.yml restart zero-ui` | **ASK USER** first. |

#### MEDIUM Fixes (degraded performance)

| Finding | Fix Action | Safety |
|---------|-----------|--------|
| SearXNG down | `docker compose -f docker-compose.searxng.yml up -d` | **ASK USER** first. |
| Slow scheduler jobs (avg > 300s) | Investigate job implementation, look for missing timeouts or unbounded queries | Read-only investigation. |
| Job success rate < 50% for specific job | Investigate audit log for that job, identify error pattern | Read-only. |
| High log volume (> 10K/30min) | Identify noisiest sources, consider reducing log level for high-frequency jobs | Read-only investigation. |
| DB pool exhaustion patterns in logs | Investigate `database.py` pool settings, check concurrent job count | Read-only. Suggest config changes. |

#### LOW Fixes (informational)

| Finding | Note |
|---------|------|
| Legion unavailable in health check | Non-critical for Zero core functions. Ecosystem sync will degrade gracefully. |
| SearXNG degraded | Research and enhancement jobs will slow. Non-blocking for core operations. |
| Disk usage 50-85% | Monitor. Backups (`/app/backups`) are the biggest consumer. |
| LLM budget 50-80% used | Normal mid-day usage. Monitor spend rate vs hours remaining. |
| Ollama model not pre-loaded | First LLM call will be slow (model load from disk). Consider `ollama pull` to pre-warm. |

### Phase 3: Self-Learn (After every audit)

After completing the audit, update the persistent learning log.

#### 1. Record New Patterns

For any error pattern NOT already in the Common Issues table or LEARNINGS.md:

```markdown
## New Pattern: {date}
- **Symptom**: {what appeared in logs/checks}
- **Root Cause**: {what was actually wrong}
- **Fix Applied**: {what fixed it}
- **File(s) Changed**: {paths if applicable}
- **Severity**: {CRITICAL|HIGH|MEDIUM|LOW}
```

Write this entry to `LEARNINGS.md` using the Edit tool.

#### 2. Promote Proven Patterns

If a pattern from `LEARNINGS.md` has occurred **2+ times** and has a reliable fix:
1. Add it to the **Common Issues and Root Causes** table in this SKILL.md
2. Add it to the appropriate **Auto-Fix tier** table
3. Add a new diagnostic check if the pattern can be detected programmatically
4. Mark the LEARNINGS.md entry as `[PROMOTED]`

#### 3. Track Fix Effectiveness

After applying any fix, record whether it resolved the issue:

```markdown
## Fix Verification: {date}
- **Issue**: {description}
- **Fix**: {what was done}
- **Result**: {RESOLVED|PARTIAL|FAILED}
- **Notes**: {additional context}
```

If a fix was `FAILED` or `PARTIAL`, update the Common Issues table with the better solution.

#### 4. Escalate Recurring Issues

If the same issue appears in **3+ audits** despite being fixed:
1. Escalate severity by one level (LOW->MEDIUM, MEDIUM->HIGH)
2. Add a root cause note -- the fix is treating symptoms, not the cause
3. Flag for architectural review

### Report Format

Output the final report in this format:

```
=== ZERO DOCKER HEALTH AUDIT ===
Timestamp: {current_time}
Mode: {full|check|fix}

CONTAINERS: [{healthy_count}/{total_count} healthy]
  zero-postgres:  {status} (up {uptime})
  zero-api:       {status} (up {uptime})
  zero-ui:        {status} (up {uptime})

SCHEDULER: [{enabled_count}/{total_count} jobs, {success_rate}% success 24h]
  Failing Jobs:    {list of jobs with <50% success rate}
  Stale Jobs:      {list of jobs with 0 runs in 24h}

LLM BUDGET: ${spend_usd} / ${budget_usd} ({pct}% used)
  Providers:       {healthy}/{total} healthy [{provider_list}]
  Circuit Breakers: {all closed|N open: [names]}

CRITICAL ({count})
  [{NEEDS_USER|FIXED}] {description}

HIGH ({count})
  [{FIXED|NEEDS_USER|WARN}] {description}

MEDIUM ({count})
  [{DIAGNOSED|WARN|INFO}] {description}

LOW ({count})
  [{INFO}] {description}

FIXES APPLIED: {count}
  - {fix_description}

RECOMMENDATIONS: {count}
  1. {highest priority action with specific commands/paths}
  2. ...
```

## Safety Rules

1. **NEVER restart containers without user confirmation.** Zero has 66 scheduler jobs with in-flight state that dies on restart.
2. **After code changes, REBUILD not restart.** Backend Dockerfile uses `COPY app/ ./app/` -- `docker compose restart` reuses the old baked-in image. Must use `docker compose -f docker-compose.sprint.yml build zero-api && docker compose -f docker-compose.sprint.yml up -d zero-api`.
3. **After config-only changes (.env):** Use `docker compose -f docker-compose.sprint.yml up -d zero-api` (rebuild not needed, but container must be recreated to pick up new env vars).
4. **Include auth header on ALL curl commands.** Extract token: `TOKEN=$(grep ZERO_GATEWAY_TOKEN .env | cut -d= -f2)` then `-H "Authorization: Bearer $TOKEN"`.
5. **Wait 2 minutes** after any backend restart/rebuild before re-checking health. Startup takes 40-120s (start_period: 40s in Docker healthcheck).
6. **NEVER modify database data** directly. Scheduler audit log and metrics are read-only for this skill.
7. **NEVER reset circuit breakers** that have been OPEN < 5 minutes. They may be protecting against active outages.
8. **Only reset circuit breakers via the API** (POST `/api/system/circuit-breakers/{name}/reset`), never by code modification.
9. **Max 1 container restart per audit run.** Wait for full recovery before any second action.
10. **NEVER modify scheduler jobs** (enable/disable/delete) without user confirmation. Some are intentionally configured.
11. **Always specify `-f docker-compose.sprint.yml`** for all docker compose commands. SearXNG uses separate `docker-compose.searxng.yml`.
12. **NEVER modify `.env` or `docker-compose.sprint.yml`.** Configuration changes require user action.
13. **Docker CLI may fail inside containers.** API-based checks are primary; Docker CLI is fallback only. Score Docker CLI failures as "inconclusive" not "broken".

## Common Issues and Root Causes

| Issue | Symptom | Root Cause | Quick Fix | Detection |
|-------|---------|-----------|-----------|-----------|
| Backend unhealthy | Health endpoint timeout or 503 | Startup hung, DB unreachable, or event loop blocked | ASK USER: rebuild + restart | Check 2 timeout |
| Scheduler stopped | `running: false` in scheduler status | Exception during scheduler start, or backend restart | Restart backend (ASK USER) | Check 6 |
| LLM budget exhausted | All LLM-dependent jobs failing, spend >= budget | Heavy autonomous usage (66 jobs, many use LLM) | Wait for midnight reset or increase budget in .env | Check 10 + Check 12 |
| Ollama unreachable | Provider unhealthy, coding/workflow tasks failing | Ollama not running on host, VRAM exhausted, process crashed | Restart Ollama on host (outside Docker) | Check 11 + Check 18 |
| Kimi unavailable | 8/10 task types degraded, API key or rate limit | API key expired, rate limited, or balance exhausted | Check/rotate `ZERO_KIMI_API_KEY` | Check 11 |
| Circuit breaker stuck OPEN | External service calls failing | Rate limiting (429), service outage, network issue | Reset via API (if OPEN > 5 min) | Check 13 |
| Scheduler job failing repeatedly | 3+ consecutive failures in audit log | External dependency down, data issue, or code bug | Manual trigger after fixing root cause | Check 8 |
| SearXNG down | Research/enhancement jobs failing silently | Container crashed or port conflict | `docker compose -f docker-compose.searxng.yml up -d` | Check 18 |
| High log volume | > 10K lines/30min, real errors masked | High-frequency jobs (every 1-5 min) producing verbose output | Identify noisy sources, reduce log level | Check 17 |
| Docker restart != rebuild | Code changes not taking effect, old tracebacks | Backend Dockerfile uses `COPY` at build time | Must `docker compose -f docker-compose.sprint.yml build zero-api` | Traceback line numbers mismatch source |
| Docker logs empty (Windows) | `--since` returns 0 lines despite healthy container | Clock skew between Windows host and Docker daemon | Use `--tail N` fallback instead of `--since` | Checks 14-16 all empty |
| Gateway token invalid | All API calls return 401/403 | Token in .env doesn't match running container's env | Recreate container to pick up new .env value | Check 5 fails |
| DB pool exhaustion | Multiple concurrent timeouts, API unresponsive | 66 scheduler jobs competing for DB connections | Restart backend (ASK USER), investigate pool settings | Check 14 for asyncpg timeouts |
| Frontend 502/504 | UI loads but API calls fail | Backend down or restarting, nginx proxy can't reach upstream | Check backend first, restart frontend if backend healthy | Check 1 + Check 2 |

## Post-Audit Checklist

1. If any CRITICAL/HIGH fixes were applied, re-run the affected diagnostic checks to verify
2. If container restarts were performed, wait 2 minutes then run full `--check`
3. Update LEARNINGS.md with any new patterns, fix verifications, or recurring issue escalations
4. If recurring issues escalated (3+ times), flag for architectural review
5. Run a final health check to confirm all fixes are working
