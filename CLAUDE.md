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

## Proactive Monitoring

When starting a session or checking the system:
1. `docker ps --format "table {{.Names}}\t{{.Status}}"`
2. `docker logs --tail 100 zero-gateway 2>&1 | grep -i "error\|fail\|warn"`
3. Report and fix any issues before proceeding

## Common Issues
- **No response**: Check auth-profiles.json exists and Ollama is running
- **WhatsApp disconnected**: `docker exec -it zero-gateway node dist/index.js configure --section channels`
- **API 500 errors**: Check `docker logs zero-api` for tracebacks
- **Frontend not loading**: Verify zero-api is running on port 18792
