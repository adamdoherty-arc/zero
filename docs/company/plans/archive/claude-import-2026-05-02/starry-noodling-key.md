# Integrate code-review-graph into FortressOS

## Context

FortressOS is a 63K+ LOC monorepo (Python + React) with 35 API routers, 31 services, 30 models, 15 scrapers, and 13 worker task modules — all heavily interconnected. Today, every Claude Code session re-discovers the codebase from scratch, burning tokens scanning files that aren't relevant to the task at hand. **code-review-graph** (8.9k stars, MIT) builds a persistent structural graph of the codebase so Claude reads only what matters.

---

## How FortressOS Benefits

### 1. Blast-Radius Analysis (highest value)
FortressOS has deep dependency chains: `Model -> Service -> API Router -> Worker Task -> Frontend Hook -> Page`. Changing a model like `Job` today requires manually tracing impacts across ~15 files. The graph traces this automatically.

**Concrete example:** Adding a column to `Job` model → graph identifies: `job.py` (model), `jobs.py` (API), `matches.py` (API), `matching_service.py`, `deep_evaluation_service.py`, `archetype_service.py`, `scrape_tasks.py`, `matching_tasks.py`, `useJobs.js`, `useMatches.js`, `Jobs.jsx`, `Matches.jsx`, `JobDetailModal.jsx`, plus 4 test files. Today Claude guesses; with the graph, it knows.

### 2. Token Efficiency (~8x reduction)
FastAPI projects see 8.1x token reduction in benchmarks. FortressOS's 212 Python files + 57 frontend files means Claude currently wastes significant context on irrelevant code. The graph delivers only the impacted subset.

### 3. Risk-Scored PR Reviews
The `detect_changes_tool` scores changes by how many dependents they touch. High-risk changes (deps.py, llm_router.py, base models) get flagged automatically. Low-risk changes (single scraper tweak) skip deep review.

### 4. Architecture Visualization
Community detection would automatically identify FortressOS's natural subsystems:
- **Job Pipeline**: scrapers -> models -> dedup -> matching
- **AI Layer**: llm_service -> ollama -> kimi -> claude_service
- **Career Ops**: deep_evaluation -> negotiation -> story_bank -> compensation
- **Sprint Management**: sprints -> features -> tasks -> health
- **User Profile**: profile -> resume -> personas -> skills

### 5. Test Gap Detection
The graph maps which functions have tests and which don't. With 31 test files covering 35 routers, gaps are likely in the services layer (only 4 service test files exist).

### 6. Incremental Updates (<2s)
FortressOS changes frequently (sprint branches). The graph re-indexes only changed files via SHA-256 diffing, keeping the map current without manual intervention.

---

## Integration Plan

### Step 1: Install code-review-graph
```bash
pip install code-review-graph[all]
```
The `[all]` extra includes embeddings, community detection, and wiki generation — all useful for FortressOS's complexity.

### Step 2: Configure for Claude Code
```bash
code-review-graph install --platform claude-code
```
This auto-generates the MCP config so Claude Code gains access to all 22 graph tools.

### Step 3: Build the Initial Graph
```bash
cd c:/code/fortressOS
code-review-graph build
```
First build parses all 269 source files (Python + JS/JSX) via tree-sitter into a local SQLite graph. Expected time: <30 seconds for a project this size.

### Step 4: Add `.code-review-graphignore`
Create exclusion file at repo root:
```
node_modules/**
*.min.js
backend/__pycache__/**
frontend/dist/**
documents/**
*.generated.*
```

### Step 5: Enable Auto-Update Hooks
```bash
code-review-graph watch
```
Or install git hooks so the graph updates on every commit automatically.

### Step 6: Verify Integration
Ask Claude Code: "What's the blast radius of changing the Job model?" — it should return the precise set of affected files without scanning the whole repo.

---

## Files to Create/Modify

| File | Action | Purpose |
|------|--------|---------|
| `.code-review-graphignore` | Create | Exclude node_modules, dist, __pycache__ |
| `.mcp.json` (auto-generated) | Auto | MCP server config for Claude Code |

No changes to FortressOS source code are required. This is purely a developer tooling integration.

---

## Verification

1. Run `code-review-graph status` — confirm all 269 source files indexed
2. Run `code-review-graph detect-changes` on current branch — should show risk-scored impact of all uncommitted changes
3. Ask Claude Code to use `get_review_context_tool` on a recent diff — verify it returns targeted context, not the whole repo
4. Run `code-review-graph visualize` — open the HTML graph to inspect dependency clusters
