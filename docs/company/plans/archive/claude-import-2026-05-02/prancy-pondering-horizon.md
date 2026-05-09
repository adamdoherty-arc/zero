# Plan: Zero Docker Health Audit Skill

## Context

Zero needs a production-quality Docker health audit skill like ADA and Legion already have. Zero's infrastructure is simpler (3 containers vs 11) but has unique complexity: 66 scheduler jobs, multi-provider LLM routing with budget tracking, and many autonomous background services. The skill will follow the proven 4-phase pattern (Learn, Diagnose, Auto-Fix, Self-Learn) adapted for Zero's specific architecture.

## Files to Create

1. `.claude/skills/zero-docker-health/SKILL.md` - Main skill file (~450 lines)
2. `.claude/skills/zero-docker-health/LEARNINGS.md` - Learning log template pre-seeded with known Zero patterns

## Design Summary

### 4-Phase Protocol
- **Phase 0 (Learn)**: Read LEARNINGS.md for known patterns
- **Phase 1 (Diagnose)**: 18 parallel checks in 4 groups
- **Phase 2 (Auto-Fix)**: Severity-tiered fixes (CRITICAL/HIGH/MEDIUM/LOW)
- **Phase 3 (Self-Learn)**: Record new patterns, promote proven ones, track fix effectiveness

### 18 Diagnostic Checks

**Group A: Container & Infrastructure (1-5)**
1. Container Status - `docker ps --filter "name=zero"`
2. Backend Readiness - `GET /health/ready`
3. Operations Dashboard - `GET /api/system/operations-dashboard` (aggregates 10 subsystems)
4. Disk Space - `GET /api/system/disk`
5. System Status (auth validation) - `GET /api/system/status`

**Group B: Scheduler & Job Health (6-9)**
6. Scheduler Status - `GET /api/system/scheduler/status`
7. Scheduler Dashboard - `GET /api/system/scheduler/dashboard`
8. Scheduler Audit Log - `GET /api/system/scheduler/audit?limit=20`
9. Daily Report - `GET /api/system/daily-report`

**Group C: LLM & Provider Health (10-13)**
10. LLM Router Config - `GET /api/llm/config`
11. LLM Provider Health - `GET /api/llm/providers`
12. LLM Daily Spend - `GET /api/llm/usage/today`
13. Circuit Breaker Status - `GET /api/system/circuit-breakers`

**Group D: Logs & Ancillary Services (14-18)**
14. Backend Error Logs (last 30 min) - `docker logs zero-api`
15. Backend Warning Patterns - `docker logs zero-api`
16. Restart Loop Detection - grep for "Application startup complete"
17. Log Volume (noise check) - `wc -l`
18. Ancillary Services - SearXNG (`localhost:8888/healthz`) + Ollama (`localhost:11434/api/tags`)

### Auto-Fix Tiers

| Tier | Examples | Safety |
|------|----------|--------|
| CRITICAL | Container down, DB unreachable, budget 100% exhausted | ASK USER before restart |
| HIGH | Circuit breaker stuck OPEN, Ollama unreachable, scheduler stopped | API resets safe; restarts need user |
| MEDIUM | SearXNG down, slow jobs, high log volume | Investigate first |
| LOW | Legion unavailable, disk 50-85%, budget 50-80% | Informational only |

### Key Design Decisions
- **API-first**: 10 of 18 checks use Zero's existing health/operations endpoints (more reliable than log parsing)
- **Auth header on all API calls**: `curl -H "Authorization: Bearer $ZERO_GATEWAY_TOKEN"`
- **Compose file**: All commands use `-f docker-compose.sprint.yml`
- **Rebuild not restart**: Backend code is COPY'd; always build+up, never just restart
- **Scheduler emphasis**: 4 dedicated checks for Zero's 66-job scheduler
- **Budget tracking**: LLM budget appears in 3 checks; exhaustion is a real operational risk
- **Pre-seeded learnings**: Known Windows gotchas (clock skew, --since empty) included from day one

### Safety Rules
1. Never restart containers without user confirmation
2. After code changes: build, not restart
3. Auth header on all curl commands
4. Wait 2 min after rebuild before re-checking
5. Never modify DB data or scheduler jobs
6. Only reset circuit breakers OPEN > 5 min
7. Max 1 container restart per audit run
8. Always specify `-f docker-compose.sprint.yml`

## Verification

After creating the files:
1. Confirm skill files exist at correct paths
2. Verify all referenced API endpoints are real (already validated: `/health/ready`, `/api/system/status`, `/api/system/circuit-breakers`, `/api/system/scheduler/status`, `/api/system/scheduler/dashboard`, `/api/system/scheduler/audit`, `/api/system/disk`, `/api/system/operations-dashboard`, `/api/system/daily-report`, `/api/llm/config`, `/api/llm/providers`, `/api/llm/usage/today`)
3. Run a quick `docker ps --filter "name=zero"` to confirm container naming matches
4. Test one curl command to verify auth header format works
