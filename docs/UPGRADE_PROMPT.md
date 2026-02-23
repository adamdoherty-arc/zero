# Zero Upgrade Prompt

Copy-paste this prompt into a new Claude Code session to run a Zero health check and upgrade cycle.

---

## The Prompt

```
Review Zero's health and upgrade it. Zero is a 24/7 personal AI assistant at c:\code\zero.

**Context:** Read CLAUDE.md for dev rules and .claude/memory/MEMORY.md for architecture (module map, scheduled jobs, patterns). Read docs/SELF_IMPROVEMENT_PROCESS.md for the full upgrade checklist.

**Steps:**
1. `docker ps --format "table {{.Names}}\t{{.Status}}" | grep zero` - verify all containers healthy
2. `docker logs --tail 100 zero-api 2>&1 | grep -i "error\|fail\|traceback"` - check for backend errors
3. Security: scan skills/ for suspicious patterns per SELF_IMPROVEMENT_PROCESS.md Phase 1
4. Gateway version: compare config/zero.json lastTouchedVersion vs latest OpenClaw release (check github.com/openclaw/openclaw tags)
5. Dependencies: compare backend/requirements.txt and frontend/package.json vs latest stable versions
6. LangGraph: run `docker exec zero-api pytest tests/test_orchestration.py -v` to verify routing
7. Scheduler: `curl -H "Authorization: Bearer $ZERO_GATEWAY_TOKEN" http://localhost:18792/api/system/scheduler/status` - verify jobs running
8. Fix any issues found, rebuild affected containers per CLAUDE.md deployment rules
9. Update .claude/memory/MEMORY.md with any new findings or version changes
10. Create Legion tasks for anything deferred to future sprints

**Important:** After ANY code changes, always rebuild and restart affected Docker containers before declaring done. See CLAUDE.md for exact rebuild commands.
```

---

## When to Run
- Weekly (Sunday morning recommended)
- After any infrastructure changes
- After updating Ollama models
- When Zero reports errors in Discord/WhatsApp

## What It Covers
1. Container health verification
2. Error log review
3. Security audit (ClawHub skills)
4. Gateway version check
5. Dependency updates
6. LangGraph routing tests
7. Scheduler job verification
8. Automated fixes + rebuild
9. Memory/documentation updates
10. Future work tracking in Legion
