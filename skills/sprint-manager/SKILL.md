# Sprint Manager Skill

Read-only sprint status and reporting via natural language chat commands. All sprint data is managed in Legion (source of truth).

## Description

Query sprint status, view task progress, and get reports through conversational commands. Sprint and task creation/management is handled directly in Legion — this skill provides a read-only view.

## Data Source

All sprint data comes from **Legion** (Sprint Manager API at `localhost:8005`), accessed via Zero's backend API:
- `GET /api/sprints` — List all sprints
- `GET /api/sprints/current` — Get the active sprint
- `GET /api/sprints/{id}` — Get sprint details
- `GET /api/sprints/{id}/board` — Get Kanban board view
- `GET /api/ecosystem/status` — Cross-project overview

## Commands

### Sprint Status

| Command | Description |
|---------|-------------|
| `show sprint` / `sprint status` | Display current sprint status |
| `list sprints` | Show all sprints across projects |
| `sprint [number] details` | View specific sprint details |
| `show board` | Show Kanban board for active sprint |

### Reporting

| Command | Description |
|---------|-------------|
| `what was completed today?` | Recent accomplishments |
| `sprint summary` | Sprint progress summary |
| `project health` | Cross-project health overview |
| `what's blocked?` | Show blocked tasks |

### Task Queries

| Command | Description |
|---------|-------------|
| `show tasks` / `my tasks` | List current sprint tasks |
| `show backlog` | View backlog items |
| `what should I work on?` | AI task recommendation |

## Task Statuses

Valid statuses: `backlog`, `todo`, `in_progress`, `review`, `testing`, `done`, `blocked`

## Implementation Notes

When handling sprint commands:
1. Query Legion via Zero's `/api/sprints` or `/api/ecosystem` endpoints
2. Format response for chat display
3. For task creation/updates, direct the user to Legion
