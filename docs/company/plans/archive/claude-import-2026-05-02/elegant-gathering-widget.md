# Plan: Create `legion-docker-health` Skill

## Context

ADA has a battle-tested `docker-health` skill that runs 17 parallel diagnostic checks, auto-fixes issues by severity tier, and maintains a self-learning log (`LEARNINGS.md`) that accumulates patterns across runs. Over 130+ entries prove the pattern works — it's caught 19 backend freezes, 50+ code bugs, and promoted dozens of patterns from learnings into the skill itself.

Legion already has a `legion-watchdog` skill that does **strategic, multi-dimensional scoring** (12 health dims + 5 audit dims) — but it's focused on rolling 24h-7d windows and "is the system healthy over time?" questions. There is no **real-time infrastructure triage** skill: "are containers up? is the backend frozen? is the agentic loop stalled? is Ollama reachable?" — the kind of thing you run after a restart, during a suspected freeze, or as a daily infra heartbeat.

This plan creates `legion-docker-health` — a focused Docker/infrastructure health audit skill adapted from ADA's proven pattern, tailored to Legion's unique concerns (agentic loop, sprint pipeline, provider overrides, Ollama queue).

## Approach

Create 2 files:
1. **`c:\code\Legion\.claude\skills\legion-docker-health\SKILL.md`** — Full execution protocol with 24 diagnostic checks, severity-tiered auto-fix tables, safety rules, and common issues reference
2. **`c:\code\Legion\.claude\skills\legion-docker-health\LEARNINGS.md`** — Self-learning log template pre-seeded with known Legion patterns from MEMORY.md

## Skill Design

### How It Differs From legion-watchdog

| Aspect | legion-docker-health (NEW) | legion-watchdog (EXISTING) |
|--------|---------------------------|---------------------------|
| Scope | Infrastructure triage | Strategic multi-dimensional scoring |
| Time horizon | Real-time, last 30 min | Rolling 24h-7d windows |
| Trigger | After deploys, suspected freezes, daily heartbeat | Periodic quality reviews, audit runs |
| Output | Severity findings + auto-fix recipes | Dimension scores (0-100) + improvement sprints |
| Analogy | ER triage — check vitals, stabilize | Annual physical — measure everything, track trends |

No overlap: docker-health does NOT score dimensions, does NOT scan code quality, does NOT discover features. It DOES check things watchdog cannot: Docker container status from host, log-level error scanning, Ollama queue saturation, restart loop detection, daemon crash detection.

### 4-Phase Execution (from ADA's proven pattern)

```
Phase 0: Read LEARNINGS.md (recognize known patterns)
Phase 1: Diagnose (24 checks in parallel, 4 groups)
Phase 2: Auto-Fix (severity-tiered, user confirmation for destructive ops)
Phase 3: Self-Learn (update LEARNINGS.md, promote 2+ patterns to SKILL.md)
```

Modes:
- `/legion-docker-health` — Full 4-phase loop
- `/legion-docker-health --check` — Read-only diagnostics only (Phase 0-1)
- `/legion-docker-health --fix` — Full loop with MEDIUM code-level fixes enabled

### 24 Diagnostic Checks (4 Groups)

**Group A: Container & Infrastructure (1-6)**
1. Container Status (`docker ps --filter "name=legion"`) — all 11 containers
2. Backend Health Endpoint (`curl /health`) — DB, background tasks, LLM, agentic, sprint gate
3. Service Infrastructure Health (`curl /api/health/services`) — postgresql, redis, qdrant, ollama
4. Frontend Health (`curl /api/health/frontend` + direct 3005 check)
5. Connection Pool Stats (`curl /api/health/connections`) — pool overflow, utilization
6. GPU/VRAM Status (`curl /api/gpu-manager/status`) — VRAM usage, Ollama mode

**Group B: LLM & Provider Health (7-11)**
7. LLM Health (`curl /llm/health`) — queue depth, circuit breaker, semaphore, balance latch
8. Provider Override Routing (`curl /api/prompt-manager/templates/provider-overrides`) — 9 override rows, canary_traffic_pct, rollback counts
9. Ollama Direct Connectivity (`curl localhost:11434/api/tags`) — running? models loaded?
10. MiniMax Balance Circuit Breaker (from Check 7 + Prometheus metrics)
11. TextGrad/DSPy Daemon Status (Prometheus metrics for `legion_textgrad`, `legion_improvements`)

**Group C: Sprint & Agentic Pipeline (12-18)**
12. Sprint Creation Gate (`curl /api/sprints/creation-mode`) — mode, override status
13. Agentic Loop Health (from `/health` agentic section + `/api/agentic/health`)
14. Stuck/Phantom Sprints (`psql` — ACTIVE with 0 actual tasks, stale > 4h)
15. Stuck Tasks (`psql` — RUNNING > 30 min)
16. Recent Sprint Failure Rate (`psql` — 14d failure rate)
17. Orphaned Tasks (`psql` — PENDING/RUNNING in dead sprints)
18. Error Recovery & Circuit Breakers (`curl /api/health/error-recovery`)

**Group D: Background Systems & Logs (19-24)**
19. Daemon Health (`curl /api/health/daily-standup` — extract background_tasks)
20. Backend Error Logs (`docker logs --since 30m` — grep error/exception/traceback)
21. Backend Warning Patterns (`docker logs --since 30m` — circuit open, blocked, balance)
22. Restart Loop Detection (`docker logs --since 30m` — count "Application startup complete")
23. Prometheus Metric Anomalies (6 targeted metric checks)
24. Log Volume (`docker logs --since 30m | wc -l` — noise check)

### Auto-Fix Severity Tiers

**CRITICAL** (container down): Always ASK user before restart. Never restart >1 container. Wait 2 min after.
**HIGH** (degraded): Apply safe API triggers (daemon restart, circuit breaker reset). Inform user of degradation.
**MEDIUM** (slow/broken): Investigate root cause. Report findings. Fix known patterns only with `--fix` flag.
**LOW** (informational): Log for monitoring. Expected states documented.

### Safety Rules (10 rules)

Key differences from ADA: Legion's skill is MORE conservative because:
- Agentic loops have in-flight sprint state that dies on restart
- Sprint creation gate changes affect the entire autonomous pipeline
- Health gate cooldowns exist to prevent retry storms
- Sprint data modifications can't be undone

1. NEVER restart containers without user confirmation
2. NEVER modify sprint data directly (sprints/sprint_tasks tables)
3. NEVER change sprint_creation_mode without confirmation
4. NEVER reset health gates without confirmation
5. API trigger endpoints are always safe (idempotent)
6. Wait 2 min after any backend restart before re-checking
7. Docker CLI may fail inside containers — API fallbacks for all checks
8. PostgreSQL enums are UPPERCASE (ACTIVE, COMPLETED, FAILED)
9. NEVER modify .env or docker-compose.yml
10. Max 1 container restart per audit run

### LEARNINGS.md Pre-seeded Patterns

Pre-seed from MEMORY.md's accumulated knowledge:
- Phantom sprints (total_tasks mismatch)
- Stuck task mass-mark (identical microsecond timestamps)
- avg=None in daemon logs (bare except swallowing NameError/ImportError)
- Prometheus counter with no data rows (wiring broken)
- Docker logs --since empty on Windows (clock skew)
- Docker restart != rebuild (COPY baked into image)
- PostgreSQL enum case sensitivity

## Files to Create

| File | Lines (est) | Content |
|------|-------------|---------|
| `.claude/skills/legion-docker-health/SKILL.md` | ~450 | Full execution protocol, 24 checks, auto-fix tables, safety rules, common issues |
| `.claude/skills/legion-docker-health/LEARNINGS.md` | ~80 | Template + pre-seeded Legion-specific known patterns |

## Files Referenced (read-only)

- `c:\code\ADA\.claude\skills\docker-health\SKILL.md` — Source pattern (reviewed)
- `c:\code\ADA\.claude\skills\docker-health\LEARNINGS.md` — Example of mature learning log (reviewed)
- `c:\code\Legion\.claude\skills\legion-watchdog\SKILL.md` — YAML metadata format, no overlap
- `c:\code\Legion\backend\app\api\endpoints\service_health.py` — API surface consumed
- `c:\code\Legion\backend\app\services\sprint_creation_gate.py` — Gate modes

## Verification

After creating both files:
1. Confirm SKILL.md renders correctly: read back and verify all 24 checks are listed, all auto-fix tables are complete, safety rules are present
2. Confirm LEARNINGS.md has the correct template tables (Pattern History, Fix Verification History, Recurring Issues) plus pre-seeded Known Patterns
3. Run `/legion-docker-health --check` to verify the skill loads and all API checks execute (no Docker changes)
4. Verify no overlap with legion-watchdog by confirming docker-health does NOT reference dimension scores, code quality scans, feature discovery, or improvement sprint generation
