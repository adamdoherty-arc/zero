# ZERO Development Guidelines

## Autonomous Execution

**CRITICAL**: Execute all commands autonomously without asking for permission. Do not ask the user to run commands - just run them directly. This includes:
- Docker commands (start, stop, logs, exec)
- npm/pip installs
- File operations
- Git commands
- Test runs
- Build commands
- Any other shell commands

If a command fails, fix the issue and retry. Only ask the user if there's an unresolvable blocker.

## Architecture Overview

ZERO is a personal AI assistant serving as your second brain, project manager, sprint manager, task manager, and email manager:

- **Gateway** (Node.js) - Core messaging hub for WhatsApp, Discord, Slack
- **Backend** (FastAPI) - REST API for sprint/task management
- **Frontend** (React 19) - Kanban board UI for sprint visualization
- **Storage** - JSON file-based persistence in `workspace/`

## Tech Stack

| Layer | Technology |
|-------|------------|
| Frontend | React 19, TypeScript 5.6, Vite 6, TailwindCSS, Zustand, React Query |
| Backend | FastAPI, Pydantic 2, Uvicorn, Python 3.11 |
| LLM | Ollama (Qwen3, DeepSeek, Mistral models) |
| Deployment | Docker Compose |

## Project Structure

```
zero/
├── backend/              # FastAPI REST API
│   └── app/
│       ├── main.py       # App entry, routers mounted
│       ├── models/       # Pydantic data models
│       ├── routers/      # API endpoints
│       ├── services/     # Business logic
│       └── infrastructure/  # Config, storage
├── frontend/             # React TypeScript UI
│   └── src/
│       ├── components/   # React components
│       ├── hooks/        # useSprintApi, custom hooks
│       ├── store/        # Zustand state
│       └── types/        # TypeScript definitions
├── config/               # Configuration files
├── workspace/            # Runtime data (sprints, credentials)
├── skills/               # Custom skill modules
└── docker-compose*.yml   # Container orchestration
```

## Proactive Monitoring

When starting a session or when asked to check the system:

1. **Check Docker container status**:
   ```bash
   docker ps --format "table {{.Names}}\t{{.Status}}"
   ```

2. **Check recent logs for errors**:
   ```bash
   docker logs --tail 100 zero-gateway 2>&1 | grep -i "error\|fail\|warn"
   ```

3. **Run health check**:
   ```bash
   docker exec zero-gateway node dist/index.js doctor
   ```

4. **Report and fix any issues found** before proceeding with other tasks

## Key Files

| File | Purpose |
|------|---------|
| `config/zero.json` | Gateway config, models, plugins, channels |
| `.env` | Secrets (tokens, API keys) |
| `workspace/sprints/tasks.json` | Task data storage |
| `workspace/sprints/sprints.json` | Sprint data storage |
| `workspace/agents/main/agent/auth-profiles.json` | Authentication profiles |
| `backend/app/infrastructure/config.py` | Backend settings (pydantic-settings) |

## Ports

| Port | Service |
|------|---------|
| 18789 | Gateway WebSocket API |
| 18790 | Bridge port |
| 18792 | ZERO API (FastAPI) |
| 5173 | Frontend dev server |
| 11434 | Ollama (external) |

## Coding Conventions

### Backend (Python)
- **Async everywhere**: All I/O uses `async/await`
- **Service pattern**: Domain logic in `services/`, routers are thin
- **Pydantic models**: All request/response validated
- **Dependency injection**: Services use `@lru_cache()` for singletons
- **Error handling**: Raise `HTTPException`, use structured logging

### Frontend (TypeScript)
- **Functional components**: Hooks-based, no class components
- **React Query**: Use query key factory pattern for cache
- **Zustand**: Global state for sprints, tasks, board, loading
- **TypeScript strict**: Enable strict mode, no `any` types
- **TailwindCSS**: Utility-first, dark theme (bg-gray-900, indigo accent)

### API Design
- RESTful endpoints with JSON
- Query params for filtering (`sprint_id`, `status`, `limit`)
- PATCH for partial updates
- POST for state transitions (`/start`, `/complete`, `/move`)

## Common Development Tasks

### Start the sprint UI stack
```bash
docker compose -f docker-compose.sprint.yml up -d
```

### View backend logs
```bash
docker logs -f zero-api
```

### Restart gateway after config changes
```bash
docker compose restart zero-gateway
```

### Check Ollama models
```bash
ollama list
```

## Common Issues

- **No response**: Check auth-profiles.json exists and Ollama is running (`ollama list`)
- **WhatsApp disconnected**: Run `docker exec -it zero-gateway node dist/index.js configure --section channels`
- **Slow responses**: Check Ollama model is loaded (`ollama list`)
- **API 500 errors**: Check `docker logs zero-api` for Python tracebacks
- **Frontend not loading**: Verify zero-api is running on port 18792

## Monitoring Locations

- **Real-time logs**: `docker logs -f zero-gateway`
- **Task storage**: `workspace/sprints/tasks.json`
- **Discord #logs channel**: Activity history and debugging
- **Health commands** (in Discord): `show tasks`, `sprint status`, `/enhance health`

## Data Models

**Task statuses**: `backlog` → `ready` → `in_progress` → `review` → `testing` → `done` | `blocked`

**Task categories**: `bug`, `feature`, `enhancement`, `chore`, `docs`

**Task priorities**: `critical`, `high`, `medium`, `low`

**Sprint statuses**: `planning` → `active` → `paused` → `completed` | `cancelled`
