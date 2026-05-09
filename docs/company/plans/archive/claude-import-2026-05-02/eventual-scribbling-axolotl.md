# Plan: Wire gstack QA/Review/Ship into Legion + Visual Regression Grading

## Context

Legion has powerful backend services (sprint execution, release management, quality grading) but lacks the "last mile" operator-facing workflows that gstack provides. gstack v0.15.16.0 is already installed at `~/.claude/skills/gstack/` with 35+ skills available. This plan integrates gstack's QA, review, and ship capabilities into Legion's autonomous loop AND creates a `/legion-ship` skill for manual operator use. Additionally, it wires the browse daemon into the sprint quality grader for visual regression detection.

**Key insight**: gstack's `/qa` and `/review` already work on any repo. We don't need to rewrite them — we need to (a) invoke them from Legion's autonomous flow, and (b) create Legion-specific wrappers for the operator.

---

## Phase 1: /legion-ship Skill (New Skill)

**Files to create:**
- `c:\code\Legion\.claude\skills\legion-ship\SKILL.md`

**What it does:**
Unified ship command for the Legion operator. Steps:
1. Pre-flight: `git status`, `git diff --stat`, identify changed files
2. Run backend tests: `cd backend && python -m pytest tests/ -v --timeout=120`
3. Run frontend type-check: `cd frontend && npm run build`
4. Docker rebuild + verify: `docker-compose build legion-backend legion-frontend && docker-compose up -d && sleep 10 && curl -s http://localhost:8005/health`
5. Review diff: Invoke gstack `/review` via the Skill tool for pre-commit code analysis
6. Commit: Create git commit following Legion's `[Nightly Sync YYYY-MM-DD]` convention
7. Verify post-commit health: `curl -s http://localhost:8005/health | python -m json.tool`

**Pattern**: Follows Legion skill format (YAML frontmatter with `metadata.legion.*`, direct step instructions).

---

## Phase 2: Wire /review as Pre-Merge Gate in Autonomous Loop

**File to modify:**
- `backend/app/services/agentic_loop_service.py` (~line 905-911)

**Insertion point**: Line 906 of `agentic_loop_service.py`, between QA gate's except block (line 905) and the `complete_sprint()` call (line 911). Verified: line 906 is a blank line.

**What to add:**
A new `_run_code_review_gate()` async method that:
1. Gets the git diff for files changed by this sprint's tasks (query `sprint_tasks` for file paths, or `git diff HEAD~N` where N = task count)
2. Runs a lightweight code review by calling `unified_llm_service.execute()` with a structured prompt containing Legion-specific checklist:
   - `case()` must import from `sqlalchemy`, never `func.case()`
   - PostgreSQL enum values are UPPERCASE (`'ACTIVE'` not `'active'`)
   - Fresh `AsyncSessionLocal()` per DB operation after any LLM call
   - No bare `except: pass` — always `except Exception as e: logger.warning(...)`
   - Module import paths must match actual filenames (singular vs plural)
   - Decimal coercion before JSONB writes or float math
   - FastAPI literal routes before `/{param}` routes
3. Stores review summary on sprint via `description` append (no new columns needed)
4. If review finds CRITICAL issues, logs a warning but does NOT block (default)
5. Add `CODE_REVIEW_BLOCKING=false` env var — when true, creates fix tasks and returns early

**Design decisions:**
- NOT invoking gstack /review as a subprocess (too heavy — spawns subagents, 5+ min)
- Lightweight LLM review with Legion-specific rules only (~10s, single LLM call)
- Non-blocking by default so it doesn't regress sprint completion rate
- Results feed into the new `code_review` grader dimension

**New Sprint Quality Grader dimension:**
- File: `backend/app/services/sprint_quality_grader.py` (line 83-92 WEIGHTS dict)
- Current weights sum to 1.0. Redistribute: `structural_risk` 0.05→0.00, add `code_review` 0.05
- Implement `_grade_code_review()` that parses the review summary appended to sprint description
- Score 100 if no issues found, 70 if warnings only, 30 if critical issues, 0 if review didn't run
- Bump `GRADER_VERSION` from `v4-learn20` to `v5-gstack01`

---

## Phase 3: Wire Browse Daemon into Sprint Quality Grader for Visual Regression

**Files to modify:**
- `backend/app/services/sprint_quality_grader.py`
- `backend/app/services/browser_validation_service.py` (existing, currently dormant)

**What to add:**

### 3a. Activate `browser_validation_service.py`
The service exists (540+ lines) with full dataclass infrastructure: `ConsoleEntry`, `ScenarioResult`, `BrowserValidationResult`, `UserFlow`, `UserFlowStep`, `StepResult`, `E2EFlowResult`. Already imports Playwright optionally (`PLAYWRIGHT_AVAILABLE` flag at line 29-31). Already targets `localhost:3005` as base_url. Wire it to:
1. Navigate to `http://localhost:3005` (Legion frontend)
2. Take screenshots of key pages: `/` (dashboard), `/sprints` (sprint center), `/learning` (learning dashboard), `/llm-console` (LLM console)
3. Check for JavaScript console errors via `ConsoleEntry` capture
4. Check for HTTP 4xx/5xx network errors
5. Verify key elements render (sidebar present, main content area not empty)

### 3b. New grader dimension: `frontend_health`
- Add to WEIGHTS dict (~5% weight)
- `_grade_frontend_health()` method:
  - Calls `browser_validation_service.validate_pages()`
  - Score 100 if no console errors + all pages render + no network errors
  - Score 70 if minor console warnings only
  - Score 30 if any page fails to render or has JS errors
  - Score 0 if frontend is unreachable
- Wrap in try/except so Playwright unavailability doesn't break grading (return score=50 with note "browser validation unavailable")

### 3c. Integration with gstack browse (optional enhancement)
If gstack's browse binary is available at `~/.claude/skills/gstack/bin/browse.exe`:
- Use it instead of raw Playwright for faster execution (~100ms vs ~3s per command)
- Run: `$BROWSE goto http://localhost:3005 && $BROWSE screenshot /tmp/legion-dashboard.png && $BROWSE console`
- Parse console output for errors
- This is an OPTIONAL path — the Playwright-direct path is the primary

---

## Phase 4: Document "Use /qa Directly" (Zero-Code)

**File to create:**
- `c:\code\Legion\.claude\skills\legion-qa-guide\SKILL.md`

**What it does:**
A thin guide skill that tells the operator HOW to use gstack's existing `/qa` on Legion:
1. Ensure Legion frontend is running: `curl -s http://localhost:3005`
2. Invoke `/qa` with the target URL: "Run QA on http://localhost:3005"
3. Document which Legion pages to test and what to look for
4. Provide the 24-page sitemap from App.tsx for comprehensive testing
5. List known UI issues to ignore vs real regressions

This is NOT a code skill — it's documentation packaged as a skill so it shows up in the operator's skill list.

---

## Implementation Order

1. **Phase 1** (legion-ship skill) — Pure file creation, no backend changes, immediately usable
2. **Phase 4** (QA guide) — Pure file creation, no backend changes
3. **Phase 2** (review gate in agentic loop) — Backend change, requires Docker rebuild + verification
4. **Phase 3** (visual regression grading) — Backend change, requires Playwright availability check

---

## Files Summary

| File | Action | Phase |
|------|--------|-------|
| `.claude/skills/legion-ship/SKILL.md` | CREATE | 1 |
| `.claude/skills/legion-qa-guide/SKILL.md` | CREATE | 4 |
| `backend/app/services/agentic_loop_service.py` | EDIT (add review gate ~line 905) | 2 |
| `backend/app/services/sprint_quality_grader.py` | EDIT (add 2 new dimensions) | 2+3 |
| `backend/app/services/browser_validation_service.py` | EDIT (activate + wire) | 3 |

---

## Verification

### Phase 1 verification:
- Run `/legion-ship` from Claude Code — should execute full pipeline (tests, build, review, commit)
- Verify git log shows proper commit format

### Phase 2 verification:
- Trigger a sprint completion (or force via `POST /api/sprints/{id}/complete`)
- Check logs for `[CodeReview]` log lines
- Check `sprint_quality_grades` for new `code_review` dimension
- Verify non-blocking mode doesn't halt sprint completion

### Phase 3 verification:
- Run `SprintQualityGrader().grade_sprint(latest_sprint_id)`
- Check for `frontend_health` dimension in grade output
- Verify screenshots captured at `/tmp/legion-*.png`

### Phase 4 verification:
- Run `/legion-qa-guide` from Claude Code — should display instructions
- Follow instructions to run `/qa` on `http://localhost:3005`

---

## Sprint Tracking

Create sprint: `GStack-01: Wire gstack QA/Review/Ship into Legion`
- Task 1: Create /legion-ship skill (Phase 1)
- Task 2: Create /legion-qa-guide skill (Phase 4)
- Task 3: Add code review gate to agentic loop (Phase 2)
- Task 4: Add code_review dimension to sprint quality grader (Phase 2)
- Task 5: Activate browser_validation_service for visual regression (Phase 3)
- Task 6: Add frontend_health dimension to sprint quality grader (Phase 3)
- Task 7: Docker rebuild + end-to-end verification
