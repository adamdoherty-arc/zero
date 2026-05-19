---
name: claude-md-curator
description: Weekly audit of CLAUDE.md and .claude/rules/*.md. Verifies stale references, detects unmentioned architectural changes from recent commits, flags rules that haven't fired in 30+ days, and writes proposals to .claude/MEMORY.md for operator approval. Cross-project consistency check across Legion/ADA/Zero.
schedule: "0 5 * * 0"
owner_project: global
target_projects: [legion, ada, zero]
daily_token_budget: 50000
---

# claude-md-curator

Curate the modular CLAUDE.md system. Keep the always-loaded baseline accurate, fresh, and consistent across sister projects (Legion, ADA, Zero).

## Why this skill exists

Each project's `CLAUDE.md` is the always-loaded baseline. `.claude/rules/*.md` files extend it by topic. Together they're the agent's working memory for every session. They drift fast — the codebase moves daily, sprint waves rename services, environment variables come and go. A stale rule is worse than a missing one because the agent will trust it.

This skill audits and proposes. **It does not auto-apply changes.** The operator approves each proposal from `.claude/MEMORY.md`.

## Inputs

- Current project root (resolve via `$PWD` or `--project=<legion|ada|zero>` flag)
- `CLAUDE.md` at project root
- All `.md` files under `.claude/rules/` (always-loaded) and `.claude/rules/path-scoped/` (lazy)
- `git log --since="7 days ago" --name-only` for recent file activity
- For cross-project consistency: peer projects' `.claude/rules/00-critical.md` (same neighbor directories)

## Audit dimensions

Run these checks in order. Each emits zero or more proposals.

### 1. Stale file references
For every file path mentioned in `CLAUDE.md` and `.claude/rules/*.md`:
- Run `Glob` to verify the file still exists
- If missing → **PROPOSAL: remove or update reference to `<path>` in `<rule-file>:<line>`**

### 2. Stale function / class / endpoint references
For every `backtick`d identifier that looks like a function/class/endpoint:
- Pattern: `[a-z_]+\.[a-z_]+\(` or `class [A-Z][a-zA-Z]+` or `/api/[a-z-]+(/[a-z-]+)*`
- Run `Grep` across the codebase to verify the symbol still exists
- If missing → **PROPOSAL: rename or remove reference to `<symbol>` in `<rule-file>:<line>`**

### 3. Unmentioned architectural changes
- Run `git log --since="7 days ago" --name-only` and collect files touched
- Filter for architectural surfaces:
  - `backend/app/services/`, `backend/app/api/endpoints/`, `frontend/src/pages/`
  - `docker-compose.yml`, `backend/alembic/versions/`, `backend/Dockerfile`
  - New files under `backend/app/services/` (could be new daemon/service worth a rule)
- Group commits by theme (feature name, file family)
- For each theme with ≥3 commits: check if `CLAUDE.md` or any `rules/*.md` mentions the theme
- If unmentioned → **PROPOSAL: add new rule or "Recent shifts" entry for `<theme>` — affected files: `<list>`**

### 4. Stale rules (haven't fired in 30+ days)
For each rule in `.claude/rules/`:
- Identify a unique fingerprint phrase (the rule's title or first imperative sentence)
- Search recent agent transcripts at `~/.claude/projects/<project-hash>/transcripts/*.jsonl` (last 30 days) for the fingerprint
- If 0 hits → **PROPOSAL: candidate for prune — `<rule-file>` hasn't appeared in any recent session**
- Note: transcripts may not exist for short-running projects; in that case skip this check rather than emit false positives

### 5. Cross-project consistency (Legion + ADA + Zero only)
Read `00-critical.md` from each of the three projects.
- Extract the canonical rules: never-defer, browser-verify (where applicable), fix-on-sight
- Compute drift: which universal rules differ in wording or substance?
- If drift > 20% (any rule materially different in one project but not the others) → **PROPOSAL: harmonize `<rule-name>` across projects — current variants:`<diff summary>`**

### 6. Banned-phrase check
Grep every `.claude/rules/*.md` and `CLAUDE.md` for: "TODO", "deferred", "out of scope", "follow-up session", "future session".
- If found in any file other than `00-critical.md` (where they're listed as banned) → **PROPOSAL: remove banned phrase from `<file>:<line>`** (these phrases shouldn't appear in operating rules — they're what we tell the agent NOT to do)

## Output format

Write all proposals as a single dated entry in `<project-root>/.claude/MEMORY.md`. Format:

```markdown
## 2026-MM-DD curator pass

**Summary:** N proposals (M ADD, K REMOVE, L PRUNE, J HARMONIZE)

### Proposals

- **ADD** [P1]: `.claude/rules/<file>` — `<description>`
  - Evidence: <git log line or grep result>
  - Suggested location: `<file>:<line>` or new file

- **REMOVE** [P2]: `.claude/rules/<file>:<line>` — stale reference to `<thing>`
  - Verification: `<glob/grep result showing absence>`

- **PRUNE** [P3]: `.claude/rules/<file>` — hasn't fired in 35 days
  - Last appearance: <date or "no recent record">

- **HARMONIZE** [P1]: 00-critical.md drift between projects
  - Legion: `<wording>` | ADA: `<wording>` | Zero: `<wording>`
  - Recommend: `<canonical wording>`

### Operator next steps
- Review proposals
- Reply with "apply P1,P3,P5" or "apply all" to enact
- Reply with "skip" or specific IDs to dismiss
```

## How operator approves

After this skill writes to MEMORY.md, the operator can:
1. Open a fresh Claude Code session in the project
2. Reference the proposal: "@.claude/MEMORY.md — apply P1, P2, skip P3"
3. The session applies the changes directly (with normal Edit/Write tools)

Or the operator can invoke this skill again with `--apply` and the IDs to merge.

## Cron behavior (when triggered by Legion's Mesh dispatcher)

When dispatched by Legion's per-project general-* dispatcher (Mesh-48), this skill:
1. Resolves target project from `--target-project` flag or `LOOP_OWNER_PROJECT` env
2. Cd's into that project root
3. Runs full audit
4. Writes proposals to `<project>/.claude/MEMORY.md`
5. If proposal count > 5, fires Discord notification via `notification_service.notify(level="info")`
6. Emits one `skill_run_spans` row with audit summary

## What this skill does NOT do

- Does NOT edit `CLAUDE.md` or `rules/*.md` automatically
- Does NOT prune transcripts or run `/compact`
- Does NOT modify the codebase to fix the references it finds stale
- Does NOT replace the rules — it audits them, operator owns the changes

## Reuse

- Mesh-15 skill-curator pattern for stale-rule detection: `~/.claude/skills/skill-curator/`
- Mesh-32 weight learner JSON I/O pattern: `~/.claude/skills/agent-auditor/scripts/learn_weights.py`
- Mesh-39 alignment Gini computation as a model for the cross-project drift metric

## Testing this skill

Before relying on it for weekly runs, validate by:
1. Run on Legion: `/claude-md-curator --project=legion`
2. Verify MEMORY.md contains a sensible proposal block (expect 3-10 proposals first time)
3. Operator reviews + decides which to apply
4. Re-run: subsequent passes should produce fewer proposals (drift shrinks)
