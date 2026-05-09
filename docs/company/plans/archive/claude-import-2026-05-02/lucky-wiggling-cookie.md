# Learn-14 → Learn-17: Continuous Prompt Improvement Roadmap

## Context

The user reviewed Legion's LLM Console and is "seeing too many bad prompts." They want every LLM request/response evaluated, learned from, and continuously improved — with the critique attached to each response so it visibly says "how this prompt could be better."

Phase 1 research found that **Legion already has ~60% of this built**:

- **`backend/app/services/prompt_evaluator_agent.py`** — 10-min daemon, scores requests + responses on 6 dimensions via MiniMax structured output, flags <70 to annotation queue
- **`backend/app/services/llm_review_service.py`** — 5-min daemon, semantic review via MiniMax, severity tiers, auto-creates LLM-Fix sprints
- **`backend/app/services/annotation_queue_service.py`** — `PromptAnnotationDB` + `PromptImprovementDB`, `auto_apply_improvements()` writes to `PromptTemplateDB`
- **`backend/app/services/prompt_evolution_service.py`** — variant tracking + LLM-driven evolution
- **`backend/app/services/prompt_manager_service.py`** — versioned `PromptTemplateDB` registry
- **`backend/app/services/learning_engine.py`** — `enrich_task_context()` is the single learning injection point at line 167
- **`backend/app/services/llm_call_tracker.py`** — in-memory ring buffer + DB persist + WebSocket events
- **`backend/app/models/llm_call_detail.py`** — already has `review_status`, `review_score`, `review_summary`, `review_flags`, `reviewed_at`

**Critical gaps the user is hitting:**

1. The LLM Console UI (`frontend/src/pages/LLMConsole.tsx`) does **not** display any review/improvement data — the backend writes it, the frontend ignores it. Invisible quality data.
2. There is **no `suggested_improvement` text column on `llm_call_details`** — flagged calls only exist in a separate `prompt_annotations` table not joined to the console view.
3. ~90% of live LLM calls bypass `PromptTemplateDB` (use task.prompt directly), so improvements applied to templates never reach the actual calls.
4. **No closed-loop verification** — improvements get applied but nothing measures whether they actually helped.
5. **No A/B testing or auto-rollback** when an "improvement" regresses.
6. No OSS framework integration for serious prompt optimization.

**OSS framework research (Phase 1):**

- **TextGrad** ([zou-group/textgrad](https://github.com/zou-group/textgrad), MIT, Nature paper) — "PyTorch for text". `.backward()` on a failed task returns a natural-language gradient/critique. Best fit for per-call critique generation. Wraps prompt+response as `tg.Variable`, uses existing signals (`test_passed`, `qa_status`, `sprint_grade`) as the loss.
- **DSPy + GEPA** ([stanfordnlp/dspy](https://github.com/stanfordnlp/dspy) + [gepa-ai/gepa](https://github.com/gepa-ai/gepa), Apache 2.0, ICLR 2026 Oral) — Reflective prompt evolution via execution-trace reflection. Proven LangGraph integration. Best fit for nightly batch-evolution of high-volume templates.
- **Microsoft Trace / OptoPrime** — Most ambitious (optimizes whole graph) but high integration cost; defer.

**User decisions** (from AskUserQuestion):

- Critique timing: **Synchronous inline with each response** *(see deviation note in Learn-15)*
- OSS framework: **TextGrad + DSPy/GEPA (full)**
- Closed loop: **Full auto-apply with rollback**
- Scope: **Full roadmap Learn-14 → Learn-17**

**Recovery-01 constraints (DO NOT break):**

- MiniMax M2 is the only active provider; Ollama + Kimi disabled
- MiniMax has a process-wide latching `insufficient_balance` circuit breaker — restart-only clear
- Sprint 2871 = first sprint with `learning_capture=100`; Execution=100 floor
- Do NOT regress these gains

---

## Cross-Sprint Dependencies

```
Learn-14 (foundation: surface + backfill + verify)
   |
   +-- Learn-15 (TextGrad sync critique; writes suggested_improvement)
   |
   +-- Learn-16 (DSPy/GEPA nightly evolution; canary template versions)
              |
              +-- Learn-17 (verification loop; auto-rollback)
```

- **Learn-14 must be first** (foundation)
- **Learn-15 and Learn-16 can run in parallel** after Learn-14
- **Learn-17 must be serial after Learn-16** (needs canary lifecycle)

---

## Pre-flight Checklist (before starting Learn-14)

1. Verify daemons are actually cycling:
   ```bash
   docker exec legion-backend env | grep -E "ENABLE_LLM_REVIEW|ENABLE_PROMPT_EVALUATOR"
   docker logs legion-backend --tail 500 2>&1 | grep -E "PromptEvaluator|LLMReview"
   ```
   *If no "Cycle complete" logs in the last 60 min, the daemons are dead — Fix sprint required first.*
2. MiniMax balance non-zero, breaker closed: `curl -s http://localhost:8005/llm/health`
3. Migration head clean: `docker exec legion-backend alembic current` → expect `027`
4. Snapshot baseline metrics for regression comparison:
   ```sql
   SELECT COUNT(*), AVG(review_score), AVG(quality_score)
   FROM llm_call_details
   WHERE created_at > now() - interval '24 hours' AND review_status != 'pending';
   ```
5. Confirm Sprint 2871's `learning_capture=100` is still the high-water mark in `sprint_grades`
6. `LLM_EXEMPT_SOURCES` unchanged since Recovery-01

---

## Top-5 Risks & Mitigations

| # | Risk | Mitigation |
|---|------|------------|
| 1 | **MiniMax balance exhaustion from sync critique (Learn-15)** doubles spend; latching breaker requires restart | Hard env-var guards: `TEXTGRAD_SAMPLE_RATE` (default 0.2 ramp to 1.0), `TEXTGRAD_DAILY_BUDGET_USD` (default 5), check `_minimax_balance_exhausted` before every call, exempt all `LLM_EXEMPT_SOURCES`, skip <50 char responses |
| 2 | **Auto-rollback false positives (Learn-17)** small-sample variance flips genuine improvements to "regression" | 50-call minimum window, require p<0.1 (scipy.stats.ttest_ind), require delta to persist across 2 consecutive cycles, cap rollbacks to 1 per template per 24h |
| 3 | **Latency regression on user-facing endpoints (Learn-15)** sync TextGrad adds 3-8s | **Deviation from spec**: implement as fire-and-forget `asyncio.create_task` not true sync. Caller latency stays at zero, every call still gets critiqued, persisted via `update_call_improvement`. Expose `TEXTGRAD_MODE=sync\|async` env var (default async). Document deviation in Learn-15 PR. |
| 4 | **GEPA evolves a template that regresses real sprints (Learn-16)** | New templates created `is_active=False, canary_eligible=True, canary_traffic_pct=10`. Never auto-promote without Learn-17 verification. Never run GEPA on a template `updated_at < 48h` ago. Never delete parent version. |
| 5 | **Self-referential critique loop (Learn-15)** TextGrad makes MiniMax calls that get persisted and re-flagged | Tag TextGrad/DSPy/verifier calls with `_source="textgrad_critic"` / `"dspy_optimizer"` / `"feedback_verifier"` and add to `LLM_EXEMPT_SOURCES` in Learn-14 (defensive one-line edit) |

---

# Learn-14: Foundation — Surface, Verify, Backfill

## Goal
Make the existing eval/review machinery visible in the LLM Console UI, add the schema columns Learn-15/16/17 need, verify daemons are running, and backfill suggestions for the last 500 unevaluated calls.

## Files to create
- **[backend/alembic/versions/028_add_llm_call_improvement_columns.py](backend/alembic/versions/028_add_llm_call_improvement_columns.py)** — Adds to `llm_call_details`: `suggested_improvement` (Text), `improvement_score` (Integer 0-100), `improvement_applied_at` (DateTime), `improvement_source` (String 30: `evaluator`/`textgrad`/`review_agent`), `prompt_template_id` (FK→prompt_templates ON DELETE SET NULL). Indexes on `(prompt_template_id, created_at DESC)` and partial `WHERE suggested_improvement IS NOT NULL`.

## Files to modify
- **[backend/app/models/llm_call_detail.py](backend/app/models/llm_call_detail.py)** — add 5 new columns to `LLMCallDetailDB`; extend `to_summary()` (line 82) and `to_detail()` (line 110)
- **[backend/app/services/llm_call_tracker.py](backend/app/services/llm_call_tracker.py)** — new method `update_call_improvement(call_id, suggested_improvement, improvement_score, improvement_source)` mirroring `update_quality_score()` at line 281
- **[backend/app/services/prompt_evaluator_agent.py](backend/app/services/prompt_evaluator_agent.py:204)** — in `_evaluate_and_flag()`, after eval, also call `tracker.update_call_improvement(...)` with `improvement_source="evaluator"` (in addition to existing `auto_flag_from_evaluator()`). Load `EVAL_BATCH_SIZE` from env `PROMPT_EVALUATOR_BATCH_SIZE` (default 20)
- **[backend/app/services/llm_review_service.py](backend/app/services/llm_review_service.py)** — also call `tracker.update_call_improvement(..., improvement_source="review_agent")` when review produces actionable suggestion
- **[backend/app/core/constants.py](backend/app/core/constants.py)** — defensively add `"textgrad_critic"`, `"dspy_optimizer"`, `"feedback_verifier"` to `LLM_EXEMPT_SOURCES` (reserves names for Learn-15/16/17, prevents loops)
- **[backend/app/services/unified_llm_service.py](backend/app/services/unified_llm_service.py:716)** — populate `prompt_template_id` on `tracker.start_call()` when `get_template_for_task_type()` returns a hit
- **[backend/app/api/endpoints/llm_console.py](backend/app/api/endpoints/llm_console.py)** — new endpoints:
  - `GET /llm-console/calls/{call_id}/improvement` — joins call with template, returns full improvement detail
  - `POST /llm-console/critique` — body `{call_id, mode: "re_evaluate"|"textgrad"}`. `re_evaluate` reuses `_evaluate_and_flag`. `textgrad` returns 501 until Learn-15.
  - `GET /llm-console/quality-stats` — rolling 24h avg `review_score` + `improvement_score`, top-10 worst sources
  - `POST /llm-console/backfill` — admin: queue last 500 unevaluated calls, rate-limited
  - Extend `/stats` with `today_flagged_count` + `today_avg_review_score`
- **[frontend/src/hooks/useLLMConsole.ts](frontend/src/hooks/useLLMConsole.ts)** — `useLLMCallImprovement(callId)`, `useLLMQualityStats()`; extend `LLMCall` type
- **[frontend/src/pages/LLMConsole.tsx](frontend/src/pages/LLMConsole.tsx)** —
  - **CallRow** (line 77): new "Quality" column with colored badge (green ≥70, yellow 40-69, red <40, gray null)
  - **CallDetailDialog** (line 140): new "Quality Review" section above Error info — review_status badge, score, summary, flag chips, collapsible Suggested Improvement, "Re-evaluate" button POSTing to `/critique`
  - Header stats (line 379): 5th card "Avg Quality (24h)"
  - Filter dropdown for review status

## DB migration
- **`028_add_llm_call_improvement_columns.py`** — revises `027`. All columns NULL/default — strictly additive.

## Existing functions to reuse
- `llm_call_tracker.py:281` `update_quality_score()` — pattern for `update_call_improvement`
- `prompt_evaluator_agent.py:204` `_evaluate_and_flag()` — extend, don't rewrite
- `annotation_queue_service.py:52` `auto_flag_from_evaluator()` — keep parallel path unchanged
- `prompt_manager_service.py:282` `get_template_for_task_type()` — already wired in `unified_llm_service.execute()` line 716, just capture the id
- `llm_console.py:104` `get_call_detail` — extend with template join

## Cost / risk
- **MiniMax**: zero net new calls in steady state. One-shot backfill of 500 calls × 2 evals = ~1000 calls (~$1-2). Run off-peak.
- **Latency**: zero — all daemon-driven
- **Blast radius**: low (purely additive migration + UI). Disable daemons to roll back.

## Verification
```bash
# Migration
docker exec legion-backend alembic upgrade head
docker exec legion-db psql -U legion -d legion -c "\d llm_call_details" | grep -E "suggested_improvement|prompt_template_id"

# Daemons running
docker logs legion-backend --tail 1000 2>&1 | grep -E "PromptEvaluator|LLMReview" | tail -20

# Backfill + verify
curl -s -X POST http://localhost:8005/llm-console/backfill | python -m json.tool
sleep 600  # let evaluator drain
docker exec legion-db psql -U legion -d legion -c \
  "SELECT COUNT(*) FILTER (WHERE suggested_improvement IS NOT NULL), COUNT(*) FROM llm_call_details WHERE created_at > now() - interval '24h';"

# Endpoint
CALL_ID=$(docker exec legion-db psql -U legion -d legion -t -c \
  "SELECT call_id FROM llm_call_details WHERE suggested_improvement IS NOT NULL LIMIT 1;" | xargs)
curl -s http://localhost:8005/llm-console/calls/$CALL_ID/improvement | python -m json.tool

# Frontend: open http://localhost:3005/llm-console — see Quality column, click flagged call, see suggestion
```

## Acceptance criteria
1. Migration `028` applied with 5 new columns + 2 new indexes
2. PromptEvaluator daemon logs "Cycle complete" twice within 30 min of restart
3. ≥200 of 500 backfilled calls have non-null `suggested_improvement` within 2h
4. LLM Console renders Quality column; flagged-call detail shows Suggested Improvement
5. `/calls/{id}/improvement` returns 200 with populated fields
6. `POST /critique` mode=`re_evaluate` returns refreshed suggestion
7. Sprint 2871 metrics not regressed: test sprint scores `learning_capture ≥ 85`
8. `LLM_EXEMPT_SOURCES` contains the 3 reserved names

---

# Learn-15: TextGrad — Per-call Natural-language Critique

## Goal
Add a TextGrad-powered critique fired on every non-exempt LLM call as a fire-and-forget `asyncio.create_task`. Writes `suggested_improvement` + `improvement_score` to `llm_call_details`. Cost-bounded by sample rate, daily budget, latency budget, and exempt-source filtering.

## Deviation from user spec — call out in PR
User chose "synchronous inline". Recommendation: **fire-and-forget per-call task** instead. Caller latency stays zero. Every call still gets critiqued. Optionally enable true sync via `TEXTGRAD_MODE=sync` env var (CI/dev only). Reason: protects Sprint 2871 Execution=100 floor and `/ai/suggest` UX.

## Files to create
- **[backend/app/services/textgrad_critic_service.py](backend/app/services/textgrad_critic_service.py)** — `TextGradCriticService.critique(call_id, prompt, response, task_type, source, sprint_context) → CritiqueResult` dataclass with `critique`, `severity` (info/warning/critical), `dimensions` (clarity/context/format/specificity), `suggested_rewrite`, `improvement_score`. Internal short-circuits: exempt source, response<50 chars, sample-rate roll, MiniMax breaker, daily budget, latency budget. Calls `UnifiedLLMService.execute_structured(_source="textgrad_critic", task_type="GENERAL")`.
- **[backend/app/services/textgrad_loss_signal.py](backend/app/services/textgrad_loss_signal.py)** — `compute_loss(call_id, source, sprint_task_id) → float (0-1)`. Reads `sprint_tasks.test_passed`, `qa_status`, `last_error`, `sprint_grades.overall_score` — no LLM calls.

## Files to modify
- **[backend/requirements.txt](backend/requirements.txt)** — add `textgrad>=0.1.5` (pin to known version)
- **[backend/app/services/unified_llm_service.py](backend/app/services/unified_llm_service.py:852)** — after `await tracker.complete_call(...)` and before `return response`:
  - Skip if `_source in LLM_EXEMPT_SOURCES`, response<50 chars, response empty
  - `asyncio.create_task(_critique_and_persist(call_id, prompt, response.content, task_type, _source, _sprint_task_id))`
  - Wrap task in `add_done_callback` that logs+swallows exceptions (never propagate)
  - If `TEXTGRAD_MODE=sync`, await the task and stamp `response.improvement = result.model_dump()`
- **[backend/app/services/llm_clients/base.py:29](backend/app/services/llm_clients/base.py)** — extend `LLMResponse` dataclass with `improvement: Optional[dict] = None`
- **[backend/app/services/llm_call_tracker.py](backend/app/services/llm_call_tracker.py)** — `update_call_improvement` gets new `severity` parameter; extend in-memory ring buffer; conditional UPDATE: only write if `suggested_improvement IS NULL` OR `improvement_source='textgrad'`
- **[backend/app/api/endpoints/llm_console.py](backend/app/api/endpoints/llm_console.py)** — implement `mode="textgrad"` in `POST /critique`. Add `GET /textgrad/stats` returning `{critiques_24h, avg_score, severity_breakdown, skipped_reasons, daily_budget_remaining_usd}`
- **[frontend/src/pages/LLMConsole.tsx](frontend/src/pages/LLMConsole.tsx)** — CallRow: red left border if `improvement_severity="critical"`. Header: 6th card "TextGrad Budget". Detail dialog: show both evaluator + textgrad suggestions when present, labeled by `improvement_source`.

## DB migration
- **`029_add_textgrad_severity_column.py`** — revises `028`. Adds `improvement_severity String(20) NULL` to `llm_call_details`.

## Existing functions to reuse
- `unified_llm_service.py:899` `execute_structured()` — TextGrad uses this for Pydantic-validated MiniMax calls
- `unified_llm_service._minimax_balance_exhausted` (class attr) — short-circuit check
- `llm_call_tracker.update_call_improvement` from Learn-14
- `LLM_EXEMPT_SOURCES` — already includes `textgrad_critic` from Learn-14
- `metrics_service.py` — Prometheus counter registration pattern

## Cost / risk
- **MiniMax**: doubles call volume on non-exempt sources. Mandatory env-var guards:
  - `TEXTGRAD_SAMPLE_RATE` default `0.2` (ramp to 1.0 after 48h clean data)
  - `TEXTGRAD_DAILY_BUDGET_USD` default `5.00`, class-level counter, reset at UTC midnight
  - Hard latch on `_minimax_balance_exhausted` for process lifetime
- **Latency**: zero on caller path (fire-and-forget). `TEXTGRAD_MODE=sync` adds 3-8s per call.
- **Blast radius**: high if outermost try/except missing — task crash must NEVER propagate (use `add_done_callback` swallowing pattern)
- **Race**: Learn-14 evaluator may have already written suggestion. Conditional UPDATE prevents clobber unless source is also textgrad.

## Verification
```bash
docker exec legion-backend python -c "import textgrad; print(textgrad.__version__)"
curl -s http://localhost:8005/metrics | grep legion_textgrad

curl -s -X POST http://localhost:8005/llm/execute \
  -H "Content-Type: application/json" \
  -d '{"prompt":"Write FizzBuzz","task_type":"general","_source":"verification_textgrad"}'
sleep 10
docker exec legion-db psql -U legion -d legion -c \
  "SELECT call_id, improvement_source, improvement_score, LEFT(suggested_improvement,100) FROM llm_call_details ORDER BY id DESC LIMIT 1;"

# Budget cap
TEXTGRAD_DAILY_BUDGET_USD=0.01 docker-compose restart legion-backend
# Trigger calls, verify legion_textgrad_skipped_total{reason="budget"} increments

curl -s http://localhost:8005/llm-console/textgrad/stats | python -m json.tool
```

## Acceptance criteria
1. `textgrad` importable in container
2. ≥60% of non-exempt completed calls have `improvement_source='textgrad'` populated within 2h (with `SAMPLE_RATE=1.0`)
3. `/textgrad/stats` shows non-zero `critiques_24h` and positive `daily_budget_remaining_usd`
4. MiniMax breaker NOT tripped (`/llm/health` shows closed)
5. `/ai/suggest` p95 latency unchanged (Grafana before/after, ≤5% delta)
6. Sprint 2871 metrics still achievable
7. `TEXTGRAD_MODE=sync`: a curl returns `LLMResponse` with non-null `.improvement`
8. Prometheus shows `legion_textgrad_critiques_total{severity="critical"} > 0` after 24h real traffic

---

# Learn-16: DSPy + GEPA — Nightly Reflective Evolution

## Goal
Auto-evolve top-5 highest-volume `PromptTemplateDB` rows nightly using DSPy/GEPA against the last 14 days of sprint outcomes. New versions saved as canary (`canary_traffic_pct=10`).

## Files to create
- **[backend/app/services/dspy_optimizer_service.py](backend/app/services/dspy_optimizer_service.py)** — `DSPyOptimizerService.compile_template(template_id, train_window_days=14) → OptimizerResult`. Steps:
  1. Load `PromptTemplateDB` row
  2. Fetch training: last 14d `llm_call_details WHERE prompt_template_id=X AND review_score IS NOT NULL`, joined with `sprint_grades`
  3. Abort if <20 examples (`"insufficient_data"`)
  4. Build `dspy.Signature` from template's `system_prompt`
  5. Configure `dspy.LM` with MiniMax via OpenAI-compatible shim (~30 LOC wrapper)
  6. Metric: `(example.sprint_grade or 0) / 100.0`
  7. `teleprompter = dspy.GEPA(metric=metric, auto="medium")`
  8. `optimized = teleprompter.compile(student=module, trainset=train)`
  9. Return `OptimizerResult(new_system_prompt, rationale, estimated_delta, train_size)`
- **[backend/app/services/dspy_evolution_daemon.py](backend/app/services/dspy_evolution_daemon.py)** — nightly 03:00 UTC, gated by `ENABLE_DSPY_EVOLUTION=false` default. Each cycle: top-N templates, eligibility check (`updated_at<now-48h`, quality drop ≥5pts OR usage≥100, not already canary), call `compile_template()`, create new `PromptTemplateDB` version with `is_active=False, canary_eligible=True, canary_traffic_pct=10, evolved_by="dspy"`, log to `sprint_learnings`, emit `legion_dspy_evolutions_total{status}`.

## Files to modify
- **[backend/requirements.txt](backend/requirements.txt)** — add `dspy-ai>=2.5.0`
- **[backend/app/models/prompt_manager.py](backend/app/models/prompt_manager.py)** — add to `PromptTemplateDB`: `canary_eligible Boolean default False`, `canary_traffic_pct Integer default 0`, `evolved_by String(30) NULL`, `evolution_metadata JSON NULL`. Extend `to_dict()`.
- **[backend/app/services/prompt_manager_service.py:282](backend/app/services/prompt_manager_service.py)** — `get_template_for_task_type()`: if canary version exists with `canary_traffic_pct>0`, use `random.random()*100 < canary_traffic_pct` to decide. Log A/B choice.
- Add `async def promote_canary(template_id)` — parent `is_active=False`, canary `is_active=True, canary_traffic_pct=0`
- Add `async def rollback_canary(template_id)` — set canary `canary_traffic_pct=0, is_active=False`, restore parent
- **[backend/app/api/endpoints/prompt_manager.py](backend/app/api/endpoints/prompt_manager.py)** — `POST /templates/{id}/promote`, `POST /templates/{id}/rollback`, `GET /templates/canary`, `POST /templates/{id}/compile` (admin, rate-limited)
- **[backend/main.py](backend/main.py)** — register `dspy_evolution_daemon` as supervised task `kind="daemon"` gated by `ENABLE_DSPY_EVOLUTION`
- **[docker-compose.yml](docker-compose.yml)** — add `ENABLE_DSPY_EVOLUTION: ${ENABLE_DSPY_EVOLUTION:-false}`
- **[frontend/src/pages/LLMConsole.tsx](frontend/src/pages/LLMConsole.tsx)** — new "Canary Templates" section: list canaries with parent version, A/B metrics, Promote/Rollback buttons

## DB migration
- **`030_add_prompt_template_canary_fields.py`** — revises `029`. Adds 4 columns + index `WHERE canary_traffic_pct > 0`.

## Existing functions to reuse
- `prompt_manager_service.py:171` `update_template()` — versioning primitive; reuse then set canary fields
- `prompt_manager_service.py:240` `revert_template()` — rollback foundation
- `sprint_quality_grader.py` — sprint_grade query pattern for metric function
- `unified_llm_service.execute_structured()` — DSPy LM wrapper routes through here
- `task_health_registry.register(kind="daemon")`
- `metrics_service.py` — Prometheus pattern

## Cost / risk
- **MiniMax**: GEPA expensive (50-200 calls per compile). 5 templates × nightly = 250-1000 calls/night, ~$3-10. Guards:
  - `DSPY_MAX_TEMPLATES_PER_CYCLE` default `2` (ramp later)
  - `DSPY_MAX_CALLS_PER_COMPILE` default `100` (passed as `max_bootstrapped_demos`)
  - `DSPY_DAILY_SPEND_CAP_USD` default `10`
  - Skip if MiniMax breaker tripped in last 24h
- **Latency**: zero live; canary routing adds ~1ms
- **Blast radius**: bounded — bad GEPA output affects only canary 10% slice; Learn-17 catches it
- **Data quality**: require 30%+ high-grade examples in training set or abort `"unbalanced_data"`
- **Custom shim**: DSPy expects OpenAI-compatible `dspy.LM`; Legion's MiniMax client is custom — write 30-line wrapper in optimizer service

## Verification
```bash
docker exec legion-backend python -c "import dspy; print(dspy.__version__)"
docker exec legion-db psql -U legion -d legion -c "\d prompt_templates" | grep canary_traffic_pct

ENABLE_DSPY_EVOLUTION=true docker-compose up -d legion-backend
docker logs legion-backend --tail 100 2>&1 | grep -i dspy

curl -s -X POST http://localhost:8005/prompt-manager/templates/1/compile | python -m json.tool

# Canary routing
docker exec legion-db psql -U legion -d legion -c \
  "UPDATE prompt_templates SET canary_eligible=true, canary_traffic_pct=50 WHERE id=N;"
# Trigger 100 calls, count canary uses ~50

curl -s http://localhost:8005/metrics | grep legion_dspy_evolutions_total
curl -s -X POST http://localhost:8005/prompt-manager/templates/N/promote
curl -s -X POST http://localhost:8005/prompt-manager/templates/N/rollback
```

## Acceptance criteria
1. DSPy/GEPA imports work in container
2. `/templates/{id}/compile` produces new row with `evolved_by='dspy', canary_traffic_pct=10`
3. Canary routing: 1000 reqs → 80-120 use canary (10% ±20%)
4. Nightly daemon respects `DSPY_MAX_TEMPLATES_PER_CYCLE`
5. 24h DSPy spend ≤ `DSPY_DAILY_SPEND_CAP_USD`
6. Sprint 2871 metrics not regressed
7. Promote + rollback idempotent
8. `ENABLE_DSPY_EVOLUTION=false` → no daemon logs

---

# Learn-17: Closed-loop Verification + Auto-rollback

## Goal
Measure whether improvements actually help. For each `PromptImprovementDB` in `applied` state and each canary template, compare next-50 calls to previous-50 on `review_score`. If statistically negative, auto-rollback via `revert_template()`. Surface in new "Improvement Tracker" tab.

## Files to create
- **[backend/app/services/feedback_loop_verifier.py](backend/app/services/feedback_loop_verifier.py)** — `FeedbackLoopVerifier.verify_improvements()`. Steps:
  1. Find `PromptImprovementDB WHERE status='applied' AND verification_delta IS NULL AND applied_at > now()-7d`
  2. For each: count "after" calls on new template (min 50), "before" calls on parent template (50 immediately preceding `applied_at`)
  3. Compute `delta = avg_review_after - avg_review_before` for review_score, improvement_score, quality_score
  4. `scipy.stats.ttest_ind` p-value
  5. Classify: `verified_positive` if `delta≥5 AND p<0.1 AND consistent across 2 cycles`. `regression` if `delta≤-5 AND p<0.1`. `inconclusive` otherwise.
  6. On regression: call `revert_template()`, set `rolled_back_at`, emit `legion_improvements_rolled_back_total`, dedup max 1/24h per template
  7. On verified_positive: set `verified_positive=true`, emit counter, auto-promote if from canary
  8. Also evaluates Learn-16 canaries via same A/B methodology

## Files to modify
- **[backend/app/models/prompt_manager.py](backend/app/models/prompt_manager.py)** — add to `PromptImprovementDB`: `verified_positive Bool NULL`, `regression Bool NULL`, `verification_delta Float NULL`, `verification_p_value Float NULL`, `verified_at DateTime NULL`, `rolled_back_at DateTime NULL`, `verification_sample_size Integer NULL`. Extend `to_dict()`.
- **[backend/app/services/prompt_evaluator_agent.py:134](backend/app/services/prompt_evaluator_agent.py)** — in `_improvement_cycle()`, after `mgr.auto_apply_improvements()`, call `FeedbackLoopVerifier().verify_improvements()`. Reuses existing 30-min cycle — no new daemon.
- **[backend/app/api/endpoints/prompt_manager.py](backend/app/api/endpoints/prompt_manager.py)** — `GET /improvements/{id}/verification`, `GET /improvements/recent`, `GET /verification/stats` (7-day rolling: positive count, regression count, rollback rate, avg delta)
- **[backend/app/services/metrics_service.py](backend/app/services/metrics_service.py)** — register `legion_improvements_verified_positive_total{source}`, `legion_improvements_rolled_back_total{source}`, histogram `legion_improvements_delta`, gauge `legion_improvements_7d_effectiveness_pct`
- **[docker/prometheus/alert_rules.yml](docker/prometheus/alert_rules.yml)** — alerts: `ImprovementRollbackRateHigh` (rollbacks/total >0.3 over 6h), `ImprovementEffectivenessDropping` (`7d_effectiveness_pct<0.4`)
- **[docker/grafana/dashboards/legion.json](docker/grafana/dashboards/legion.json)** — new "Learning Loop" row: rolling effectiveness gauge, stacked bar (positive/regression/inconclusive per day), top-10 templates by rollback count
- **[frontend/src/hooks/useLLMConsole.ts](frontend/src/hooks/useLLMConsole.ts)** — `useImprovementVerification(id)`, `useRecentImprovements(limit)`, `useVerificationStats()`
- **[frontend/src/pages/LLMConsole.tsx](frontend/src/pages/LLMConsole.tsx)** — new "Improvement Tracker" tab: recent improvements table (timestamp, template, source, status, delta, badge, rollback button) + Canary A/B panel + 7-day mini-chart

## DB migration
- **`031_add_improvement_verification_columns.py`** — revises `030`. Adds 7 columns to `prompt_improvements` + index `(verified_positive, regression, verified_at)`.

## Existing functions to reuse
- `prompt_manager_service.py:240` `revert_template()` — DO NOT rewrite the rollback primitive
- `annotation_queue_service.py:448` `apply_improvement()` — pattern for "apply then commit" transactions
- `prompt_evaluator_agent.py:134` `_improvement_cycle()` — hook the verifier here, no new daemon
- `scipy.stats.ttest_ind` — already in dependency tree (don't add explicit scipy)
- `metrics_service.py` — counter registration pattern
- `sprint_learning_service.record_learning()` — log rollback events

## Cost / risk
- **MiniMax**: zero — verifier reads existing `review_score` / `improvement_score`, no LLM calls
- **Latency**: zero, runs on existing 30-min cycle
- **False-positive rollbacks**: 50-call min, p<0.1, persist across 2 consecutive cycles, 24h cooldown per template
- **Thrashing**: after rollback, improvement enters `"rolled_back"` permanent state; next proposal for same template must come from a DIFFERENT source (`improvement_source != rolled_back_source`) for 7 days
- **Insufficient data**: improvements <7d old with <50 after-calls stay `NULL`, re-checked next cycle

## Verification
```bash
docker exec legion-db psql -U legion -d legion -c "\d prompt_improvements" | grep verified_positive

# Inject deliberately bad improvement
docker exec legion-db psql -U legion -d legion -c "
INSERT INTO prompt_improvements (annotation_id, prompt_template_id, improvement_type, old_value, new_value, rationale, status, applied_at)
VALUES (NULL, 1, 'request_rewrite', 'good prompt', 'BAD PROMPT XYZ', 'test rollback', 'applied', now() - interval '2 hours');"

curl -s -X POST http://localhost:8005/prompt-manager/verification/run | python -m json.tool

docker exec legion-db psql -U legion -d legion -c \
  "SELECT id, status, regression, verification_delta, rolled_back_at FROM prompt_improvements ORDER BY id DESC LIMIT 1;"

curl -s http://localhost:8005/metrics | grep legion_improvements

# Frontend: open http://localhost:3005/llm-console → "Improvement Tracker" tab → see bad improvement with regression badge
```

## Acceptance criteria
1. Migration `031` applied with 7 new columns
2. Verifier runs on existing 30-min `_improvement_cycle` (no new daemon)
3. Bad injected improvement rolled back within 1 cycle (after 50-call minimum met)
4. `/verification/stats` returns non-zero counts within 24h of real traffic
5. "Improvement Tracker" tab renders, shows per-improvement status
6. Prometheus counters increment; Grafana Learning Loop row displays gauge
7. No thrashing: single improvement does NOT oscillate
8. Canaries from Learn-16 with positive delta auto-promote to full traffic
9. Sprint 2871 metrics still achievable

---

## Critical Files (cross-cutting)

- **[backend/app/services/unified_llm_service.py](backend/app/services/unified_llm_service.py)** — central call path; the hinge of the entire roadmap. Learn-14 captures `prompt_template_id`. Learn-15 hooks fire-and-forget critique at line 852.
- **[backend/app/services/llm_call_tracker.py](backend/app/services/llm_call_tracker.py)** — owns write path to `llm_call_details`. Learn-14 adds `update_call_improvement()`. Learn-15 writes through it.
- **[backend/app/services/prompt_evaluator_agent.py](backend/app/services/prompt_evaluator_agent.py)** — already running on 10/30-min cycle. Learn-14 wires direct write. Learn-17 hooks verifier into `_improvement_cycle()`.
- **[backend/app/services/prompt_manager_service.py](backend/app/services/prompt_manager_service.py)** — versioning + canary routing. Learn-16 modifies `get_template_for_task_type()` (line 282). Learn-17 reuses `revert_template()` (line 240).
- **[backend/app/models/llm_call_detail.py](backend/app/models/llm_call_detail.py)** + **[backend/app/models/prompt_manager.py](backend/app/models/prompt_manager.py)** — schema hinges; migrations 028→031 land here.
- **[frontend/src/pages/LLMConsole.tsx](frontend/src/pages/LLMConsole.tsx)** — sole user-facing surface. Every sprint adds a section.

## End-to-end Verification After All 4 Sprints
1. Make a deliberately bad LLM call: `curl -X POST /llm/execute -d '{"prompt":"do stuff","_source":"e2e_test"}'`
2. Within 60s: open LLM Console → see Quality column with red badge for the call
3. Click the call → see TextGrad critique under "Suggested Improvement" with severity="warning" or higher
4. Wait 30 min: PromptEvaluator + verifier cycle runs
5. Check `prompt_improvements` table: a new row should exist for the affected template
6. Wait 24h or run a sprint that triggers ≥50 more calls on that template
7. Run `POST /verification/run`: improvement should be classified `verified_positive` or `regression`
8. If `regression`: confirm `rolled_back_at` populated and template version reverted in DB
9. Check Grafana "Learning Loop" panel: 7-day effectiveness gauge populated
10. Confirm Sprint 2871-style sprint still scores `learning_capture=100, execution_success=100`
