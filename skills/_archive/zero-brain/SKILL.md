---
name: zero-brain
description: Route user messages to the Zero backend LangGraph orchestration API for intelligent, data-aware responses. Use this skill for ANY question about tasks, sprints, projects, emails, calendar, research, briefings, money ideas, Notion pages, knowledge/notes, workflows, or system status. This is the primary skill - always try it first before answering directly.
metadata: {"openclaw":{"emoji":"🧠","category":"core","priority":100}}
---

# Zero Brain - Backend Orchestration Router

Routes all domain-specific user messages through the Zero backend API for intelligent responses backed by real data (PostgreSQL, Google Calendar, Gmail, Legion, Notion, etc).

## When to Use

Use this skill for ANY question about:
- **Sprints/Projects**: "What sprints are active?", "Show sprint progress", "Project health"
- **Tasks** (read + write): "Create task: fix login bug", "Mark task 42 done", "What tasks are blocked?"
- **Email**: "Any urgent emails?", "Show my inbox", "Email digest"
- **Calendar**: "What's on my calendar today?", "Find free slots", "Next meeting?"
- **Knowledge** (read + write): "Remember that I prefer dark mode", "What do you know about me?", "List my notes"
- **Research**: "Latest research findings", "What trends are emerging?"
- **Briefing**: "Give me a summary", "Morning briefing"
- **Notion**: "Search my workspace", "Find that document about..."
- **Money Maker**: "Any new income ideas?", "Side hustle suggestions"
- **Enhancements**: "Scan for code improvements", "What TODOs exist?"
- **Workflows**: "List workflows", "Trigger the backup workflow", "Active executions"
- **System**: "System status", "GPU usage", "Scheduler jobs", "Health check"

## How It Works

```
User Message -> Zero Backend API -> LangGraph Router -> Domain Service -> Synthesized Response
```

The backend uses two-tier routing:
1. **Keyword matching** (fast path) for obvious intents
2. **LLM classification** for ambiguous queries

## Usage

```bash
# Query the backend
python scripts/query.py "What sprints are active?" "whatsapp" "user123"

# With channel context
python scripts/query.py "Show my calendar" "discord" "427818579812155402"
```

## API Endpoint

- **URL**: `http://zero-api:18792/api/orchestrator/graph/invoke`
- **Method**: POST
- **Auth**: Bearer token (ZERO_GATEWAY_TOKEN)
- **Request**: `{"message": "user query", "thread_id": "channel-sender"}`
- **Response**: `{"result": "natural language answer", "route": "sprint|email|...", "thread_id": "..."}`

## Routes (13 total)

**Read-only routes:**
- **sprint** — sprint, project, backlog, progress, velocity (Legion API)
- **email** — email, gmail, inbox, unread, digest (Gmail API)
- **calendar** — calendar, schedule, meeting, event, free (Google Calendar)
- **briefing** — briefing, summary, daily, morning, overview (Multi-source)
- **research** — research, discover, finding, trends (PostgreSQL)
- **notion** — notion, workspace, page, database, wiki (Notion API)
- **money_maker** — money, income, monetize, revenue, idea (PostgreSQL + SearXNG)
- **enhancement** — enhance, scan, todo, fixme, improve (Codebase scanning)
- **system** — system, health, gpu, vram, scheduler, backup (System services)

**Read + write routes:**
- **task** — create task, add task, complete task, mark task done (Legion API)
- **knowledge** — remember, recall, note, save, learn, fact (PostgreSQL)
- **workflow** — workflow, trigger, automate, run workflow (Workflow Engine)

**Fallback:**
- **general** — greetings, meta-questions, anything else (Ollama LLM)
