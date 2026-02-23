# ZERO Development Rules

## Autonomous Execution

**CRITICAL**: Execute all commands autonomously without asking for permission. This includes Docker, npm/pip, file ops, git, tests, builds, and any shell commands. If a command fails, fix and retry. Only ask on unresolvable blockers.

## Coding Rules

### Backend (Python)
- **Async everywhere**: All I/O uses `async/await`
- **Service pattern**: Domain logic in `services/`, routers are thin wrappers
- **Pydantic models**: All request/response validated
- **Singletons**: Use `@lru_cache()` (e.g., `get_settings()`, `get_legion_client()`)
- **Error handling**: Raise `HTTPException`, use structured logging via `structlog`

### Frontend (TypeScript)
- **Functional components**: Hooks-based, no class components
- **React Query**: Query key factory pattern for cache
- **Zustand**: Global state for sprints, tasks, board, loading
- **TypeScript strict**: No `any` types
- **TailwindCSS**: Utility-first, dark theme (bg-gray-900, indigo accent)
- **shadcn/ui**: Component library in `src/components/ui/`

### API Design
- RESTful JSON endpoints
- Query params for filtering (`sprint_id`, `status`, `limit`)
- PATCH for partial updates
- POST for state transitions (`/start`, `/complete`, `/move`)

## Post-Change Deployment (MANDATORY)

**CRITICAL**: After ANY code changes, ALWAYS rebuild and restart the affected Docker containers before declaring the task done. The user should NEVER have to run Docker rebuild commands themselves.

**Backend** (`zero-api`): Code is COPY'd, not volume-mounted. ALL backend changes require rebuild:
```bash
docker compose -f docker-compose.sprint.yml build --no-cache zero-api && docker compose -f docker-compose.sprint.yml up -d zero-api
```

**Frontend** (`zero-ui`): Source files (`src/`, config files) ARE volume-mounted — code changes are live. But `node_modules` is NOT mounted, so **new npm packages require rebuild**:
```bash
# After npm install (new packages):
docker compose -f docker-compose.sprint.yml build --no-cache zero-ui && docker compose -f docker-compose.sprint.yml up -d zero-ui

# After source-only changes: just restart if needed
docker compose -f docker-compose.sprint.yml restart zero-ui
```

After rebuilding, verify containers are healthy:
```bash
docker ps --format "table {{.Names}}\t{{.Status}}" | grep zero
```

**Never leave changes undeployed.** Always rebuild affected containers as final step.

## Common Commands

```bash
# Start the sprint UI stack
docker compose -f docker-compose.sprint.yml up -d

# Rebuild backend (code is COPY'd, not volume-mounted)
docker compose -f docker-compose.sprint.yml build --no-cache zero-api

# View backend logs
docker logs -f zero-api

# Restart gateway after config changes
docker compose restart zero-gateway

# Check Ollama models
ollama list
```

## SEARCH BEFORE EXPLORING (MANDATORY)

Before using Glob/Grep to explore the codebase, use QMD MCP tools for documentation lookup:

- `qmd_search "keyword query"` - Fast BM25 keyword search across all project .md docs
- `qmd_vsearch "conceptual query"` - Semantic search by meaning (e.g., "how does auth work")
- `qmd_query "complex question"` - Hybrid BM25 + vector + LLM re-ranking (best quality, slower)
- `qmd_get "path/to/file.md"` - Retrieve full document content
- `qmd_multi_get "docs/product/*.md"` - Retrieve multiple docs by pattern

**When to use which tool:**
- **QMD**: Finding docs about "how does X work", "what's the pattern for Y", discovering relevant guides
- **Direct Read**: When you know the exact file path from the Module Map in MEMORY.md
- **Glob/Grep**: When searching .py/.tsx source code (QMD only indexes .md files)

## Proactive Monitoring

When starting a session or checking the system:
1. `docker ps --format "table {{.Names}}\t{{.Status}}"`
2. `docker logs --tail 100 zero-gateway 2>&1 | grep -i "error\|fail\|warn"`
3. Report and fix any issues before proceeding

## Legion Sprint Management (MANDATORY)

**CRITICAL**: ALL code changes to Zero MUST be tracked as tasks in Legion (project_id=8). Before starting any implementation work:
1. Create a sprint in Legion for the work (or use the active sprint)
2. Break the work into tasks with clear descriptions
3. Create tasks in Legion via `LegionClient.create_task()`
4. Update task status as work progresses
5. Close the sprint when all tasks are complete

This ensures Zero's work is observable, auditable, and can be monitored via the ecosystem dashboard. Never make untracked changes.

## Common Issues
- **No response**: Check auth-profiles.json exists and Ollama is running
- **WhatsApp disconnected**: `docker exec -it zero-gateway node dist/index.js configure --section channels`
- **API 500 errors**: Check `docker logs zero-api` for tracebacks
- **Frontend not loading**: Verify zero-api is running on port 18792
