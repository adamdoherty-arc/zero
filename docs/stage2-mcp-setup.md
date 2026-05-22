# Stage-2 MCP Setup: cyanheads-obsidian

Stage-2 vault writes (outside `_agent/`) route through the `cyanheads-obsidian`
MCP server. This server talks to the **Obsidian Local REST API** community
plugin running on your local machine.

## Status check

```bash
curl http://localhost:18792/api/zero/stage2/readiness
```

Returns `"ready": true` when all three prerequisites are met.

## Prerequisites

### 1. Install the Obsidian Local REST API plugin

1. Open Obsidian.
2. Go to **Settings → Community plugins → Browse**.
3. Search for **Local REST API** (author: coddingtonbear).
4. Install and enable it.
5. In its settings, copy the **API key** it generates.

The plugin listens on `https://127.0.0.1:27124` with a self-signed TLS cert.

### 2. Set OBSIDIAN_API_KEY in your environment

Add to `c:\code\zero\.env`:

```
OBSIDIAN_API_KEY=<paste key from plugin settings>
OBSIDIAN_BASE_URL=https://127.0.0.1:27124
```

Then restart zero-api:

```powershell
docker compose -f docker-compose.sprint.yml up -d zero-api
```

### 3. Wire cyanheads-obsidian in .mcp.json

Verify `.mcp.json` at the project root contains:

```json
{
  "mcpServers": {
    "cyanheads-obsidian": {
      "command": "npx",
      "args": ["-y", "@cyanheads/obsidian-mcp-server"],
      "env": {
        "OBSIDIAN_API_KEY": "${OBSIDIAN_API_KEY}",
        "OBSIDIAN_BASE_URL": "${OBSIDIAN_BASE_URL}"
      }
    }
  }
}
```

Then restart Claude Code (the MCP server starts on session launch).

## Vault constitution reminder

All vault writes must:
- Check `agent_writable` frontmatter first
- Use append-only heading markers
- Carry audit footer `<!-- agent-run-id: ... source: zero at: ... -->`
- Never touch `.obsidian/`, `.git/`, `.trash/`
- Use `partition: personal | trading | zero-dev` (never `work`)

See `C:\code\vault\ObsidianZero\00_Meta\CLAUDE.md` for the full constitution.
