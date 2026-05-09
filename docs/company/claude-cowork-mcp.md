---
owner: company
status: canonical
source_of_truth: claude-cowork-mcp
last_verified: 2026-05-03
---

> Active Zero context: created in `C:\code\zero\docs\company` on 2026-05-02.
> Zero is the canonical company app/context; Obsidian is the mirror, and
> `C:\code\company` is archive-only.

# Claude Co-Work MCP Connector

Claude Co-Work should use the narrow `zero-company` MCP connector for ADA AI LLC
Company OS. The broad `zero-mcp` connector still exists for developer
work, but `zero-company` is the safer default for day-to-day company task
execution.

## Connector

Local MCP entry in `C:\code\zero\.mcp.json`:

```json
"zero-company": {
  "command": "python",
  "args": ["C:\\code\\zero\\mcp_servers\\zero_company_mcp.py"]
}
```

Server file:

`C:\code\zero\mcp_servers\zero_company_mcp.py`

Default transport is `stdio`, which is right for local Claude Desktop / local
MCP clients. For Claude Co-Work custom connectors that need remote MCP, run the
same server over streamable HTTP and expose it only behind authenticated access:

```powershell
cd C:\code\zero
.\scripts\start-zero-company-mcp.ps1 -Transport streamable-http -HostName 127.0.0.1 -Port 8787
```

Remote connector URL:

```text
https://<your-authenticated-tunnel>/mcp
```

Do not expose this connector directly to the public internet. If using a tunnel,
put it behind Cloudflare Access, Tailscale Funnel ACLs, a private VPN, or an
equivalent identity gate.

## Tools

| Tool | Purpose | Write tier |
|---|---|---|
| `company_operating_context` | Read Zero Company OS context and guardrails | read |
| `company_docs_index` | Read active company docs index | read |
| `company_read_doc` | Read a single doc under `docs/company` | read |
| `company_search_docs` | Search active company docs | read |
| `company_guardrail_check` | Classify whether an action needs approval | read |
| `company_daily_brief` | Summarize context, tasks, approvals, and backlog | read |
| `company_operator_status` | Read Zero Company Operator heartbeat and live state | read |
| `company_operator_today` | Read today's recommended company work | read |
| `company_operator_overnight` | Read the latest overnight report | read |
| `company_operator_runs` | List recent operator runs | read |
| `company_operator_run_tick` | Run one supervised internal operator tick | write_local |
| `company_operator_generate_report` | Generate a morning/evening/weekly/manual report | write_local |
| `company_operator_pause` | Pause scheduled overnight work | write_local |
| `company_operator_resume` | Resume scheduled overnight work | write_local |
| `company_operator_assign_task` | Assign an internal task to a company subagent | write_local |
| `company_operator_queue_approval` | Queue a tiered approval for high-risk company work | write_local |
| `company_list_tasks` | List editable Company Work Items from `/api/company/work-items` | read |
| `company_create_task` | Create internal Company Work Items with server guardrails | write_local |
| `company_update_task` | Update internal Company Work Items with server guardrails | write_local |
| `company_complete_task` | Complete safe tasks through `/complete`; high-risk work returns an approval-gated task | write_local / approval |
| `company_queue_approval` | Create approval record for high-risk work | write_local |
| `company_list_approvals` | Show pending approvals | read |
| `company_seed_backlog_from_docs` | Preview or create tasks from `task-backlog.md` | read by default; write_local when `dry_run=false` |

## Operating Rules

Claude Co-Work may:

- answer "what should I work on today?";
- summarize company status from docs and tasks;
- create internal tasks and organize backlog;
- update safe task status;
- draft reports, checklists, proposals, and CPA/attorney packets;
- queue approvals for risky actions.

Claude Co-Work must not directly execute:

- purchases, subscriptions, or payments;
- LLC filings, tax elections, EIN actions, or legal document execution;
- client emails, proposals, SOWs, or public website changes;
- account, credential, DNS, OAuth, or infrastructure changes;
- trades, transfers, tax filing, or CPA-submitted materials.

Those actions require approval records in `/company/approvals`.

## 2026-05-03 API Note

The company MCP connector now routes task tools through Zero's dedicated
Company Work Items API instead of the generic `/api/tasks` API. This matters:
Claude Co-Work gets the same behavior as `/company/tasks`, including seed
backlog import, risk classification, approval-gated completion, and task audit
events. The broad `zero_api_mcp.py` connector can still access generic tasks
for developer work, but company operations should prefer this connector.

## Ruflo Note

Ruflo is evaluation-only and must not be exposed through Claude Co-Work,
`zero-company`, `zero-mcp`, Legion MCP, Ada MCP, or broad MCP registration until
the sandbox runbook passes and a human approves the adapter. Claude Co-Work may
read `ruflo-incorporation.md` and create internal evaluation tasks, but it must
not run Ruflo commands against real projects.

## Recommended Prompt

Use this as the standing instruction for Claude Co-Work:

```text
You are helping operate ADA AI LLC Company OS through Zero. Use the
zero-company MCP connector first. Read company_operating_context and
company_daily_brief before planning. Use company_operator_status,
company_operator_today, and company_operator_overnight for the live 24/7 view.
Create and update internal tasks freely.
For purchases, filings, tax elections, client/public communications, account
changes, security changes, or financial actions, create an approval instead of
executing. Keep Zero as the task source of truth, Obsidian as narrative memory,
and Notion deferred unless explicitly requested.
```

## Source Notes

- Anthropic describes MCP as an open standard for connecting Claude to tools
  and data sources.
- Anthropic custom connectors for Claude / Claude Co-Work use remote MCP; local
  MCP remains useful for local Claude clients and development.
- The Python MCP SDK supports stdio and streamable HTTP transports, which is why
  this connector can run in both modes.
