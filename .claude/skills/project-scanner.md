# Project Scanner Skill

## Purpose
Scan registered code projects for enhancement signals (TODO, FIXME, errors, etc.) and create tasks from findings.

## Trigger
- "scan project <name>"
- "check code quality"
- "find todos in <project>"
- "analyze project <name>"

## Process
1. Get project from API: `GET /api/projects/{id}`
2. Trigger scan: `POST /api/projects/{id}/scan`
3. Review scan results for signal counts
4. Optionally create tasks from high-priority signals via `POST /api/tasks`

## API Integration
Base URL: http://localhost:18792/api

### Endpoints Used
- `GET /api/projects` - List all registered projects
- `GET /api/projects/{id}` - Get project details
- `POST /api/projects/{id}/scan` - Trigger a scan
- `GET /api/projects/{id}/context` - Get CLAUDE.md, README, structure
- `POST /api/tasks` - Create task from signal

## Signal Types
- **TODO** - Items marked for future implementation
- **FIXME** - Known bugs or issues to fix
- **HACK** - Temporary workarounds
- **BUG** - Identified bugs

## Example Usage
```
# Scan a project
curl -X POST http://localhost:18792/api/projects/proj-1/scan

# Create task from finding
curl -X POST http://localhost:18792/api/tasks \
  -H "Content-Type: application/json" \
  -d '{"title": "Fix FIXME in auth.py:42", "project_id": "proj-1", "category": "bug"}'
```
