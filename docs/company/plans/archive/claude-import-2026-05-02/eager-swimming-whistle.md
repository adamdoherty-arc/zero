# Plan: Transform Legion into a Learning-First AI App Builder

## Context

**Problem**: Legion is an AI Agent Orchestration System (38/100 maturity) that can improve existing projects but cannot create new ones from scratch. Tools like Lovable ($20M ARR in 2 months), Bolt.new ($40M ARR in 6 months), and Replit Agent dominate the "prompt → deployed app" space — but none of them learn across projects. Legion's 6-layer learning system, 29 agents, and multi-project orchestration give it a unique edge if we add the missing "builder" pipeline.

**Approach**: Hybrid — build the learning-first core (spec inference, scaffolding, code generation, preview) then layer on polish (visual editing, deploy) informed by what the learning system reveals works best. Full tech stack flexibility (any frontend + any backend). Sprint-by-sprint delivery, ~2-3 weeks each.

**Competitive differentiator**: A builder that gets smarter with every project it creates.

---

## Research Summary

### Lovable/Bolt Architecture Pattern
All successful AI builders follow the same core loop:
1. **Spec Inference**: Prompt → structured requirements (features, pages, data model)
2. **Scaffolding**: Create project structure + install dependencies
3. **Code Generation**: Generate components, models, routes, API endpoints
4. **Preview**: Live dev server with error feedback to AI
5. **Iteration**: Chat-based refinement with context-aware file selection
6. **Deploy**: One-click to production

**Key Lovable innovation**: Multi-model hydration — fast small models select relevant files, large models generate code. Only ~5-10 files are fed to the LLM per change, not the entire codebase.

### GitReverse.com / Repo Ingestion
- GitReverse is web-only (no API), turns repos into narrative prompts via LLM
- **Repomix** is the production choice: open-source CLI + MCP server, token counting, security scanning, XML/Markdown/JSON output, `pack_remote_repository` for any GitHub repo
- Integration: Repomix CLI in Docker → external_knowledge_daemon calls it → patterns stored in knowledge base → templates auto-generated

### Legion's Existing Assets to Leverage
| Asset | How It Helps |
|-------|-------------|
| `UnifiedLLMService` + 2-tier LLM | Spec inference (Kimi) + code gen (Ollama) |
| `CodeApplicatorService` | Apply generated code with validation + rollback |
| `AutonomousSprintExecutor` | Test feedback loop + error recovery |
| `KnowledgeIngestionService` (11 domains) | Store framework patterns for reuse |
| `EpisodicMemoryService` | Remember successful scaffolding approaches |
| `LearningCouncilService` | Vote on tech stack choices |
| `AgentExecutionService` + 29 agents | Parallelize frontend/backend/test generation |
| `external_knowledge_daemon` | Already discovers GitHub repos |
| `ProjectDB` + sprint tracking | Track builder projects in existing system |
| `ChatService` + WebSocket events | Real-time iteration interface |

---

## Implementation: 6 Sprints

### Sprint 1: Project Spec Inference (Builder-01)
**Goal**: User types a prompt → Legion produces a structured project specification

**New service**: `ProjectSpecService`
- Takes natural language prompt (e.g., "Build me a Kanban board app")
- Uses Kimi K2.5 (planning tier) with structured output schema
- Produces `ProjectSpec` with:
  - `name`, `description`
  - `tech_stack`: `{frontend: "react"|"vue"|"svelte"|"nextjs", backend: "fastapi"|"express"|"django"|"nextjs-api", database: "postgresql"|"sqlite"|"mongodb", styling: "tailwind"|"css-modules"|"styled-components"}`
  - `features`: list of feature descriptions
  - `pages`: list of `{name, route, components[], description}`
  - `data_model`: list of `{entity, fields[], relationships[]}`
  - `api_endpoints`: list of `{method, path, description, request_schema, response_schema}`
- Learning integration: Query episodic memory for similar past projects, use as few-shot examples
- Council integration: If ambiguous, learning council votes on tech stack

**New model**: `ProjectSpecDB` (Alembic migration)
- Links to `ProjectDB` via project_id
- Stores full spec JSON + version history
- Tracks which spec generated which sprint

**New endpoint**: `POST /api/projects/from-prompt`
- Input: `{prompt: string, preferences?: {frontend?, backend?, database?}}`
- Output: `ProjectSpec` for user review/edit before scaffolding

**Frontend changes**:
- `CreateProjectDialog.tsx`: Add "Create from Prompt" tab
- New component: `ProjectSpecReview.tsx` — shows generated spec, allows edits before confirming

**Files**:
- NEW: `backend/app/services/project_spec_service.py`
- NEW: `backend/app/models/project_spec.py`
- NEW: `backend/alembic/versions/025_add_project_specs.py`
- MODIFY: `backend/app/api/endpoints/projects.py` — add `/from-prompt` endpoint
- MODIFY: `frontend/src/components/CreateProjectDialog.tsx` — prompt input tab
- NEW: `frontend/src/components/project/ProjectSpecReview.tsx`
- MODIFY: `frontend/src/hooks/useProjectDetail.ts` — add `useCreateFromPrompt` mutation

---

### Sprint 2: Project Scaffolding (Builder-02)
**Goal**: Confirmed spec → runnable empty project with correct structure

**New service**: `ProjectScaffolderService`
- Takes `ProjectSpec` as input
- Creates project directory under managed projects path
- Framework-specific scaffolding:
  - **React**: Vite + TypeScript + selected styling
  - **Vue**: Vite + TypeScript + selected styling
  - **Svelte**: SvelteKit + TypeScript
  - **Next.js**: Next.js App Router + TypeScript
  - **FastAPI**: pyproject.toml + uvicorn + SQLAlchemy
  - **Express**: package.json + TypeScript + Prisma
  - **Django**: manage.py + settings + apps structure
- Template system: Each framework combo has a base template (JSON config + file templates)
- Dependency installation via subprocess (npm/pip)
- Git init + initial commit
- Registers project in `ProjectDB` with auto_sprint_enabled=true

**Template registry**: `backend/app/services/builder_templates/`
- `react-vite-tailwind/` — base React template
- `fastapi-sqlalchemy/` — base FastAPI template
- `nextjs-app-router/` — base Next.js template
- Templates are JSON configs + Jinja2 file templates
- Learning system can modify templates based on success rates

**New endpoint**: `POST /api/projects/{id}/scaffold`
- Input: `ProjectSpec`
- Output: `{project_id, path, status, files_created}`
- Async — returns immediately, sends WebSocket updates

**Files**:
- NEW: `backend/app/services/project_scaffolder_service.py`
- NEW: `backend/app/services/builder_templates/` (directory with templates)
- MODIFY: `backend/app/api/endpoints/projects.py` — add `/scaffold` endpoint
- MODIFY: `backend/app/services/project_service.py` — wire scaffolding into project creation

---

### Sprint 3: Code Generation Pipeline (Builder-03)
**Goal**: Scaffolded project → generated components, models, routes, API endpoints

**Enhance existing**: `CodeApplicatorService` + `ClaudeExecutor`
- New method: `generate_from_spec(spec: ProjectSpec) -> List[CodeChange]`
- Generation order (respects dependency):
  1. Database models / schemas
  2. API endpoints / routes
  3. Frontend components (atoms → molecules → pages)
  4. Page routing configuration
  5. Shared utilities (auth, API client, types)
- Each step uses Ollama (execution tier) with spec context
- Knowledge injection: retrieves similar components from episodic memory
- Error recovery: if generated code doesn't compile, retry with error context

**Context-aware file selection** (Lovable's key innovation):
- Don't feed entire project to LLM for each change
- `ContextSelectionService` — uses embeddings or keyword matching to select 5-10 relevant files
- Reduces token usage by ~80%, reduces hallucination

**Agent parallelization**:
- Frontend agent generates components while backend agent generates API
- Test agent generates basic test stubs
- Swarm coordination via existing `AgentSwarmService`

**Files**:
- NEW: `backend/app/services/code_generation_pipeline.py`
- NEW: `backend/app/services/context_selection_service.py`
- MODIFY: `backend/app/services/code_applicator_service.py` — enhance for greenfield generation
- MODIFY: `backend/app/services/agent_swarm_service.py` — builder-specific swarm preset

---

### Sprint 4: Live Preview + Error Feedback (Builder-04)
**Goal**: See generated app running, AI auto-fixes build errors

**New service**: `PreviewService`
- Manages dev server processes per project (Vite, Next.js dev, uvicorn)
- Tracks PID, port, status per project
- Captures stdout/stderr for error detection
- Auto-kills stale servers after timeout
- Health check endpoint per preview

**Error feedback loop** (critical for quality):
- Preview server starts → captures build/runtime errors
- Errors fed back to code generation pipeline
- AI generates fix → applies → restarts preview
- Max 3 auto-fix attempts before asking user
- Records fix patterns in episodic memory

**Frontend**:
- New component: `ProjectPreview.tsx` — iframe showing live app
- Split-pane layout: code editor (left) + preview (right)
- Build status indicator (building, ready, error)
- WebSocket updates for real-time feedback

**Files**:
- NEW: `backend/app/services/preview_service.py`
- NEW: `backend/app/api/endpoints/preview.py`
- NEW: `frontend/src/components/project/ProjectPreview.tsx`
- NEW: `frontend/src/components/project/BuilderLayout.tsx` — split pane
- MODIFY: `frontend/src/pages/ProjectDetail.tsx` — add preview tab
- MODIFY: `frontend/src/hooks/useProjectDetail.ts` — preview hooks

---

### Sprint 5: Interactive Chat Iteration (Builder-05)
**Goal**: "Make the header blue" → targeted code change → preview updates

**Enhance existing**: `ChatService`
- Project-scoped chat context (knows which project, which files)
- Context-aware file selection: only load relevant files per message
- Intent classification: UI change vs feature addition vs bug fix vs refactor
- Targeted code generation: modify specific file(s) based on intent
- Preview auto-refresh after successful change

**Multi-turn conversation**:
- Chat history stored per project
- AI remembers previous changes and can reference them
- "Undo last change" support via git revert
- "Show me the code for X" support

**Frontend**:
- Project-scoped chat panel (right sidebar or bottom drawer)
- Shows which files were modified per message
- "Apply" / "Reject" buttons for each suggested change
- Before/after diff view

**Files**:
- MODIFY: `backend/app/services/chat_service.py` — project-scoped context
- MODIFY: `backend/app/api/endpoints/chat.py` — project context parameter
- MODIFY: `frontend/src/pages/AskLegion.tsx` — project-scoped mode
- NEW: `frontend/src/components/project/BuilderChat.tsx`
- MODIFY: `frontend/src/hooks/useChat.ts` — project context

---

### Sprint 6: External Knowledge via Repomix (Builder-06)
**Goal**: Legion learns patterns from top OSS repos, builds template library

**Repomix integration**:
- Add `npx repomix` to Docker image (Node.js already available in frontend container)
- New method on `ExternalKnowledgeDaemon`: `ingest_repo_via_repomix(owner, repo)`
- Calls `repomix --remote {owner}/{repo} --output-style xml --include "src/**"`
- Parses XML output → extracts patterns (component structure, API patterns, DB schemas)
- Stores in `knowledge_sources` table with domain tags

**Template library**:
- New service: `TemplateLibraryService`
- Auto-generates templates from successfully ingested repos
- Templates include: file structure, key patterns, dependencies, config
- Learning council rates templates by quality
- Best templates surface in project creation flow

**Scheduled ingestion**:
- Monthly cron: scan trending repos in relevant categories
- Categories: React, Vue, FastAPI, Express, Django, Next.js, SvelteKit
- Rate limited to 10 repos/month (GitHub API limits)
- Dedup by repo URL

**New endpoint**: `POST /api/external-knowledge/ingest-repo`
- Input: `{owner: string, repo: string}`
- Output: `{knowledge_source_id, patterns_extracted, template_created}`

**Files**:
- MODIFY: `backend/app/services/external_knowledge_daemon.py` — add Repomix pipeline
- NEW: `backend/app/services/template_library_service.py`
- NEW: `backend/app/api/endpoints/templates.py`
- MODIFY: `docker-compose.yml` — ensure Node.js available for Repomix
- MODIFY: `frontend/src/components/CreateProjectDialog.tsx` — template browser

---

## Sprint Tracking

All sprints tracked as Legion project_id=3:

| Sprint | Name | Tasks | Depends On |
|--------|------|-------|------------|
| Builder-01 | Project Spec Inference | 5 | None |
| Builder-02 | Project Scaffolding | 5 | Builder-01 |
| Builder-03 | Code Generation Pipeline | 5 | Builder-02 |
| Builder-04 | Live Preview + Error Feedback | 5 | Builder-03 |
| Builder-05 | Interactive Chat Iteration | 4 | Builder-04 |
| Builder-06 | External Knowledge via Repomix | 5 | Builder-01 (parallel with 02-05) |

**Builder-06 can run in parallel with Builder-02 through 05** since it's about knowledge ingestion, not the builder pipeline itself.

---

## Verification Plan

After each sprint:
1. **Builder-01**: `curl POST /api/projects/from-prompt -d '{"prompt":"Build a todo app"}'` → returns valid ProjectSpec
2. **Builder-02**: Spec → scaffolded project that `npm run dev` / `uvicorn` starts clean
3. **Builder-03**: Scaffolded project → generated code that compiles and serves pages
4. **Builder-04**: Preview iframe shows working app, build errors auto-fix
5. **Builder-05**: Chat message "Add dark mode" → modifies correct files → preview updates
6. **Builder-06**: `POST /api/external-knowledge/ingest-repo` for `tiangolo/fastapi` → patterns stored

**End-to-end verification**: Create a complete app from prompt, iterate via chat, verify learning system records patterns for future projects.

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Full flexibility = template explosion | Start with React+FastAPI, add frameworks incrementally based on demand |
| Dev server management in Docker | Run preview servers in isolated containers, not in Legion backend |
| LLM token costs for code generation | Context-aware file selection limits tokens per call |
| Generated code quality | QA pipeline validates before preview, episodic memory improves over time |
| Template library spam | Council votes on template quality, minimum threshold for storage |

---

## What This Achieves

After all 6 sprints, Legion will be:
1. **A builder**: "Build me a Kanban app" → working app with preview
2. **A learner**: Every project improves future scaffolding + generation
3. **An improver**: After initial build, Legion continues improving autonomously via existing sprint execution
4. **A knowledge base**: External repo patterns inform better generation
5. **Framework-agnostic**: React, Vue, Svelte, Next.js + FastAPI, Express, Django

**What Lovable/Bolt still can't do**: Learn from past projects, improve autonomously, manage multiple projects, enforce quality gates, track incidents/releases.

---

## Documentation Requirements

### Step 0 (Before any code): Save plan + update docs

1. **Save this plan to Legion-accessible location**:
   - Create `.legion/plans/` directory for strategic plans
   - Save as `.legion/plans/BUILDER_MODE_ROADMAP.md`
   - This will be accessible from the ProductDocs page in the UI

2. **Update CLAUDE.md** with new section:
   - Add "Builder Mode" section under capabilities
   - Document new services, endpoints, and frontend pages as they're built
   - Keep sprint history updated (Builder-01 through Builder-06)

3. **Update .legion/PRODUCT.md**:
   - Add Builder Mode to product description
   - Update tech stack to reflect new capabilities
   - Add roadmap timeline

4. **Keep docs current during execution**:
   - Each sprint completion updates CLAUDE.md sprint history
   - New endpoints documented in API reference
   - New pages documented in frontend section
   - MEMORY.md updated with cross-session learnings
