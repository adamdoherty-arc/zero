# Zero - Personal And Company AI Operating System

Zero is Adam's personal AI assistant and the active software home for
**ADA AI LLC Company OS**. The Company OS docs, task cockpit, approval
gates, agent structure, finance/legal readiness, consulting pipeline, product
studio, and robotics lab context now live here.

- Company UI: `/company`
- Company docs UI: `/company/docs`
- Company docs on disk: `C:\code\zero\docs\company`
- Legacy company archive: `C:\code\company`

Multi-channel assistant capabilities still run on the existing Zero stack.

## Quick Start

1. Set required API keys in `.env`.
2. Start the sprint stack:

```powershell
cd C:\code\zero
docker compose -f docker-compose.sprint.yml up -d
```

3. Open the UI:

```text
http://localhost:5173
http://localhost:5173/company
```

## Company OS

Zero is the canonical company operating system:

- tasks and approvals live in Zero;
- docs live in `docs/company`;
- Obsidian mirrors narrative weekly reviews and decisions;
- Notion is deferred until external collaboration requires it;
- purchases, legal filings, tax elections, client/public communications,
  account changes, and financial actions require approval gates.

## Ports

- `18792`: Zero FastAPI backend
- `5173`: Zero UI
- `18796`: host agent
- `8000`: Reachy Mini daemon
- `4444`: shared LiteLLM gateway

## File Structure

```text
zero/
|-- docs/company/       # Company OS operating manual and sourced context
|-- frontend/           # React/Vite UI, including /company routes
|-- backend/            # FastAPI API, including /api/company context endpoints
|-- workspace/          # Runtime workspace and generated state
|-- config/             # Local configuration
|-- .agents/skills/     # Project-local skills
`-- docker-compose.sprint.yml
```

## Legacy Note

`C:\code\company` is retained as a migration/archive folder only. New Company
OS work starts in `C:\code\zero`.
