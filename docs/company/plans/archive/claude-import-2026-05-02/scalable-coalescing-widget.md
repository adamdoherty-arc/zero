# Legion Sprint Quality Audit — 2026-04-07

> Note: plan file path is leftover from a prior session. This document is the
> output of `/legion-sprint-auditor` for sprint quality audit + recommended
> follow-up sprint.

## Context

Run `/legion-sprint-auditor` was invoked to grade Legion's recent sprint
execution quality and identify the highest-leverage fix to improve the next
batch of sprints. The audit pulled grades for the 10 most recent gradeable
sprints (project_id=3), inspected the learning pipeline (annotations, episodes,
templates, daemons), and cross-checked Prometheus counters.

The audit is **read-only** — its sole deliverable is this report and a
recommended `Improve-NN` sprint that the user can run after approving.

---

## Overall Health

**Average overall score (last 10 sprints): 51.4 / 100** — barely above the
"Current Target" benchmark of 50, dragged up by a single outlier (Sprint 2871
@ 86.9). Median is **46.5**, mode is **44.8**. Trend is **flat-with-regression**
since Recovery-01 — the swarm-path fix delivered Sprint 2871=86.9 and Sprint
2870=60.4, but every sprint generated *after* those (2873–2889) has scored
40–50 because the recovery/RCA pipeline is now firing but its tasks are
failing on a new error mode.

| # | Sprint | Name | Status | Overall | Worst Dim |
|---|--------|------|--------|---------|-----------|
| 1 | 2889 | Fix-56: RCA — minimax api overloaded_error | FAILED | 44.8 | learning_capture=0 |
| 2 | 2886 | Fix-55: RCA — minimax api overloaded_error | FAILED | 44.8 | learning_capture=0 |
| 3 | 2882 | Auto-Sprint 20260407-0509 | FAILED | 47.0 | learning_capture=0 |
| 4 | 2877 | Fix-54: RCA — task stuck recovered | FAILED | 46.8 | exec_success=12 |
| 5 | 2874 | Fix-53: RCA — task stuck recovered | FAILED | 42.8 | learning_capture=0 |
| 6 | 2873 | Auto-Sprint 20260407-0325 | FAILED | 47.6 | learning_capture=0 |
| 7 | 2871 | Smoke-01: Recovery-01 swarm-path verification | COMPLETED | **86.9** | task_decomp=85 |
| 8 | 2870 | Recovery-01: Make Legion actually work | FAILED | 60.4 | learning_capture=0 |
| 9 | 2869 | Fix-52: RCA — task minutes timed | FAILED | 46.3 | learning_capture=0 |
| 10 | 2868 | Fix-51: RCA — task stuck recovered | FAILED | 46.3 | learning_capture=0 |

---

## Dimension Grades

| Dimension | Avg (last 10) | vs Target | Notes |
|-----------|---------------|-----------|-------|
| Task Decomposition | **87.4** | ✅ 60 / 80 | Strong — generator producing well-shaped tasks (avg 423–938 chars, story points present) |
| Prompt Quality | **60.4** | ✅ 50 / 75 | Stalled on annotation snapshot (req=64.8 / resp=56.1, n=63). 136 pending annotations not yet folded in |
| Routing Effectiveness | **43.0** | ⚠ 40 / 70 | Only Sprint 2871 has routing traces (1 record, success_rate=1.0). All other sprints score 40 (no traces) |
| Execution Success | **20.8** | ❌ 70 / 90 | **CRITICAL** — 8 of 10 sprints have completion_rate=0%. All RCA fix sprints fail their single task |
| Learning Capture | **15.0** | ❌ 30 / 60 | **CRITICAL** — 8 of 10 score 0. Only 2871 (100) and 2877 (50) capture anything |
| QA Gate | **55.0** | ⚠ 60 / 85 | Only Sprint 2871 has approved tasks. Everything else stuck at the default 50 |
| Time Efficiency | **86.0** | ✅ 50 / 75 | Strong — most failed-fast tasks bank the high score, but it masks the real problem |

---

## Learning Pipeline Health

| Component | Status | Evidence |
|-----------|--------|----------|
| Backend (`/health`) | ✅ healthy | DB connected, daemons running |
| LLMReview daemon | ⚠ running but **broken** | Reviewing 1–4 calls/batch, but `avg=None` and `flagged=0` for hours — Pydantic validation failing on `LLMReviewResponse` (4 missing fields: score, summary, answered_prompt, actionable). MiniMax responding with `improved_system_prompt` only. |
| Prompt evaluator | (no recent log line in tail) | 136 pending annotations vs 26 action_taken — backlog growing |
| Annotations | 136 pending, 26 action_taken | Backlog 5.2x action_taken |
| Improvements | 5 applied, 4 approved | Healthy ratio, but volume tiny vs sprint count |
| Templates evolved | 4 of 15 (v≥2) | code_review v3, planning/code_gen/debugging v2 |
| Most-used template | `task_type:general` v1, 1095 uses, avg_quality=97.5 | Never evolved despite 1095 uses — v1 is "good enough" |
| Episodes stored | 85 total across 9 task_types | Low volume but quality high (avg 0.85–1.00) |
| Sprint learnings (last 10 sprints) | 5 records (2 failure, 2 success, 1 routing) | Only Sprint 2871 produced full learning records — every other recent sprint stored zero |
| `legion_learning_writes_total` | sprint_learning=845, enhanced=28, model_perf=28 | Aggregated learning is live but lopsided — 30:1 ratio between basic and enhanced stores |
| `legion_sprint_quality_grades_total` | 23 graded, all in 40–50 bucket | Every grade since process restart sits in `le=50` |
| `legion_learning_engine_enrichments_total` | (counter present but no values shown) | Need to verify it's incrementing — could be a wiring gap |

---

## Top Issues (ranked by leverage)

### 1. MiniMax `overloaded_error` is killing every recovery sprint (HIGHEST)
Sprint 2886/2889 are RCA fix sprints that triggered on prior failures, then
themselves failed with "minimax api overloaded_error" — a new failure mode
distinct from `insufficient_balance_error` (Recovery-01). The recovery loop
is now hot but the LLM provider is rejecting load:
- `Fix-55` and `Fix-56` literally have the failure cause embedded in the
  sprint name, meaning the loop is observing the failure but cannot recover
  because the provider is the bottleneck.
- We have **zero retry/backoff** for `overloaded_error` — Recovery-01 only
  added the latching circuit breaker for `insufficient_balance_error`.
- Result: every Auto-Sprint and every Fix sprint inherits the same error
  and fails on its first task.

### 2. `LLMReviewResponse` schema is wrong (HIGH)
LLM review daemon log shows repeated `Structured output validation failed`:
```
4 validation errors for LLMReviewResponse
score          Field required ... input has only 'improved_system_prompt'
summary        Field required ...
answered_prompt Field required ...
actionable     Field required ...
```
MiniMax is returning `{"improved_system_prompt": "..."}` but the schema
demands `score`, `summary`, `answered_prompt`, `actionable`. Result: every
review batch logs `flagged=0, avg=None`, the daemon never produces
actionable signals, and the Prompt Quality dimension can never improve from
its frozen 60.4.

### 3. Learning Capture is 0 on every failed sprint (HIGH)
Only sprints that *complete* are storing learnings (2871=4 records).
Every FAILED sprint stores nothing — yet the failure-side learning is
the most valuable signal. Looking at sprint_learnings for last 10 sprints
we see only 5 total records:
- 2 success (both from Sprint 2871)
- 2 failure (likely from Sprint 2870, the only multi-task failure)
- 1 routing (Sprint 2871)
Recovery-01's "store_episode on failure" wiring exists in autonomous
executor, but the **agent_swarm path** that all Auto-Sprints take still
isn't storing failure episodes.

### 4. Prompt-evaluator backlog growing (MEDIUM)
136 annotations pending vs only 26 action_taken — the evaluator is queueing
faster than improvements are being approved/applied. Either the evaluator is
running but improvement promotion is stalled, or the evaluator daemon
silently failed and only the *backlog* is growing (no new annotations).
The cached `(req=64.8, resp=56.1, n=63)` pair on every grade since the
counter restarted strongly suggests **the annotation snapshot is stale**:
the grader is reading 63 annotations and never re-fetching.

### 5. `task_type:general` template never evolved despite 1095 uses (LOW-MEDIUM)
v1, avg_quality=97.5 — looks fine, but at 1095 uses it's the most leverage-
heavy template in the system. If we can squeeze even +1pt average from
v2, that's +1095 quality-units of impact. Currently no improvement loop
is targeting it because annotations score it as already-good.

---

## Recommended Sprint

> Goal: in one sprint, unblock the recovery loop, fix the silent LLM-review
> daemon, and get failure-path learning flowing again. After this sprint
> the next audit cycle should see grades climbing back into the 60s.

```
Name:      Improve-01: Recovery-loop unblock + learning resume
Project:   3 (Legion)
Tasks:     6
```

### Tasks

1. **Add MiniMax overloaded_error handling**
   - File: `backend/app/services/llm_clients/errors.py`
   - Add `MinimaxOverloadedError(LLMError)` exception class
   - File: `backend/app/services/llm_clients/minimax_client.py`
   - Detect `overloaded_error` substring in 429/503 response body and raise
     `MinimaxOverloadedError` (not the latching circuit breaker — this is
     transient, not balance-exhaustion)
   - File: `backend/app/services/unified_llm_service.py`
   - In `_acquire_minimax_slot()`/execute path: on `MinimaxOverloadedError`
     apply exponential backoff (5s, 15s, 45s) up to 3 attempts before
     escalating, **distinct** from the latching `_minimax_balance_exhausted`
     breaker. Log a Prometheus counter `legion_minimax_overloaded_total`.

2. **Fix LLMReviewResponse schema**
   - File: `backend/app/services/llm_response_validator.py` (or wherever
     `LLMReviewResponse` is defined — grep `class LLMReviewResponse`)
   - Make `score`, `summary`, `answered_prompt`, `actionable` Optional with
     sane defaults, OR update the LLM-review system prompt to demand all 4
     fields explicitly with a JSON example.
   - Verify the resolution by re-running a single review:
     `POST /llm-review/run` with batch_size=1, then check that `avg` in the
     batch log is no longer `None`.

3. **Wire failure-path episode storage into agent_swarm**
   - File: `backend/app/services/agent_swarm_service.py`
   - In `advance_task_node` *failure* branch, mirror the success-branch
     wiring added in Fix-52: call `episodic_memory_service.store_episode()`
     with `quality_score=0.3`, `outcome="failure"`, last_error in metadata.
   - Coverage check: after 1 failed sprint, query
     `SELECT count(*) FROM episodes WHERE task_type='X' AND quality_score<0.5`
     and confirm it's incrementing.

4. **Fix stale annotation snapshot in grader**
   - File: `backend/app/services/sprint_quality_grader.py`
   - The repeated `(req=64.8, resp=56.1, n=63)` across every recent grade
     proves the annotation query is cached/stale. Verify `_grade_prompts`
     is querying `prompt_annotations` per call, not a cached snapshot. If
     a class-level cache exists, drop it or add a 5-minute TTL.

5. **Reset prompt evaluator backlog**
   - Verify the prompt evaluator daemon is actually running:
     `docker logs legion-backend 2>&1 | grep -i "PromptEvaluator" | tail -5`
   - If silent, check `task_health_registry` and restart the daemon via
     the supervised task path.
   - With 136 pending annotations, force-promote the top 20 highest-impact
     ones to `action_taken` so the next grade window has fresh data.

6. **Verify with a smoke sprint**
   - After tasks 1–5, manually create a single-task `Smoke-02:
     Improve-01 verification` sprint that exercises the fixed paths:
     execute one task → confirm overloaded_error retries work → confirm
     failure episode is stored → confirm grader picks up new annotations.
   - Acceptance: Smoke-02 grades ≥ 70 with all 7 dimensions populated.

---

## Critical Files (read before executing)

- `backend/app/services/llm_clients/minimax_client.py` — current 429 handling,
  `_is_insufficient_balance` check (Recovery-01)
- `backend/app/services/unified_llm_service.py:_acquire_minimax_slot` — where
  the latching breaker lives, where overloaded handling should plug in
- `backend/app/services/llm_response_validator.py` — `LLMReviewResponse`
  Pydantic model (target of task 2)
- `backend/app/services/llm_review_service.py:run_review_batch` — daemon that
  is logging the validation errors
- `backend/app/services/agent_swarm_service.py:advance_task_node` — failure
  branch is missing episode storage (mirror the success branch wired in Fix-52)
- `backend/app/services/sprint_quality_grader.py:_grade_prompts` — annotation
  read path, suspected stale cache

## Verification (after Improve-01 runs)

```bash
# 1. Confirm overloaded_error handling fires under load
docker logs legion-backend 2>&1 | grep -c "MinimaxOverloadedError"
curl -s http://localhost:8005/metrics | grep legion_minimax_overloaded_total

# 2. Confirm LLM review daemon producing real scores
docker logs legion-backend 2>&1 | grep "LLMReview.*Batch complete" | tail -5
# Expect: avg=NN.N (NOT avg=None)

# 3. Confirm failure episodes are flowing
docker exec legion-db psql -U legion -d legion -c \
  "SELECT outcome, count(*) FROM episodes WHERE created_at > now() - interval '1 hour' GROUP BY outcome;"
# Expect: at least 1 row with outcome='failure'

# 4. Re-grade the same set of sprints
curl -s "http://localhost:8005/api/sprint-quality/recent/list?project_id=3&limit=10" | \
  python -c "import json,sys; data=json.load(sys.stdin); print(f'avg={sum(s[\"overall_score\"] for s in data)/len(data):.1f}')"
# Expect: avg climbs from 51.4 → 60+

# 5. Smoke sprint
# Execute Smoke-02 manually and check grade ≥ 70
```

---

## Knowledge Files To Update (after sprint approved + executed)

- `.claude/skills/legion-sprint-auditor/knowledge/sprint_audit_history.json`
  → append today's row (date=2026-04-07, sprints_graded=10, avg_overall=51.4,
  worst=execution_success)
- `.claude/skills/legion-sprint-auditor/knowledge/improvement_patterns.md`
  → document MiniMax overloaded_error pattern + LLMReviewResponse schema bug
  for future audit runs
