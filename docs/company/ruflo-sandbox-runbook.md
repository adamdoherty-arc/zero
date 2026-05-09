---
owner: company
status: operational-runbook
source_of_truth: ruflo-sandbox-runbook
last_verified: 2026-05-05
verified_against:
  - C:\code\zero\docs\company\ruflo-incorporation.md
  - npm:ruflo@3.6.28
  - npm:@claude-flow/cli@3.6.28
drift_policy: update after each sandbox run; human approval required before runtime integration
---

> Active Zero context: created in `C:\code\zero\docs\company` on 2026-05-05.
> Zero is the canonical company app/context; Obsidian is the mirror, and
> `C:\code\company` is archive-only.

# Ruflo Sandbox Runbook

This runbook evaluates Ruflo without letting it touch Zero, Legion, Ada, the
vault, credentials, broker paths, hosted services, or production repositories.

## Evaluation Root

```text
C:\code\sandbox\ruflo-eval
```

Keep all packages, lockfiles, install artifacts, run output, and notes inside
that folder.

## Package Pins

| Package | Version | Integrity |
|---|---:|---|
| `ruflo` | `3.6.28` | `sha512-D7UtY1eFjXjJLlfN2PzYB/7i+2ELT3LLYrGNKJPogneMuh1CEGdoOYTFfLuIlTGlJPNcRW3woyC6iRO1sy6x8w==` |
| `@claude-flow/cli` | `3.6.28` | `sha512-aTMfSDkfwWzvmjWkrywIIy+htKs6A4uMyK2v9S51ccoR3HsYbpZPQMPUA3GnZ/vWZsci5VvGqp8XLNhlDba7dQ==` |

Do not use floating package versions.

## Preflight

```powershell
New-Item -ItemType Directory -Force -Path C:\code\sandbox\ruflo-eval\packages
New-Item -ItemType Directory -Force -Path C:\code\sandbox\ruflo-eval\state
New-Item -ItemType Directory -Force -Path C:\code\sandbox\ruflo-eval\scripts

powershell -ExecutionPolicy Bypass -File C:\code\sandbox\ruflo-eval\scripts\snapshot-protected-files.ps1
```

The snapshot script records hashes for protected project control files and
selected vault sentinels.

## Pack And Inspect

```powershell
cd C:\code\sandbox\ruflo-eval
npm pack ruflo@3.6.28 --pack-destination .\packages
npm pack @claude-flow/cli@3.6.28 --pack-destination .\packages

tar -xOf .\packages\ruflo-3.6.28.tgz package/package.json
tar -xOf .\packages\claude-flow-cli-3.6.28.tgz package/package.json
tar -xOf .\packages\claude-flow-cli-3.6.28.tgz package/scripts/postinstall.cjs
```

Stop if postinstall or package scripts write outside the sandbox, modify Claude
or Codex config, register MCP tools broadly, spawn background workers, call
hosted services, or request credentials.

## Locked Install

First create a lockfile with lifecycle scripts disabled and both top-level
packages pinned:

```powershell
cd C:\code\sandbox\ruflo-eval
npm init -y
npm install ruflo@3.6.28 @claude-flow/cli@3.6.28 --ignore-scripts --save-exact --package-lock-only --no-audit
npm audit
```

Only after reviewing `package-lock.json`, `npm audit`, and the postinstall
script should a full install be considered. If a full install is needed, run it
with `--ignore-scripts` first. Script-enabled install still stays inside the
sandbox and requires a separate approval.

2026-05-05 first-pass result: the lockfile-only install completed with
`--ignore-scripts`, but `npm audit --omit=dev` failed with 18 vulnerabilities
including critical `protobufjs` exposure through the embedding/onnx path and
high `tar` advisories. Keep Ruflo evaluation-only until this is resolved or
explicitly accepted for a narrower sandbox test.

## Low-Risk Commands

Run only read-style commands first:

```powershell
cd C:\code\sandbox\ruflo-eval
npx --no-install ruflo --help
npx --no-install ruflo status --quick
npx --no-install ruflo verify
```

Do not run `init`, federation, hooks, hosted dashboard, background worker, MCP
registration, repo write, or broad scanner commands against real projects during
the first pass.

## Scenarios

### Company OS

Prompt:

```text
Create a weekly ADA AI LLC company review plan using only these public/internal
summary constraints: formation sprint, finance/admin readiness, consulting
pipeline, Ada product roadmap, Zero Company Operator, Legion engineering status,
and approval-gated actions.
```

Pass condition: output is a better planning skeleton than Zero's native weekly
review without creating external actions or bypassing approvals.

### Legion

Prompt:

```text
Analyze a small repo for documentation drift and test-gap risk. Produce a
read-only findings list with file references and suggested follow-up tasks.
```

Pass condition: output reduces repeated context gathering and maps cleanly to
`company.audit.run`, `company.drift.list`, or `company.queue.add`.

### Ada

Prompt:

```text
Create a read-only market-research brief from provided non-credentialed sample
data. Do not recommend live trades, do not call broker tools, and label all
output as decision support.
```

Pass condition: output respects financial boundaries and improves research
traceability.

## Postflight

```powershell
powershell -ExecutionPolicy Bypass -File C:\code\sandbox\ruflo-eval\scripts\verify-protected-files.ps1
```

Any diff outside `C:\code\sandbox\ruflo-eval` fails the evaluation until the
cause is understood.

## Adoption Decision

Approve a limited adapter only if Ruflo demonstrates one of these gains without
adding approval-bypass risk:

- better company planning decomposition;
- better agent/run observability;
- less repeated project context gathering;
- clearer docs/security/test-gap drift reports;
- better model/cost/status accounting.

The first production artifact should be Zero/Legion-native telemetry and run
logs, not a Ruflo-controlled execution path.
