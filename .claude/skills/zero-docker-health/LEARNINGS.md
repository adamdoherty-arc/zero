# Zero Docker Health Audit - Learning Log

> Auto-maintained by the zero-docker-health skill. Records new patterns,
> fix results, and recurring issues across audit runs.
> Patterns that appear 2+ times with reliable fixes get PROMOTED into SKILL.md.

## Pattern History

| Date | Symptom | Root Cause | Fix | Severity | Status |
|------|---------|-----------|-----|----------|--------|

## Fix Verification History

| Date | Issue | Fix Applied | Result | Notes |
|------|-------|-------------|--------|-------|

## Recurring Issues (2+ occurrences, escalate at 3+)

| Issue | Count | Last Seen | Current Fix | Escalated? |
|-------|-------|-----------|-------------|------------|

## Known Zero-Specific Patterns

Pre-seeded from codebase knowledge. These are not yet observed in audits but are known failure modes.

### Docker restart != Docker rebuild
- **Symptom**: Code changes not taking effect after `docker compose restart`
- **Root Cause**: Backend Dockerfile uses `COPY app/ ./app/` to bake code into the image at build time. `docker compose restart` reuses the old image without rebuilding.
- **Fix**: Always use `docker compose -f docker-compose.sprint.yml build zero-api && docker compose -f docker-compose.sprint.yml up -d zero-api`
- **Detection**: Compare error traceback line numbers with current source code

### Docker logs --since returns empty on Windows
- **Symptom**: `docker logs --since 30m` returns 0 lines despite container being healthy and active
- **Root Cause**: Clock skew between Windows host and Docker Desktop daemon
- **Fix**: Use `--tail N` instead of `--since` on Windows (e.g., `--tail 3000`)
- **Detection**: Checks 14-16 all return 0 lines AND container is healthy in Check 1

### 66 Scheduler Jobs Competing for Resources
- **Symptom**: Slow API responses, DB pool exhaustion (asyncpg timeouts), event loop saturation
- **Root Cause**: High-frequency jobs (every 1-5 min) combined with batch jobs create resource contention. 66+ jobs all sharing one backend process.
- **Fix**: Monitor via scheduler dashboard (Check 7). Consider staggering or reducing frequency of non-critical jobs.
- **Detection**: Check 7 for slow jobs + Check 14 for asyncpg timeout errors

### LLM Budget Depletion Mid-Day
- **Symptom**: All LLM-dependent scheduler jobs start failing around midday
- **Root Cause**: Autonomous jobs consume budget throughout the day (content generation, research, brain cycles, AI company tasks). Default budget $5/day can be exhausted by heavy autonomous activity.
- **Fix**: Monitor spend rate via Check 12. Increase `ZERO_LLM_DAILY_BUDGET_USD` in `.env` if needed. Budget resets at midnight.
- **Detection**: Check 10 budget percentage approaching 100% + Check 8 for LLM-related job failures

### Kimi Temperature Requirement
- **Symptom**: Kimi K2.5 API calls failing with parameter validation error
- **Root Cause**: Kimi K2.5 requires `temperature=1` exactly. Other values are rejected by the API.
- **Fix**: Ensure all Kimi K2.5 calls use `temperature=1` in `kimi_provider.py`
- **Detection**: Check 14 for Kimi-related errors mentioning temperature

### Alpine localhost Resolution
- **Symptom**: Healthcheck failing despite service being up
- **Root Cause**: Alpine-based containers resolve `localhost` to `::1` (IPv6). If the service binds only to `0.0.0.0` (IPv4), the healthcheck connection is refused.
- **Fix**: Use `127.0.0.1` instead of `localhost` in healthcheck commands
- **Detection**: Container stuck in `(health: starting)` state in Check 1
