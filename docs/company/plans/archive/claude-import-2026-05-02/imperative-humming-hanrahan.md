# Plan: Autonomous Feature Engine (AFE)

## Context

The feature-researcher skill was created and run successfully (48 discoveries), but it only researches -- it doesn't implement. The user wants a **fully autonomous engine** that discovers features, picks the best candidates, implements them, reviews the results, and surfaces everything in a UI dashboard. Each run does 1 improvement (grade bump on weakest feature) + 1 new feature build (highest-scored discovery). Reports are stored in the database and visible on a new frontend page.

---

## Architecture

**Backend is state tracker, skill does implementation.** The backend service stores run history, discoveries, implementations, and grade changes in PostgreSQL. The actual code implementation is orchestrated by the `/auto-engine` Claude skill, which calls `feature-builder` and `feature-reviewer` sub-skills. This keeps the API clean.

**Discovery data lives in both JSON and DB.** Existing `discovery_database.json` (48 features) seeds the DB. New discoveries write to both JSON (skill compatibility) and `afe_discoveries` table (UI). DB is source of truth for the UI.

**COS pattern reused.** DB schema, router, and orchestrator follow the proven COS pattern exactly.

---

## Files to Create

| # | File | Purpose |
|---|------|---------|
| 1 | `backend/services/auto_engine/__init__.py` | Package init |
| 2 | `backend/services/auto_engine/schemas.py` | Pydantic models + enums |
| 3 | `backend/services/auto_engine/orchestrator.py` | Core 5-phase engine |
| 4 | `backend/services/auto_engine/discovery_engine.py` | Load + score discoveries |
| 5 | `backend/services/auto_engine/triage_engine.py` | Pick improvement + build targets |
| 6 | `backend/services/auto_engine/grade_reader.py` | Parse markdown grade cards |
| 7 | `backend/routers/auto_engine.py` | Router at `/api/auto-engine` (8 endpoints) |
| 8 | `frontend/src/hooks/useAutoEngine.ts` | React Query v5 hooks (8 hooks) |
| 9 | `frontend/src/pages/AutoEngineHub.tsx` | Main page, 4 tabs |
| 10 | `frontend/src/components/auto-engine/RunHistoryTable.tsx` | Run history table |
| 11 | `frontend/src/components/auto-engine/DiscoveryList.tsx` | Discovery list with scores |
| 12 | `frontend/src/components/auto-engine/ImplementationCard.tsx` | Implementation detail cards |
| 13 | `frontend/src/components/auto-engine/GradeChangeChart.tsx` | Before/after grade chart |
| 14 | `.claude/skills/auto-engine/SKILL.md` | Skill definition |
| 15 | `.claude/memory/topics/auto-engine.md` | Topic file |

## Files to Modify

| # | File | Change |
|---|------|--------|
| 1 | `backend/infrastructure/database_migrations.py` | Add 4 AFE table migrations |
| 2 | `backend/main.py` | Import + register `auto_engine` router |
| 3 | `frontend/src/App.tsx` | Add lazy import + route `/auto-engine` |
| 4 | `CLAUDE.md` | Add auto-engine to topic/grade/skill tables |

---

## Database Schema (4 tables)

```sql
-- Run tracking
CREATE TABLE afe_runs (
    id SERIAL PRIMARY KEY,
    run_id VARCHAR(100) NOT NULL UNIQUE,
    mode VARCHAR(50) NOT NULL DEFAULT 'full',     -- full/discover_only/improve_only/build_only
    status VARCHAR(30) NOT NULL DEFAULT 'running', -- running/completed/failed
    phase VARCHAR(30) DEFAULT 'discover',          -- discover/triage/implement/review/report
    discoveries_count INTEGER DEFAULT 0,
    improvement_target VARCHAR(200),
    grade_before DECIMAL(5,2),
    grade_after DECIMAL(5,2),
    grade_delta DECIMAL(5,2),
    build_target VARCHAR(200),
    build_discovery_id VARCHAR(100),
    started_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    completed_at TIMESTAMP WITH TIME ZONE,
    duration_seconds DECIMAL(10,2),
    summary TEXT,
    report JSONB DEFAULT '{}'
);
-- Indexes: status, started_at DESC, mode

-- Discoveries (seeded from discovery_database.json)
CREATE TABLE afe_discoveries (
    id SERIAL PRIMARY KEY,
    run_id VARCHAR(100) NOT NULL,
    discovery_id VARCHAR(100) NOT NULL UNIQUE,
    name VARCHAR(500) NOT NULL,
    category VARCHAR(50) NOT NULL,
    source VARCHAR(200),
    description TEXT,
    user_impact DECIMAL(4,3), competitive_gap DECIMAL(4,3),
    technical_feasibility DECIMAL(4,3), synergy_with_existing DECIMAL(4,3),
    market_demand DECIMAL(4,3), composite_score DECIMAL(5,2),
    score_band VARCHAR(30),
    exists_in_ada VARCHAR(20) DEFAULT 'no',
    ada_gap TEXT, effort VARCHAR(5),
    integration_points TEXT[],
    status VARCHAR(30) DEFAULT 'new',  -- new/accepted/rejected/deferred/implemented
    discovered_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
-- Indexes: run_id, composite_score DESC, status, category

-- Implementations
CREATE TABLE afe_implementations (
    id SERIAL PRIMARY KEY,
    run_id VARCHAR(100) NOT NULL,
    implementation_id VARCHAR(100) NOT NULL UNIQUE,
    type VARCHAR(30) NOT NULL,           -- improvement/new_feature
    target_feature VARCHAR(200) NOT NULL,
    dimension_improved VARCHAR(50),
    weakness_addressed TEXT,
    discovery_id VARCHAR(100),
    files_created TEXT[] DEFAULT '{}',
    files_modified TEXT[] DEFAULT '{}',
    review_grade_before DECIMAL(5,2),
    review_grade_after DECIMAL(5,2),
    review_passed BOOLEAN,
    review_report JSONB DEFAULT '{}',
    status VARCHAR(30) DEFAULT 'planned', -- planned/in_progress/completed/failed
    started_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    completed_at TIMESTAMP WITH TIME ZONE
);
-- Indexes: run_id, type, status, target_feature

-- Grade changes
CREATE TABLE afe_grade_changes (
    id SERIAL PRIMARY KEY,
    run_id VARCHAR(100) NOT NULL,
    feature_name VARCHAR(200) NOT NULL,
    dimension VARCHAR(50),  -- NULL=overall, or backend/frontend/testing/docs/arch
    grade_before DECIMAL(5,2) NOT NULL,
    grade_after DECIMAL(5,2) NOT NULL,
    grade_delta DECIMAL(5,2) NOT NULL,
    letter_before VARCHAR(3),
    letter_after VARCHAR(3),
    changed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
-- Indexes: run_id, feature_name, grade_delta DESC, changed_at DESC
```

---

## Router Endpoints (`/api/auto-engine`)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/status` | Engine status, last run, next actions |
| GET | `/runs` | Paginated run history |
| GET | `/runs/{run_id}` | Full run with discoveries + implementations + grades |
| GET | `/discoveries` | All discoveries, filterable by category/score/status |
| GET | `/implementations` | All implementations, filterable by type/status |
| GET | `/grade-changes` | Grade change history |
| POST | `/trigger` | Trigger a new run (mode parameter) |
| GET | `/next-actions` | Preview what next run would do |

---

## Frontend Page (`/auto-engine`)

4 tabs: **Overview | Discoveries | Implementations | Grade Impact**

**Overview**: 4 stat cards (runs, discoveries, implementations, avg grade delta) + engine status + next actions preview + recent runs table

**Discoveries**: Sortable/filterable table of all 48+ discoveries with score, band, effort, status

**Implementations**: Cards per implementation showing type, target, files changed, before/after grade

**Grade Impact**: Recharts bar chart (before/after per implementation) + platform average timeline

---

## Skill Modes (`/auto-engine`)

| Mode | What Happens |
|------|-------------|
| `/auto-engine` | Full cycle: discover + triage + implement 1 improvement + implement 1 new feature + review + report |
| `/auto-engine --discover-only` | Research only, no implementation |
| `/auto-engine --improve-only` | Improve weakest feature only |
| `/auto-engine --build-only` | Build top discovery only |
| `/auto-engine --status` | Print engine status |
| `/auto-engine --history` | Print run history |

---

## Build Order

1. **Database**: Add 4 migration tuples to `database_migrations.py` → docker restart
2. **Backend schemas**: `schemas.py` (enums + Pydantic models)
3. **Backend services**: `grade_reader.py` → `discovery_engine.py` → `triage_engine.py` → `orchestrator.py`
4. **Router**: `auto_engine.py` + register in `main.py` → docker restart → verify endpoints
5. **Frontend hooks**: `useAutoEngine.ts`
6. **Frontend components**: 4 components in `auto-engine/` directory
7. **Frontend page**: `AutoEngineHub.tsx` + route in `App.tsx`
8. **Skill**: `.claude/skills/auto-engine/SKILL.md`
9. **Seed data**: Populate `afe_discoveries` from `discovery_database.json`
10. **Docs**: Topic file, grade card, CLAUDE.md updates

---

## Reference Files

- `backend/services/cos/orchestrator.py` - Orchestrator pattern to follow
- `backend/services/cos/schemas.py` - Pydantic schema pattern
- `backend/routers/cos.py` - Router pattern
- `backend/infrastructure/database_migrations.py` - Migration tuple format
- `.claude/skills/feature-researcher/knowledge/discovery_database.json` - Seed data (48 features)
- `.claude/memory/quality/MASTER_SCORECARD.md` - Grade data to parse
- `.claude/memory/grades/kronos.md` - Grade card format example

---

## Verification

1. `docker restart ada-backend` + check logs for clean startup
2. `curl /api/auto-engine/status` returns 200 with `is_running: false`
3. `curl /api/auto-engine/discoveries?limit=5` returns seeded discoveries
4. `curl /api/auto-engine/next-actions` returns Kronos (improvement) + Walk-Forward Opt (build)
5. Navigate to `http://localhost:5420/auto-engine` - page loads with 4 tabs
6. `/auto-engine --status` via skill prints engine status
