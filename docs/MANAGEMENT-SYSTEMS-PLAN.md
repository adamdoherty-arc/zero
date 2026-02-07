# Moltbot Management Systems Implementation Plan

## Overview

Bring three integrated management systems from ADA into moltbot as fresh Node.js/TypeScript implementations:

1. **Orchestration System** - YAML-based workflow engine with DAG execution
2. **Enhancement System** - Self-improvement with AI-powered analysis and auto-fixes
3. **Sprint Management** - Project/task management via chat commands

All systems use moltbot's existing architecture: JSON file persistence, Ollama LLMs, and chat channel integration (WhatsApp/Slack/Discord).

---

## Architecture Summary

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Moltbot Gateway (existing)                        │
│                     Port 18789 WebSocket                             │
└─────────────────────────────┬───────────────────────────────────────┘
                              │
┌─────────────────────────────▼───────────────────────────────────────┐
│                      New Management Layer                            │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────┐ │
│  │  Orchestration  │  │   Enhancement   │  │  Sprint Manager     │ │
│  │     Engine      │◄─┤     System      │◄─┤     System          │ │
│  └────────┬────────┘  └────────┬────────┘  └─────────┬───────────┘ │
│           │                    │                      │             │
│  ┌────────▼────────────────────▼──────────────────────▼───────────┐│
│  │                    Shared Services                              ││
│  │  • JSON Persistence (workspace/)                                ││
│  │  • Ollama LLM Client (qwen3-coder:30b)                         ││
│  │  • Chat Channel Router (WhatsApp/Slack/Discord)                ││
│  └─────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────┘
```

---

## File Structure

```
moltbot/
├── workspace/
│   ├── orchestration/              # Orchestration state
│   │   ├── workflows/              # YAML workflow definitions
│   │   │   ├── examples/           # Bundled workflows
│   │   │   └── custom/             # User-defined
│   │   ├── state/
│   │   │   ├── executions/         # Active executions
│   │   │   └── history/            # Completed logs
│   │   └── config.json
│   │
│   ├── enhancement/                # Self-improvement state
│   │   ├── signals/                # Raw signals archive
│   │   ├── opportunities/          # Enhancement backlog
│   │   ├── reviews/                # Daily reviews
│   │   ├── fixes/                  # Fix history
│   │   └── config.json
│   │
│   └── sprints/                    # Sprint management state
│       ├── sprints.json            # Sprint definitions
│       ├── tasks.json              # All tasks
│       ├── projects.json           # Project tracking
│       ├── metrics/                # Velocity, burndown
│       └── config.json
│
├── skills/                         # Custom skills (mounted to /app/skills-custom)
│   ├── sprint-manager/SKILL.md
│   ├── enhancement/SKILL.md
│   └── orchestration/SKILL.md
│
└── config/
    └── moltbot.json                # Management system configs added
```

---

## System 1: Orchestration Engine

### Purpose
Execute complex multi-step workflows with parallel processing, LLM decision-making, and crash recovery.

### Key Features
- **YAML workflow definitions** with DAG-based step execution
- **Chat triggers** - Start workflows via `/workflow run <name>`
- **Skill integration** - Execute existing moltbot skills as steps
- **LLM steps** - Use Ollama for AI-powered decisions
- **Parallel execution** - Independent steps run concurrently
- **State persistence** - Resume interrupted workflows

### Core Components
| Component | Purpose |
|-----------|---------|
| WorkflowParser | Load and validate YAML definitions |
| DAGExecutor | Topological sort and parallel execution |
| StateManager | JSON persistence for crash recovery |
| TriggerRouter | Chat/cron/event triggers |
| StepHandlers | skill, llm, http, notify, condition |

### Example Workflow
```yaml
name: daily-briefing
triggers:
  - type: cron
    cron: "0 7 * * *"
steps:
  - id: weather
    type: skill
    config: { skill: weather, action: forecast }
  - id: compose
    type: llm
    depends_on: [weather]
    config:
      prompt: "Create morning briefing with: {{ steps.weather.output }}"
  - id: send
    type: notify
    depends_on: [compose]
    config: { channel: whatsapp, to: self }
```

### Chat Commands
- `/workflow list` - List available workflows
- `/workflow run <name> [params]` - Execute workflow
- `/workflow status <id>` - Check execution status
- `/workflow cancel <id>` - Cancel execution

---

## System 2: Enhancement/Self-Improvement

### Purpose
Automatically analyze moltbot's health, detect issues, and apply fixes with human-in-the-loop approval.

### Key Features
- **Signal collection** - Docker logs, errors, performance metrics
- **AI prioritization** - LLM scores issues 0-100
- **Auto-fix** - Apply safe fixes automatically (confidence >90%)
- **Approval workflow** - Send to chat for human approval
- **Daily reviews** - AI-generated health reports

### Processing Flow
```
Signal Collection (fan-out)     →  Aggregation (fan-in)
  • Docker logs                     • Deduplicate
  • Error tracking                  • Categorize
  • Performance metrics             • Map to components
  • Health checks
                                         ↓
                               AI Prioritization (Ollama)
                                   • Score 0-100
                                   • Chain-of-thought reasoning
                                         ↓
                               Routing by Confidence
                               ┌─────────┼─────────┐
                          Auto-Fix   Approval    Batch
                          (>90%)    (70-90%)    (<70%)
```

### Chat Commands
- `/enhance status` - Show enhancement system status
- `/enhance health` - Display system health score
- `/enhance review` - Generate daily review
- `/enhance approve <id>` - Approve enhancement
- `/enhance reject <id> [reason]` - Reject enhancement

---

## System 3: Sprint/Project Management

### Purpose
Personal project management via natural language chat commands.

### Key Features
- **Sprint lifecycle** - planning → active → completed
- **Task workflow** - backlog → todo → in_progress → review → done
- **Natural language** - "add task: fix login bug"
- **AI estimation** - LLM estimates story points
- **Metrics** - Velocity, burndown charts
- **Enhancement integration** - Auto-create tasks from detected issues

### Natural Language Commands
| Say This | Does This |
|----------|-----------|
| "start a new sprint" | Create and activate sprint |
| "add task: implement OAuth" | Create task in current sprint |
| "show my tasks" | List current sprint tasks |
| "move task 3 to done" | Update task status |
| "what should I work on?" | AI task recommendation |
| "show burndown" | Sprint progress chart |
| "estimate: add dark mode" | AI complexity estimation |

---

## ADA Framework Analysis

### Frameworks Used by ADA

| Framework | Version | Purpose |
|-----------|---------|---------|
| **LangChain** | >=0.3.25 | LLM orchestration core |
| **LangGraph** | >=0.4.10 | State-managed workflows, DAG execution |
| **langgraph-swarm** | >=0.0.15 | Multi-agent domain swarms |
| **langgraph-checkpoint-postgres** | >=3.0.0 | Workflow state persistence |
| **Redis Streams** | - | Event bus for agent communication |

### Decision: Custom vs Framework

**For moltbot, we chose CUSTOM implementation** because:

1. **Simpler use case** - Personal assistant vs trading platform
2. **No Python dependency** - Moltbot is Node.js/Docker-based
3. **Sufficient patterns** - YAML workflows + skills cover our needs
4. **Lower complexity** - JSON persistence vs PostgreSQL

### What CAN Be Built Without Frameworks

| Pattern | Custom Approach (what we built) |
|---------|--------------------------------|
| Workflow execution | YAML workflow engine with DAG |
| Agent coordination | Skills + JSON state |
| LLM calls | Direct Ollama API calls |
| State management | JSON file persistence |
| Tool integration | Skill-based tool registry |

### Node.js Equivalents (if needed later)

| ADA Component | Node.js Equivalent |
|---------------|-------------------|
| LangGraph | @langchain/langgraph or custom StateGraph |
| Redis Streams | ioredis with XADD/XREAD |
| FastAPI | Express/Fastify/NestJS |
| asyncpg | pg/knex/prisma |
| Pydantic | Zod/class-validator |

---

## Implementation Status

### Completed (Foundation)

- [x] Workspace directory structure
- [x] Config files for all systems
- [x] Initial data store JSON files
- [x] Skill definitions (SKILL.md)
- [x] Example workflows (daily-briefing, research-task)
- [x] docker-compose.yml updated with skills mount
- [x] moltbot.json updated with management config

### Pending

- [ ] Test skill loading in moltbot
- [ ] Create additional example workflows
- [ ] Add Redis event bus (optional)
- [ ] Implement checkpoint persistence for long workflows

---

## Quick Start

1. **Restart moltbot** to load new configuration:
   ```bash
   docker-compose down && docker-compose up -d
   ```

2. **Test via chat**:
   - `start sprint My Project` - Create a sprint
   - `add task: setup authentication` - Add a task
   - `/workflow list` - List available workflows
   - `/enhance health` - Check system health

3. **Create custom workflows** in `workspace/orchestration/workflows/custom/`

---

## Reference Files (ADA)

- `C:\code\ADA\backend\infrastructure\workflow_engine.py` - Orchestration patterns
- `C:\code\ADA\src\ada\langgraph\graphs\enhancement_manager.py` - Enhancement flow
- `C:\code\ADA\backend\services\sprint_management_service.py` - Sprint service
- `C:\code\ADA\database\schemas\sprint_management_schema.sql` - Data models
