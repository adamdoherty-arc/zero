# Sprint Assistant Skill

## Purpose
Help with sprint planning, task management, and progress tracking for Zero development.

## Trigger
- "create sprint"
- "add task"
- "show sprint status"
- "move task"
- "sprint progress"

## Capabilities
1. **Sprint Management**
   - Create new sprints with goals
   - Start/complete sprints
   - View sprint progress

2. **Task Management**
   - Create tasks (with optional project association)
   - Move tasks through workflow states
   - Update task details
   - Delete tasks

3. **Progress Tracking**
   - View Kanban board
   - Check story points
   - Monitor blocked tasks

## API Integration
Base URL: http://localhost:18792/api

### Sprint Endpoints
- `GET /api/sprints` - List all sprints
- `GET /api/sprints/current` - Get active sprint
- `POST /api/sprints` - Create sprint
- `POST /api/sprints/{id}/start` - Start sprint
- `POST /api/sprints/{id}/complete` - Complete sprint
- `GET /api/sprints/{id}/board` - Get Kanban board

### Task Endpoints
- `GET /api/tasks` - List tasks (filter by sprint_id, project_id, status)
- `GET /api/tasks/backlog` - Get unassigned tasks
- `POST /api/tasks` - Create task
- `PATCH /api/tasks/{id}` - Update task
- `POST /api/tasks/{id}/move` - Move task to new status
- `DELETE /api/tasks/{id}` - Delete task

## Task Workflow States
```
backlog -> todo -> in_progress -> review -> testing -> done
                        |                      |
                        +------ blocked <------+
```

## Example Usage
```bash
# Create a sprint
curl -X POST http://localhost:18792/api/sprints \
  -H "Content-Type: application/json" \
  -d '{"name": "Sprint 1", "goals": ["Fix bugs", "Add features"]}'

# Create a task for a project
curl -X POST http://localhost:18792/api/tasks \
  -H "Content-Type: application/json" \
  -d '{"title": "Implement auth", "project_id": "proj-1", "priority": "high"}'

# Move task to in_progress
curl -X POST http://localhost:18792/api/tasks/task-1/move \
  -H "Content-Type: application/json" \
  -d '{"status": "in_progress"}'
```
