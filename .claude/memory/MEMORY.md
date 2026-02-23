# Zero Development Memory

## Architecture Overview

### Components
- **Gateway** (`src/`): TypeScript Node.js bot gateway (OpenClaw.ai)
  - Handles WhatsApp, Discord, Slack channels
  - Routes messages to agents
  - Runs in Docker container `zero-gateway`

- **Backend** (`backend/`): FastAPI Python API
  - Sprint and task management
  - Project registration
  - Enhancement signal collection
  - Port: 18792

- **Frontend** (`frontend/`): React 19 + Vite
  - Sprint Manager dashboard
  - Kanban board for tasks
  - Project management UI
  - Port: 5173

### Data Storage
- JSON files in `workspace/sprints/`
  - `tasks.json` - All tasks
  - `sprints.json` - Sprint definitions
  - `projects.json` - Registered code projects
  - `config.json` - Sprint settings

## Key Patterns

### Backend
- Services use `@lru_cache()` for singleton instances
- JSON storage with camelCase field names
- Pydantic models with snake_case
- structlog for logging

### Frontend
- React Query for data fetching
- Zustand for state management
- Tailwind CSS for styling
- Lucide for icons

## QMD Documentation Search
- Indexed: 511 .md files in project (skills, docs, backend, .claude)
- Use `qmd_search`, `qmd_vsearch`, `qmd_query` MCP tools before Glob/Grep
- 6 context descriptions configured for path relevance
- Collection name: `zero`

## Quick Reference

### Start Services
```bash
# Full stack
docker-compose -f docker-compose.sprint.yml up

# Just API
cd backend && uvicorn app.main:app --host 0.0.0.0 --port 18792

# Just frontend
cd frontend && npm run dev
```

### Key Files
- Config: `config/zero.json`
- Auth: `workspace/agents/main/agent/auth-profiles.json`
- Environment: `.env`

### API Base URL
http://localhost:18792/api

## Registered Projects
(Use `GET /api/projects` to list)
