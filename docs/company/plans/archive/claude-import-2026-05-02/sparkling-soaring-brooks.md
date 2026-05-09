# Plan: Onboard profstudio + Create Reusable Project Take-In Flow

## Context

**Why**: Legion manages 6 projects but has no standardized "project take-in" process. Adding a new project requires manual edits across 3 config files, a DB registration function, startup wiring, and Docker volume mount. The user wants to onboard **profstudio** (AI-powered proficiency assessment desktop app — Electron + React + TypeScript + FastAPI) and establish a repeatable flow for future projects.

**profstudio repo**: `https://github.com/adamdoherty-arc/profstudio`
**Local clone**: `C:\code\profstudio` (already cloned, last touched Mar 22)
**Tech stack**: Electron 41, React 19, TypeScript 6, Vite 8, FastAPI, Radix UI, Tailwind CSS, Zustand, Anthropic SDK, Playwright

**Current state**: No "project take-in" plan type exists. Projects are added via bespoke `ensure_*_project()` functions + hardcoded config entries. This works but doesn't scale.

---

## Sprint: `Ops-03: Onboard profstudio + Project Take-In Flow`

Tracked as a Legion sprint (project_id=3).

### Step 1: Git pull profstudio to latest

```bash
cd C:\code\profstudio && git pull origin main
```

Ensures we have the latest docs and package.json for the knowledge scan.

### Step 2: Add profstudio to `_PROJECT_PATHS` in legion_config.py

**File**: [legion_config.py:58-64](backend/app/core/legion_config.py#L58-L64)

Add after the `fortressos` entry:
```python
"profstudio": "/managed/profstudio" if IS_DOCKER else "C:\\code\\profstudio",
```

### Step 3: Add profstudio to `MANAGED_PROJECTS` in legion_config.py

**File**: [legion_config.py:70-168](backend/app/core/legion_config.py#L70-L168)

Add after the `ollama_manager` entry:
```python
"profstudio": {
    "name": "ProfStudio",
    "path": _PROJECT_PATHS["profstudio"],
    "agent_name": "ProfStudio",
    "type": "desktop_application",
    "tech_stack": [
        "Electron", "React", "TypeScript", "Vite",
        "FastAPI", "Python", "Radix UI", "Tailwind CSS",
        "Zustand", "Anthropic SDK", "Playwright"
    ],
    "services": {},
    "monitoring": True,
    "auto_learn": True,
},
```

### Step 4: Add profstudio to sprint_execution.py MANAGED_PROJECTS

**File**: [sprint_execution.py:598-629](backend/app/models/sprint_execution.py#L598-L629)

Add after the `legion` entry:
```python
"profstudio": ManagedProjectConfig(
    name="ProfStudio",
    path=_PROJECT_PATHS.get("profstudio", "C:\\code\\profstudio"),
    claude_config="CLAUDE.md",
    sprints_dir="docs/"
),
```

### Step 5: Create `ensure_profstudio_project()` in project_service.py

**File**: [project_service.py](backend/app/services/project_service.py) (after `ensure_gpu_project` at line ~430)

Follow the exact `ensure_ollama_project()` pattern:
- Idempotent: check `ProjectDB.name == "ProfStudio"`, create if missing
- Fields: `name="ProfStudio"`, `path=` from `_PROJECT_PATHS`, `git_url="https://github.com/adamdoherty-arc/profstudio"`, `git_branch="main"`, `tech_stack=[...]`, `auto_sprint_enabled=True`, `autonomous_mode_enabled=False`
- No `_archive_wrong_virtual_plans` call (profstudio is a real project, not virtual)

### Step 6: Register in main.py startup

**File**: [main.py:113](backend/main.py#L113) (after GPU Manager block)

Add registration call following the GPU Manager pattern:
```python
try:
    from app.services.project_service import ensure_profstudio_project
    async with AsyncSessionLocal() as db:
        profstudio_id = await ensure_profstudio_project(db)
        print(f"   [OK] ProfStudio project registered (id={profstudio_id})")
except Exception as e:
    print(f"   [WARN] ProfStudio project registration failed: {e}")
```

### Step 7: Add Docker volume mount

**File**: [docker-compose.yml:202](docker-compose.yml#L202) (after fortressos volume)

```yaml
- ${PROFSTUDIO_PATH:-C:/code/profstudio}:/managed/profstudio
```

### Step 8: Docker rebuild and verify startup

```bash
docker-compose build legion-backend && docker-compose up -d
docker logs legion-backend --tail 30 2>&1 | grep -i profstudio
# Expect: [OK] ProfStudio project registered (id=N)
```

### Step 9: Verify plan seeding and knowledge scan

The deferred `_bootstrap_all_projects()` (30s after startup) will automatically:
1. Scan `C:\code\profstudio` filesystem — extracts file structure, dependencies from package.json, documentation from README/CLAUDE.md/docs/, tech stack detection
2. `seed_default_plans()` will create 3 plans for profstudio:
   - `project_review` — daily 6 AM
   - `docker_logs_review` — daily 2 PM
   - `dependency_check` — weekly Monday 3 PM

Verify:
```bash
curl -s http://localhost:8005/api/projects | python -c "import json,sys; [print(f'{p[\"id\"]}: {p[\"name\"]}') for p in json.load(sys.stdin) if 'Prof' in p.get('name','')]"
curl -s http://localhost:8005/api/plans | python -c "import json,sys; [print(f'{p[\"id\"]}: {p[\"name\"]} ({p[\"plan_type\"]})') for p in json.load(sys.stdin).get('plans',[]) if 'Prof' in p.get('name','')]"
```

### Step 10: Manually trigger first dependency review

After plan seeding is confirmed, trigger the dependency check immediately (don't wait for Monday):
```bash
# Find profstudio project id from step 9, then:
curl -s -X POST http://localhost:8005/api/plans/{dependency_plan_id}/run
```

This runs npm dependency analysis on package.json — detects outdated packages, vulnerabilities, modernization opportunities.

### Step 11: Import additional GitHub documentation

The knowledge scan already reads README.md and CLAUDE.md from the local clone. For deeper docs (architecture/, testing/, troubleshooting/ subdirs), fetch from GitHub and store as knowledge entries:

```bash
# Fetch docs listing
gh api repos/adamdoherty-arc/profstudio/contents/docs --jq '.[].name'
# For each doc file, fetch content and store via knowledge API
```

Alternatively, the local filesystem scan should already pick up `docs/*.md` files during `_extract_documentation()` in project_knowledge_service.py.

### Step 12: Create sprint in Legion DB

Create the tracking sprint:
```sql
INSERT INTO sprints (name, description, project_id, status, priority, total_tasks, created_at, updated_at)
VALUES ('Ops-03: Onboard profstudio + Project Take-In Flow',
        'Register profstudio as managed project, import docs, trigger scans, create reusable take-in checklist',
        3, 'ACTIVE', 1, 6, NOW(), NOW());
```

---

## Reusable Take-In Checklist (for future projects)

No new service or API endpoint needed yet — that's over-engineering for the current scale of ~7 projects. Instead, create a checklist document that standardizes the manual steps.

If the project count grows past 10, consider adding a `POST /projects/take-in` endpoint that orchestrates Steps 2-9 automatically.

### Checklist: Adding a New Project to Legion

1. **Clone**: `git clone <repo_url> C:\code\<project_name>`
2. **Config**: Add to `_PROJECT_PATHS` + `MANAGED_PROJECTS` in [legion_config.py](backend/app/core/legion_config.py)
3. **Execution config**: Add `ManagedProjectConfig` in [sprint_execution.py](backend/app/models/sprint_execution.py)
4. **DB registration**: Add `ensure_<project>_project()` in [project_service.py](backend/app/services/project_service.py)
5. **Startup**: Wire into [main.py](backend/main.py) after existing registrations
6. **Docker**: Add volume mount `${VAR:-path}:/managed/<name>` in [docker-compose.yml](docker-compose.yml)
7. **Rebuild**: `docker-compose build legion-backend && docker-compose up -d`
8. **Verify**: Check startup logs for `[OK]`, verify plans seeded, trigger first dependency scan
9. **Sprint**: Create tracking sprint in Legion DB (project_id=3)

---

## Files Modified

| File | Change |
|------|--------|
| [backend/app/core/legion_config.py](backend/app/core/legion_config.py) | Add profstudio to `_PROJECT_PATHS` + `MANAGED_PROJECTS` |
| [backend/app/models/sprint_execution.py](backend/app/models/sprint_execution.py) | Add profstudio `ManagedProjectConfig` |
| [backend/app/services/project_service.py](backend/app/services/project_service.py) | Add `ensure_profstudio_project()` |
| [backend/main.py](backend/main.py) | Add startup registration call |
| [docker-compose.yml](docker-compose.yml) | Add volume mount |

No new files. No migrations. No frontend changes.

---

## Verification

1. **Startup log**: `[OK] ProfStudio project registered (id=N)` within first 5s
2. **Plans**: 3 plans created (project_review, docker_logs_review, dependency_check)
3. **Knowledge**: `GET /api/projects/{id}` shows populated `tech_stack`, `architecture_summary`
4. **Docker volume**: `docker exec legion-backend ls /managed/profstudio/package.json` succeeds
5. **Health**: `curl localhost:8005/health` still healthy
6. **Dependency scan**: First run produces findings from package.json analysis
