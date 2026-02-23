# Claude Code Context Optimization Guide

> How to eliminate Claude's 3-5 minute "cold start" exploration on every new conversation.
> Applicable to any project using Claude Code.

---

## The Problem

Every new Claude Code conversation, Claude has to explore your codebase from scratch before it can plan or execute. You see messages like "Now I have a thorough understanding..." after a long wait. This happens because Claude knows your project's **rules** but not **where things are**.

## Root Cause

Claude Code auto-loads two files into every conversation's system prompt:

1. **`CLAUDE.md`** (project root) - Project instructions, coding rules
2. **`MEMORY.md`** (at `~/.claude/projects/<project>/memory/MEMORY.md`) - Persistent memory across conversations

If these files contain history, completed tasks, or verbose architecture descriptions instead of **navigational indexes**, Claude has to glob and grep to find anything.

## The Fix: 3-Layer Context Architecture

### Layer 1: MEMORY.md (Auto-loaded, 200 line limit)

This is your **navigation map**. Every line must help Claude find files or avoid errors. No history, no completed items.

**Structure:**
```markdown
# Project Name - Navigation Map

## Quick Reference
- Stack, ports, config file locations, key numbers (X routers, Y pages, etc.)

## Backend Module Map
| Domain | Router/Controller | Service | API Prefix |
|--------|------------------|---------|------------|
| Auth   | auth.py          | auth_service.py | /api/auth |
| Users  | users.py         | user_service.py | /api/users |
...

## Frontend Page Map
| Page | Route | Primary API |
|------|-------|-------------|
| Dashboard | / | /api/dashboard |
| Settings  | /settings | /api/settings |
...

## Key File Map (for non-web projects)
| Module | Entry Point | Purpose |
|--------|-------------|---------|
| Parser | src/parser/index.ts | AST parsing |
| CLI    | src/cli/main.ts     | Command handling |
...

## API Gotchas (Error Prevention)
- Library X: use `methodA()` NOT `methodB()` (renamed in v3)
- Never hardcode port Y, use env var Z
- Framework quirk: always do X before Y

## Known Issues
- Brief list of active bugs/limitations

## Topic Files (read when working in these areas)
- `.claude/memory/topics/auth.md` - Auth flow, tokens, sessions
- `.claude/memory/topics/database.md` - Schema, migrations, queries
- `.claude/memory/topics/frontend.md` - Components, hooks, state
```

**Rules:**
- MAX 200 lines (truncated after that)
- Every row in a table = one domain Claude can navigate to instantly
- No completed sprint/task history (query your task system instead)
- No "New Files Created" lists (the module map IS the file index)
- No feature roadmaps marked "DONE"

### Layer 2: Topic Files (On-demand, not auto-loaded)

Store deep-dive context in `.claude/memory/topics/`. MEMORY.md lists them, Claude reads only the relevant one when needed.

**Create one file per major domain:**

```
.claude/memory/topics/
  auth.md          # Auth flow, token refresh, session management
  database.md      # Schema overview, migration patterns, query patterns
  frontend.md      # Component inventory, hook patterns, state management
  api.md           # Endpoint patterns, middleware, error handling
  deployment.md    # Docker, CI/CD, environment configs
  testing.md       # Test patterns, fixtures, mocking strategies
```

**Each file should be 40-80 lines** covering:
- Import cheat sheets / code snippets
- File locations for that domain
- Common patterns and anti-patterns
- Configuration details

### Layer 3: CLAUDE.md (Auto-loaded, rules only)

Keep CLAUDE.md focused on **rules that prevent errors**, not architecture descriptions.

**What to KEEP in CLAUDE.md:**
- Mandatory coding rules (defensive math, null checks, etc.)
- Build/deploy commands (Docker, test commands)
- Orchestration/routing rules
- Pre-implementation checklists
- Lessons learned (bug patterns to avoid)

**What to MOVE OUT of CLAUDE.md:**
- Detailed architecture descriptions -> topic files
- Auth flow details -> `topics/auth.md`
- Database schema -> `topics/database.md`
- Agent/service inventories -> `topics/agents.md`
- API endpoint lists -> MEMORY.md module map

**Target: CLAUDE.md under 250 lines.**

---

## Implementation Checklist

### Step 1: Audit Current Files (10 min)
- [ ] Count lines in CLAUDE.md and MEMORY.md
- [ ] Identify lines that are history/completed items (delete these)
- [ ] Identify architecture sections that could be topic files (move these)
- [ ] Identify missing navigational content (add module map)

### Step 2: Build the Module Map (30 min)
- [ ] Scan your entry point (main.py, app.ts, etc.) for all route/module registrations
- [ ] For each route, identify the primary service/handler file
- [ ] Create the Backend Module Map table in MEMORY.md
- [ ] Create the Frontend Page Map table (if applicable)
- [ ] Add infrastructure quick reference

### Step 3: Create Topic Files (45 min)
- [ ] Create `.claude/memory/topics/` directory
- [ ] Write 3-5 topic files for your major domains (40-80 lines each)
- [ ] Add topic file pointers to MEMORY.md
- [ ] Move detailed sections from CLAUDE.md to topic files

### Step 4: Trim CLAUDE.md (20 min)
- [ ] Replace moved sections with one-line pointers to topic files
- [ ] Remove stale references (old configs, deprecated features)
- [ ] Verify all mandatory rules are still present
- [ ] Target: under 250 lines

### Step 5: Clean Up Noise (10 min)
- [ ] Remove or relocate auto-generated log files from `.claude/memory/`
- [ ] Fix any broken hook/tool references in `.claude/settings.json`
- [ ] Clear empty template files that waste exploration time

---

## Anti-Patterns (What NOT to Do)

| Anti-Pattern | Why It's Bad | Fix |
|-------------|-------------|-----|
| Sprint/task history in MEMORY.md | Wastes auto-loaded context on past work | Query your task API instead |
| "DONE" items in roadmaps | Zero value for new work | Delete completed items |
| "New Files Created" lists | Stale quickly, duplicates module map | Use module map tables |
| Verbose architecture prose | Claude reads tables 10x faster than paragraphs | Use tables |
| Everything in CLAUDE.md | 500+ lines of system prompt slows processing | Split into layers |
| Auto-generated codebase maps | Too verbose, unfocused | Hand-curate the 80/20 |
| MCP servers for project context | Over-engineering | Topic files are simpler |
| Spec agents per feature | Overkill for most projects | Topic files cover it |

---

## Expected Results

| Metric | Before | After |
|--------|--------|-------|
| Cold-start time | 3-5 minutes exploring | 30-60 seconds reading map |
| System prompt size | 500+ lines (wasteful) | ~400 lines (focused) |
| File discovery | Glob + grep per domain | Direct lookup from table |
| Domain context | Full codebase exploration | Read one 60-line topic file |

---

## Layer 4: QMD Semantic Search (Optional, High Impact)

If your project has significant documentation (.md files), QMD adds on-demand search via MCP tools. Claude gets native `qmd_search`, `qmd_vsearch`, and `qmd_query` tools that search all indexed docs instantly.

### Setup

1. **Install QMD**:
   ```bash
   bun install -g qmd
   ```

2. **Index your project**:
   ```bash
   qmd collection add /path/to/project --name MyProject --mask "**/*.md"
   qmd update
   qmd embed  # Generate semantic embeddings (takes a few minutes)
   ```

3. **Add context descriptions** (improves search relevance):
   ```bash
   qmd context add "qmd://MyProject" "Brief description of what this project is"
   qmd context add "qmd://MyProject/docs" "Documentation: guides, API reference, architecture"
   ```

4. **Add MCP server to Claude Code** (`.mcp.json`):
   ```json
   {
     "mcpServers": {
       "qmd": {
         "command": "bash",
         "args": ["/path/to/qmd", "mcp"],
         "env": { "HOME": "/path/to/home" }
       }
     }
   }
   ```
   Note: On Windows with Bun, QMD is a bash script at `~/.bun/install/global/node_modules/qmd/qmd`. The `HOME` env var must be set explicitly.

5. **Add instructions to CLAUDE.md**:
   ```markdown
   ## SEARCH BEFORE EXPLORING
   Before using Glob/Grep, use QMD MCP tools for documentation lookup:
   - qmd_search "keyword" - Fast BM25 keyword search
   - qmd_vsearch "concept" - Semantic search by meaning
   - qmd_query "question" - Hybrid search (best quality)
   - qmd_get "path.md" - Retrieve full document
   ```

### How It Fits the 4-Layer Architecture

```
Layer 1: MEMORY.md (auto-loaded) -> instant file lookup via tables
Layer 2: Topic files (on-demand) -> domain deep-dives
Layer 3: CLAUDE.md (auto-loaded) -> mandatory rules
Layer 4: QMD MCP (on-demand)     -> search ALL docs by meaning
```

Claude's workflow becomes:
1. Read MEMORY.md module map -> knows which files to modify
2. Read topic file -> knows domain patterns
3. `qmd_query "how does X work"` -> finds relevant docs instantly
4. Only then use Glob/Grep for source code

### When QMD Is Worth It

| Project Size | Documentation | Worth It? |
|-------------|---------------|-----------|
| Small (<50 files) | Few docs | No - topic files are enough |
| Medium (50-200) | 10+ docs | Maybe - if docs are detailed |
| Large (200+) | 20+ docs | Yes - saves significant exploration time |

### Keeping the Index Fresh

Run `qmd update` after adding new .md files. Can be automated via git hooks:
```bash
# .git/hooks/post-commit
qmd update --quiet 2>/dev/null &
```

---

## Template: Minimal MEMORY.md for a New Project

```markdown
# [Project Name] - Navigation Map

## Quick Reference
- **Stack**: [language] + [framework] + [database]
- **Dev server**: port [X]
- **Config**: [config file path]

## Module Map
| Module | Entry File | Purpose |
|--------|-----------|---------|
| [name] | [path]    | [1-line description] |

## API Gotchas
- [Library gotcha 1]
- [Framework gotcha 2]

## Known Issues
- [Active issue 1]

## Topic Files
- `.claude/memory/topics/[domain].md` - [what's covered]
```

## Template: Minimal Topic File

```markdown
# [Domain] Deep Dive

## Key Files
- `path/to/main_file.py` - [purpose]
- `path/to/config.py` - [purpose]

## Patterns
- [Pattern 1 with code snippet]
- [Pattern 2 with code snippet]

## Common Issues
| Problem | Fix |
|---------|-----|
| [issue] | [solution] |
```
