# Zero Platform Deep Review + Legion Integration

## Context

Zero has grown to 56 routers, 94 services, 37 pages, 71 scheduler jobs across 10+ business domains — but has never been formally audited. ADA has a baseline audit (81/100, B-) and Legion has a deep review skill with 8 phases and 10 grading dimensions. Zero needs the same treatment.

Additionally, Legion's config for Zero is stale: wrong filesystem path (`C:\code\moltbot` instead of `C:\code\zero`), references a dead gateway (OpenClaw removed), and has monitoring/auto_learn disabled.

**Goal**: Create a comprehensive baseline audit for Zero (matching ADA's format), then update Legion to actively manage Zero.

---

## Part 1: Zero Baseline Audit

### Files to Create

```
C:\code\zero\.claude\memory\quality\
  SCORING_RUBRIC.md                         # Dimension definitions & scoring guide
  MASTER_SCORECARD.md                       # Full 20-feature score table
  history\
    2026-04-baseline-audit.md               # The audit document (primary deliverable)
```

### 20 Features to Score

| # | Feature | Primary Backend | Primary Frontend |
|---|---------|----------------|-----------------|
| 1 | Orchestration/LangGraph | orchestration_graph.py, orchestrator_service.py | OrchestratorPage.tsx |
| 2 | Multi-Provider LLM Router | llm_router.py, unified_llm_client.py, 4 providers | LlmTab.tsx |
| 3 | Scheduler System (71 jobs) | scheduler_service.py | SystemHealthPage.tsx |
| 4 | TikTok Shop Pipeline | tiktok_shop_service.py + 5 related services | TikTokShopPage.tsx, ProductDetailPage.tsx |
| 5 | AI Company (5 agents) | agent_company_service.py | AiCompanyPage.tsx |
| 6 | Deep Research (STORM) | deep_research_service.py | DeepResearchPage.tsx |
| 7 | Council of Agents | council_service.py | CouncilRoomPage.tsx |
| 8 | Experiment Lab | experiment_service.py | ExperimentLabPage.tsx |
| 9 | Email/Gmail | gmail_service.py + 5 email services | EmailPage.tsx |
| 10 | Calendar | calendar_service.py | CalendarPage.tsx |
| 11 | Meeting Intelligence | 8 meeting_*.py services | MeetingsPage.tsx + 2 sub-pages |
| 12 | Prediction Markets | prediction_market_service.py | PredictionMarketsPage.tsx |
| 13 | Money Maker | money_maker_service.py | MoneyMakerPage.tsx |
| 14 | Content Agent | content_agent_service.py, publishing_service.py | ContentAgentPage.tsx |
| 15 | Ecosystem Sync | ecosystem_sync_service.py, ecosystem_health_service.py | EcosystemPage.tsx |
| 16 | Sprint/Task Management | sprint_service.py, task_service.py | SprintsPage.tsx, BoardPage.tsx |
| 17 | Knowledge Base | (in orchestrator services) | KnowledgePage.tsx |
| 18 | Frontend UI/UX | N/A (cross-cutting) | All 37 pages |
| 19 | Docker Infrastructure | docker-compose.sprint.yml, Dockerfile | N/A |
| 20 | Discord/Messaging Bridge | discord_bot.py, messaging_bridge.py | N/A |

### 5 Scoring Dimensions (matching ADA format)

| Dimension | Weight | What it measures |
|-----------|--------|-----------------|
| Backend | 30% | Async patterns, error handling, structlog, Pydantic, service separation |
| Frontend | 25% | TypeScript quality, React Query, loading states, error boundaries, dark theme |
| Testing | 20% | Test files per feature, pass rates, integration coverage |
| Docs | 15% | CLAUDE.md accuracy, inline docs, API documentation |
| Architecture | 10% | Router-service-data separation, DB schema, resilience patterns |

**Formula**: `Overall = (Backend * 0.30) + (Frontend * 0.25) + (Testing * 0.20) + (Docs * 0.15) + (Arch * 0.10)`

For infra-only features (no frontend): Backend absorbs frontend weight (0.55).
For frontend-only features: Frontend absorbs backend weight (0.55).

### Audit Execution Steps

1. **Code quality scan** — For each feature's primary files, check:
   - TODO/FIXME/HACK count (found: 38 across 9 files)
   - `except Exception` breadth (found: 181 across 30+ files)
   - `print()` statements (found: 58 across 16 files, should be structlog)
   - `datetime.now()` without UTC (found: 10 across 6 files)
   - Functions >100 LOC

2. **Test verification** — Map existing tests to features:
   - 6 test files total for 94 services (extremely low)
   - 0 frontend tests
   - 14/20 features have zero dedicated tests

3. **API endpoint smoke tests** — curl key GET endpoints on localhost:18792

4. **Frontend build check** — TypeScript compilation, dead pages, error boundaries (only 3 found)

5. **Score each feature** across 5 dimensions, compute weighted overall, assign letter grade

### Preliminary Estimates (to be validated during execution)

**Estimated platform average: ~64/100 (D)**

Critical weakness: **Testing (est ~15/100)** — 6 test files for 94 services, 0 frontend tests. This drags every feature down via 20% weight.

Secondary weakness: **Documentation (est ~58/100)** — only CLAUDE.md and MEMORY.md, no per-feature docs.

Strengths: **Backend (est ~81/100)** and **Architecture (est ~80/100)** — good async patterns, service separation, Pydantic models.

---

## Part 2: Update Legion Config for Zero

### File: `C:\code\legion\backend\app\core\legion_config.py`

**Change 1** — Fix path (line 62):
```python
# FROM:
"zero": "/managed/zero" if IS_DOCKER else "C:\\code\\moltbot",
# TO:
"zero": "/managed/zero" if IS_DOCKER else "C:\\code\\zero",
```

**Change 2** — Update Zero project config (lines 129-141):
```python
"zero": {
    "name": "Zero Personal Assistant",
    "path": _PROJECT_PATHS["zero"],
    "agent_name": "Zero",
    "type": "personal_assistant",
    "tech_stack": ["Python", "FastAPI", "React", "TypeScript", "PostgreSQL", "pgvector", "LangGraph", "APScheduler", "Kimi", "Ollama"],
    "database": {
        "type": "postgresql",
        "name": "zero",
        "host": "host.docker.internal" if IS_DOCKER else "localhost",
        "port": 5433
    },
    "services": {
        "api": "http://host.docker.internal:18792" if IS_DOCKER else "http://localhost:18792",
    },
    "monitoring": True,
    "auto_learn": True,
    "resource_heavy": True
},
```

**Changes summary**:
- Path: `moltbot` -> `zero`
- tech_stack: Added PostgreSQL, pgvector, LangGraph, APScheduler, Kimi, Ollama; removed Node.js
- database block: Added (port 5433)
- services: Removed dead `gateway` (OpenClaw removed), kept `api`; aligned Docker URL format with ADA's
- monitoring: `False` -> `True`
- auto_learn: `False` -> `True`
- Added `resource_heavy: True`

### File: `C:\code\legion\.claude\skills\legion-deep-review\knowledge\deep_review_history.json`

After audit completes, add Zero's baseline run with grade and dimension scores.

### File: `C:\code\legion\.claude\skills\legion-deep-review\knowledge\feature_grades.json`

After audit completes, add all 20 Zero feature grades for trend tracking.

---

## Part 3: Rebuild & Verify

1. **Rebuild Legion backend** to pick up config changes:
   ```bash
   docker compose -f /path/to/legion/docker-compose.yml build --no-cache legion-backend
   docker compose -f /path/to/legion/docker-compose.yml up -d legion-backend
   ```

2. **Verify Legion sees Zero**:
   ```bash
   curl http://localhost:8005/api/managed-projects | jq '.[] | select(.name == "Zero Personal Assistant")'
   ```

3. **Trigger learning**:
   ```bash
   curl -X POST http://localhost:8005/api/learn/zero
   ```

4. **Verify audit files** exist in `C:\code\zero\.claude\memory\quality\`

---

## Execution Order

| Step | Action | Files |
|------|--------|-------|
| 1 | Create quality tracking directory structure | `zero/.claude/memory/quality/` |
| 2 | Write SCORING_RUBRIC.md | `quality/SCORING_RUBRIC.md` |
| 3 | Execute code quality scan (grep for issues) | Read-only scan |
| 4 | Execute test verification | Read-only scan |
| 5 | Execute API smoke tests | curl commands |
| 6 | Execute frontend build check | docker exec |
| 7 | Score all 20 features, write grade cards | `quality/MASTER_SCORECARD.md` |
| 8 | Write baseline audit document | `quality/history/2026-04-baseline-audit.md` |
| 9 | Update Legion config (path, monitoring, tech_stack) | `legion_config.py` |
| 10 | Update Legion deep review knowledge files | `deep_review_history.json`, `feature_grades.json` |
| 11 | Rebuild Legion backend | docker compose |
| 12 | Verify integration | curl + logs |
