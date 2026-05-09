# Plan: Apply for AI Solutions Architect + Skills/Project/LinkedIn Workflow

## Context

**Target Job**: AI Solutions Architect (Part-Time) at Teiva Systems - Remote (Europe/USA)
**Key skills needed**: Solution architecture, AI/ML consulting, pre-sales, technical documentation, architecture diagrams, cloud platforms (AWS/Azure/GCP), API/system design, stakeholder management, enterprise integration.

**Problem**: FortressOS has the full resume/skills/LinkedIn/job workflow, but projects are manually entered and there's no connection to Legion (which manages 7+ repos). The user wants to:
1. Populate Fortress with projects from Legion, broken down by skills
2. Tailor their resume to the AI Solutions Architect role
3. Update LinkedIn bio
4. Build a reusable "rescan from Legion" capability

**User's Projects** (from Legion at `c:\code\legion`):
- **FortressOS** - AI job automation platform (FastAPI, React, PostgreSQL, Celery, LangGraph, pgvector)
- **Legion** - AI agent orchestration system (FastAPI, React/TS, 126 services, 26 agents, LangGraph)
- **ProfStudio** - AI skills assessment desktop app (Electron 41, React 19, TypeScript 6, Claude API, Radix UI)
- **ADA**, **Zero**, **AIContentTools**, **OllamaManager** - other managed projects

---

## Phase 1: Code Changes - Legion Integration in Fortress

### 1a. Add `legion_project_id` and `last_synced_from_legion` to Project model

**File**: [backend/app/models/project.py](backend/app/models/project.py)
- Add `legion_project_id: Mapped[Optional[int]]` (nullable, indexed) - links to Legion's project DB ID
- Add `last_synced_from_legion: Mapped[Optional[datetime]]` (nullable) - tracks freshness
- Add column via `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` in [backend/app/core/database.py](backend/app/core/database.py) `init_db()`

### 1b. Add `POST /api/projects/import-from-legion` endpoint

**File**: [backend/app/api/projects.py](backend/app/api/projects.py)
- New endpoint that calls Legion API at `http://localhost:8005/api/projects`
- Fetches all projects from Legion, maps them to Fortress Project records
- Upsert logic: match on `legion_project_id`, create or update
- Maps Legion fields -> Fortress: `name`, `description`, `tech_stack` -> `technologies`, `type` -> `category`
- Uses `httpx.AsyncClient` for async HTTP call to Legion
- Sets `is_featured=True` for key projects, `is_professional=True`
- After import, triggers skill sync for the user

**New schema** in same file:
```python
class LegionImportResponse(BaseModel):
    imported: int
    updated: int
    projects: List[ProjectResponse]
```

### 1c. Add `POST /api/projects/{id}/extract-skills` endpoint

**File**: [backend/app/api/projects.py](backend/app/api/projects.py)
- Calls `SkillService.extract_skills_from_project()` for a single project
- Returns extracted skills with categories
- Reuses existing `SkillService` from [backend/app/services/skill_service.py](backend/app/services/skill_service.py)

### 1d. Add `POST /api/projects/rescan-legion` endpoint

**File**: [backend/app/api/projects.py](backend/app/api/projects.py)
- Re-fetches from Legion API and updates existing projects
- Returns diff of what changed
- Same as import but focuses on updating existing `legion_project_id` matches

### 1e. Add `httpx` dependency

**File**: [backend/requirements.txt](backend/requirements.txt)
- Add `httpx>=0.27.0` (for async HTTP calls to Legion)

### 1f. Update CLAUDE.md with Legion reference

**File**: [CLAUDE.md](CLAUDE.md)
- Add note that Legion lives at `c:\code\legion` and manages/improves FortressOS
- Add Legion port (8005) to ports table

### 1g. Verify Legion's `/api/projects` response format

**Files** (read-only in Legion, no changes needed):
- Legion's `GET /api/projects` already returns: `id`, `name`, `description`, `type`, `tech_stack`, `path`, `auto_learn`
- This is sufficient for Fortress to import

---

## Phase 2: Data Operations (execute via API calls)

All operations use `X-User-Id: 1` header and hit `http://localhost:8001/api/`.

### 2a. Check current state
- `GET /api/profile` - see current profile, bio, skills
- `GET /api/projects` - see existing projects
- `GET /api/linkedin/profile` - see LinkedIn state
- `GET /api/skills` - see current tracked skills
- `GET /api/resume` - see current resume(s)

### 2b. Import projects from Legion
- Call new `POST /api/projects/import-from-legion` endpoint
- Or manually create via `POST /api/projects` for each:

| Project | Technologies | Category | Impact |
|---------|-------------|----------|--------|
| FortressOS | FastAPI, React, PostgreSQL, Redis, Celery, LangGraph, pgvector, SQLAlchemy, Docker, Vite | AI/ML | AI-powered job automation serving multi-tenant users with LLM routing, vector search, 18+ scrapers |
| Legion | FastAPI, React, TypeScript, PostgreSQL, LangGraph, Kimi K2.5, Docker, Qdrant | AI/ML | Autonomous AI orchestration managing 7+ projects with 26 agents and 6-layer learning |
| ProfStudio | Electron, React, TypeScript, Vite, Zustand, Radix UI, Tailwind CSS, Claude API, FastAPI, Playwright | AI/ML | Desktop AI skills assessment app with SFTP integration, multi-platform distribution |

### 2c. Sync skills from all projects
- `POST /api/skills/sync` - extracts from projects + resume + LinkedIn

### 2d. Add the job to Fortress
- Check if already scraped: query jobs table for "AI Solutions Architect" + "Teiva Systems"
- If not, create manually or use the Indeed scraper
- `POST /api/jobs` or insert via direct DB

### 2e. Tailor resume to job
- `POST /api/enhancement/tailor` with:
  - `resume_id`: primary resume ID
  - `job_description`: full Teiva Systems job posting text
  - `job_title`: "AI Solutions Architect"
  - `company`: "Teiva Systems"
  - `include_projects`: true
  - `save_as_new`: true

### 2f. Run deep evaluation
- `POST /api/deep-evaluations/evaluate/{job_id}` - get 6-block score

### 2g. Update LinkedIn bio
- `GET /api/linkedin/profile` - check current state
- If no profile exists: `POST /api/linkedin/profile/import-text` with current bio
- `POST /api/linkedin/optimize/about` - get AI suggestions incorporating all projects/skills
- `POST /api/linkedin/optimize/headline` - optimize headline for AI architect positioning
- `PUT /api/linkedin/profile` - apply updates

---

## Phase 3: Add "Solution Architecture" Skills to Skill Categories

**File**: [backend/app/services/skill_service.py](backend/app/services/skill_service.py)

The current `SKILL_CATEGORIES` lacks several skills critical for this role. Add to `soft-skills`:
- `"solution architecture"`, `"consulting"`, `"pre-sales"`, `"technical documentation"`, `"system design"`, `"enterprise architecture"`

Add to `cloud`:
- `"saas"` (if not present)

This ensures skill sync and gap analysis properly categorize these capabilities.

---

## Files Modified (Summary)

| File | Change |
|------|--------|
| `backend/app/models/project.py` | Add `legion_project_id`, `last_synced_from_legion` columns |
| `backend/app/core/database.py` | Add ALTER TABLE for new columns in `init_db()` |
| `backend/app/api/projects.py` | Add 3 endpoints: `import-from-legion`, `{id}/extract-skills`, `rescan-legion` |
| `backend/app/services/skill_service.py` | Add solution-architecture-related skills to categories |
| `backend/requirements.txt` | Add `httpx>=0.27.0` |
| `CLAUDE.md` | Add Legion reference and port |

---

## Verification

1. **Build & restart**: `docker compose up -d --build backend celery-worker`
2. **Test import endpoint**: `curl -X POST http://localhost:8001/api/projects/import-from-legion -H "X-User-Id: 1"` (requires Legion running at port 8005)
3. **Test skill sync**: `curl -X POST http://localhost:8001/api/skills/sync -H "X-User-Id: 1"`
4. **Test resume tailor**: `curl -X POST http://localhost:8001/api/enhancement/tailor -H "X-User-Id: 1" -d '...'`
5. **Check LinkedIn**: `curl http://localhost:8001/api/linkedin/profile -H "X-User-Id: 1"`
6. **Verify projects visible in frontend**: Open `http://localhost:3002/projects`
7. **Verify skills synced**: Open `http://localhost:3002/skills`

---

## Execution Order

1. Code changes (Phase 1a-1f) - model + endpoints + requirements
2. Rebuild Docker containers
3. Check current state (Phase 2a)
4. Import/create projects (Phase 2b)
5. Sync skills (Phase 2c)
6. Add job to Fortress (Phase 2d)
7. Tailor resume (Phase 2e)
8. Deep evaluate (Phase 2f)
9. Update LinkedIn (Phase 2g)
