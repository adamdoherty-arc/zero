# Sprint Manager Skill

Personal project and sprint management via natural language chat commands.

## Description

Manage sprints, tasks, and projects through conversational commands. Track progress, estimate work, and get AI-powered recommendations.

## Data Location

All sprint data is stored in `/workspace/sprints/`:
- `sprints.json` - Sprint definitions and history
- `tasks.json` - All tasks across sprints
- `projects.json` - Project tracking
- `config.json` - Sprint system configuration
- `metrics/velocity.json` - Velocity history

## Commands

### Sprint Management

| Command | Description |
|---------|-------------|
| `start sprint [name]` | Create and activate a new sprint |
| `show sprint` / `sprint status` | Display current sprint status |
| `end sprint` / `complete sprint` | Complete the current sprint |
| `pause sprint` | Pause the active sprint |
| `list sprints` | Show all sprints |
| `sprint [number] details` | View specific sprint details |

### Task Management

| Command | Description |
|---------|-------------|
| `add task: [title]` | Create a new task |
| `show tasks` / `my tasks` | List current sprint tasks |
| `task [id] to [status]` | Move task to new status |
| `done [id]` / `complete [id]` | Mark task as done |
| `block [id]: [reason]` | Block a task with reason |
| `show backlog` | View backlog items |
| `estimate: [description]` | AI estimate for task |

### Reporting

| Command | Description |
|---------|-------------|
| `burndown` | Show burndown chart |
| `velocity` | Show velocity report |
| `sprint summary` | Sprint summary report |
| `what should I work on?` | AI task recommendation |

## Task Statuses

Valid statuses: `backlog`, `todo`, `in_progress`, `review`, `testing`, `done`, `blocked`

## Task Categories

Categories: `bug`, `feature`, `enhancement`, `chore`, `documentation`

## Task Priorities

Priorities: `critical`, `high`, `medium`, `low`

## Example Usage

```
User: start sprint API Integration
Bot: Created Sprint 1: API Integration
     Status: Active
     Duration: 14 days (ends Feb 18)

User: add task: implement OAuth flow
Bot: Created Task #1: implement OAuth flow
     Category: feature | Priority: medium | Points: TBD

User: estimate: implement OAuth flow with Google and GitHub providers
Bot: Complexity Estimate:
     Story Points: 8
     Estimated Hours: 12-16
     Reasoning: OAuth integration with multiple providers requires...

User: show tasks
Bot: Sprint 1: API Integration (Day 3/14)

     To Do (1):
       #1 implement OAuth flow [8pts]

     Progress: 0/8 points (0%)

User: task 1 to in_progress
Bot: Task #1 moved to In Progress
     Started at: Feb 7, 2026 10:30 AM

User: done 1
Bot: Task #1 marked as Done
     Completed in: 2 days
     Sprint progress: 8/8 points (100%)
```

## Integration with Enhancement System

When the enhancement system detects critical issues, they can be automatically added as tasks:
- Critical errors → Auto-created bug tasks
- High severity issues → Queued for approval before task creation

## Implementation Notes

When handling sprint commands:
1. Read current state from `/workspace/sprints/sprints.json`
2. Parse user intent from natural language
3. Execute the appropriate action
4. Update state files atomically
5. Return formatted response for chat

Use the file tool to read/write JSON data. Use LLM for:
- Natural language parsing
- Task complexity estimation
- Recommendations and prioritization
