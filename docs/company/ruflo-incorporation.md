---
owner: company
status: proposed-evaluation
source_of_truth: ruflo-incorporation-evaluation
last_verified: 2026-05-05
verified_against:
  - https://github.com/ruvnet/ruflo
  - https://raw.githubusercontent.com/ruvnet/ruflo/main/README.md
  - https://raw.githubusercontent.com/ruvnet/ruflo/main/docs/STATUS.md
  - https://raw.githubusercontent.com/ruvnet/ruflo/main/docs/USERGUIDE.md
  - https://raw.githubusercontent.com/ruvnet/ruflo/main/SECURITY.md
  - npm:ruflo@3.6.28
  - npm:@claude-flow/cli@3.6.28
drift_policy: human approves any runtime integration; Legion may refresh research notes only
---

> Active Zero context: created in `C:\code\zero\docs\company` on 2026-05-05.
> Zero is the canonical company app/context; Obsidian is the mirror, and
> `C:\code\company` is archive-only.

# Ruflo Incorporation

Ruflo is a useful pattern source and evaluation candidate for ADA AI LLC
Company OS, but it is not the company orchestrator. Zero remains the CEO /
Chief-of-Staff and operating source of truth. Legion remains the engineering
execution and model-ops system. Ada remains financial decision support behind
the financial approval tier.

## Decision

Adopt Ruflo as a sandboxed evaluation track:

- use Ruflo to study goal decomposition, memory, run logs, agent dashboards,
  worker coordination, and Codex/Claude coordination patterns;
- keep Ruflo out of production task, vault, broker, MCP, and project mutation
  paths until it passes supply-chain and behavior review;
- implement any durable value as Zero, Legion, or Ada-native capability instead
  of making Ruflo the new source of truth;
- expose any future runtime adapter behind `ZERO_COMPANY_RUFLO_ENABLED=false`.

## Fit By System

| System | Useful Ruflo pattern | Boundary |
|---|---|---|
| Zero / Company OS | GOAP-style task planning, run memory, agent dashboarding, cost/status traces | Zero database and Company Work Items stay canonical |
| Legion | Orchestrator-tracks/executor-does workflow, docs/security/test-gap reviews, background observability | Legion executes through its own queues, audits, and MCP tools |
| Ada | Research debate, market-data RAG experiments, paper-trading summaries | No live trading, broker action, or financial recommendation bypass |
| Shared infra | Cost, model, and worker telemetry patterns | LiteLLM, Postgres, approvals, and MCP configs remain current truth |

## Company OS Pattern

Ruflo-like coordination should become a Zero-native run log rather than an
external authority. Each company subagent run should record:

- agent name and role;
- trigger and source documents;
- input scope and output summary;
- tasks created or updated;
- approvals requested;
- cost, runtime, and model/provider route when available;
- blocked actions and the reason they were blocked;
- next recommended task.

This complements the existing Company Operator cadence and the Company Work
Items API. Ruflo memory, if piloted, is pattern memory only. It must not become
the canonical task database or decision ledger.

## Legion Pattern

Legion should borrow the coordination contract: the orchestrator records the
plan, memory, and status; the execution system performs the work through known
interfaces. If Ruflo's patterns prove useful, Legion should surface them through
Company OS contracts such as:

- `company.audit.run(read_only: bool)`;
- `company.drift.list()`;
- `company.queue.add/fetch/resolve()`;
- `projects.graph.query(project, question)`;
- `llm_ops.models.current()`.

Ruflo plugins or agents may be studied for docs drift, security review, test-gap
detection, dependency/cost reporting, and long-running worker status. Any
production version should be implemented in Legion with normal approval gates.

## Ada Pattern

Ada may use Ruflo patterns only for read-only research, debate orchestration,
paper-trading analysis, and traceable market-data experiments. Do not adopt
`ruflo-neural-trader` or any market plugin for live execution. Any live-order,
fund-transfer, broker, tax, or regulated-finance path remains `financial` tier
and requires explicit human confirmation plus an audit trail.

Public/company Ada positioning stays conservative: decision support until legal
and compliance review clears stronger claims.

## Security Boundary

The only approved evaluation root is:

```text
C:\code\sandbox\ruflo-eval
```

The evaluation must not modify:

- `C:\code\zero\.mcp.json`, `.claude`, `.agents`, `CLAUDE.md`, or `AGENTS.md`;
- `C:\code\Legion\.mcp.json`, `.claude`, `.agents`, `CLAUDE.md`, or `AGENTS.md`;
- `C:\code\ADA\.mcp.json`, `.claude`, `.agents`, `CLAUDE.md`, or `AGENTS.md`;
- `C:\code\vault\ObsidianZero` outside explicitly approved Zero mirror paths;
- broker, credential, bank, Stripe, email, DNS, cloud, or production deploy
  paths.

Hosted Ruflo UIs must not receive private company data, vault notes, trading
data, secrets, or credentials. Federation, hooks, background workers, broad MCP
registration, and repo writes all require explicit human approval after review.

## Supply Chain Notes

Pinned packages observed on 2026-05-05:

| Package | Version | License | Integrity |
|---|---:|---|---|
| `ruflo` | `3.6.28` | MIT | `sha512-D7UtY1eFjXjJLlfN2PzYB/7i+2ELT3LLYrGNKJPogneMuh1CEGdoOYTFfLuIlTGlJPNcRW3woyC6iRO1sy6x8w==` |
| `@claude-flow/cli` | `3.6.28` | MIT | `sha512-aTMfSDkfwWzvmjWkrywIIy+htKs6A4uMyK2v9S51ccoR3HsYbpZPQMPUA3GnZ/vWZsci5VvGqp8XLNhlDba7dQ==` |

`ruflo` depends on `@claude-flow/cli`. The Ruflo package itself did not expose a
postinstall script in the inspected npm metadata, while `@claude-flow/cli`
declared `postinstall: node ./scripts/postinstall.cjs`. Inspect that script
from the packed tarball before any install that runs scripts.

First sandbox results on 2026-05-05:

- package packing and protected-file verification passed;
- `@claude-flow/cli` postinstall searches the install's `node_modules` tree for
  `agentdb` and mutates files inside that dependency tree;
- the `ruflo` tarball includes a bundled `src/ruvocal` tree with `.env`,
  `.claude-flow`, `.swarm`, logs, package locks, and `CLAUDE.md`;
- a lockfile-only install with `--ignore-scripts` completed;
- `npm audit --omit=dev` failed with 18 vulnerabilities: 14 critical, 2 high,
  and 2 moderate.

This is enough to keep Ruflo out of real projects until dependency risk and
command behavior are reviewed in more detail.

## Evaluation Gates

1. Pack and inspect `ruflo@3.6.28` and `@claude-flow/cli@3.6.28` in the sandbox.
2. Snapshot protected files before any install or command execution.
3. Generate a pinned lockfile in `C:\code\sandbox\ruflo-eval` with
   `--ignore-scripts --package-lock-only` before any full install.
4. Run `npm audit` and inspect generated lockfiles.
5. Run only low-risk commands such as help/status/verify from the sandbox.
6. Run three scenarios:
   - Company OS: create a weekly company review plan;
   - Legion: analyze docs drift or test-gap risk on a small repo;
   - Ada: produce a read-only market-research summary with no broker path.
7. Verify protected project files and vault sentinels did not change.
8. Accept only if Ruflo improves planning quality, reduces repeated context
   gathering, or improves observability without weakening approval boundaries.

## Non-Goals

- Do not replace Zero Company Operator.
- Do not move company truth back to `C:\code\company`.
- Do not register Ruflo as a broad MCP server in Zero, Legion, or Ada.
- Do not enable autonomous writes, hooks, hosted UIs, federation, or background
  workers against real project data during evaluation.
- Do not let Ruflo make financial, legal, client, public, credential, or
  procurement actions.
