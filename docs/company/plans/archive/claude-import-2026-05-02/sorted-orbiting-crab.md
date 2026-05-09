# Bidirectional Alignment Plan: Legion <-> ADA + Cross-Project Comparison Skill

## Context

Legion and ADA are roughly tied overall (52% vs 55%) but in completely different areas. Phase 1 of the alignment (previous session) completed 7 tasks: dict slice fix, MiniMax M2.7 upgrade, circuit breaker port (ADA->Legion), confidence calibration port (ADA->Legion), post-sync learning extraction, auto_learn enablement, and Prometheus counters. Verification revealed and fixed circuit breaker gaps in 3 of 4 LLM methods and confidence calibration lazy-load.

**This plan covers the remaining 3 goals:**
1. Close remaining Phase 2 gaps (Legion still behind ADA in some areas)
2. Port Legion's advantages TO ADA (DSPy evolution, TextGrad, statistical verification, etc.)
3. Create a reusable cross-project comparison skill (works for any two projects, not just Legion/ADA)

---

## Part A: Close Remaining Legion Gaps (ADA -> Legion)

These are the Phase 2 items from the original comparison where ADA is still ahead.

### A1. Output Guardrails Service (MEDIUM priority)
**What ADA has**: `GuardrailsService` that sanitizes LLM output before returning to callers.
**What Legion needs**: Sanitization layer in `unified_llm_service.py` that strips provider markers, tool_call leakage, and validates output format.

**Files to modify**:
- NEW: `backend/app/services/output_guardrails.py` (~120 lines)
  - `sanitize_llm_output(text, provider) -> str` — strip `<minimax:tool_call>`, `<tool_call>`, orphan XML tags
  - `validate_structured_output(text, schema) -> bool` — check JSON parseable if schema expected
  - Reuse existing `_sanitize_review_text()` pattern from [llm_review_service.py](backend/app/services/llm_review_service.py)
- MODIFY: [unified_llm_service.py](backend/app/services/unified_llm_service.py) — call `sanitize_llm_output()` on response content before returning in `execute()`, `execute_with_tools()`, `chat()`

### A2. Per-Agent Performance Tracking (LOW priority)
**What ADA has**: `AgentLearningSystem` in [agent_learning.py](C:/code/ADA/backend/infrastructure/agent_learning.py) — tracks per-agent predictions vs outcomes, accuracy, precision, recall.
**What Legion has**: `LearningAggregator.record_task_outcome()` with `model_name=f"agent:{agent.name}"` but no per-agent dashboard.

**Files to modify**:
- MODIFY: [agent_swarm_service.py](backend/app/services/agent_swarm_service.py) — after task completion, record agent-specific metrics (which agent type succeeded/failed, latency per agent)
- MODIFY: [metrics_service.py](backend/app/services/metrics_service.py) — add `legion_agent_task_outcome_total{agent_name, result}` counter
- MODIFY: [learning_engine.py](backend/app/services/learning_engine.py) — `get_agent_performance(agent_name)` query method

### A3. Prediction Tracking (LOW priority)
**What ADA has**: `agent_predictions` table — prediction + outcome pairs with error tracking.
**What Legion has**: Nothing equivalent.

**Defer to future sprint** — Legion's sprint system doesn't make explicit predictions the way trading agents do. If needed, model as an extension to `confidence_calibration.py` where we track per-task predicted_difficulty vs actual_difficulty.

### A4. Streaming LLM (LOW priority)
**What ADA has**: Both blocking + SSE streaming APIs in `llm_router.py`.
**What Legion has**: `execute_stream()` method exists but is never called by any consumer.

**Defer** — No current consumer needs streaming. When Builder-05 (Chat Iteration) ships, streaming will be needed for live preview.

### A5. RAG/Agentic RAG (MEDIUM priority, defer to Learn-21)
**What ADA has**: 7 TTL-aware Qdrant collections, agentic RAG, adaptive retrieval.
**What Legion has**: Basic Qdrant episodic memory with rare retrieval.

**Already planned** as Learn-21 in the roadmap. Not included in this sprint.

---

## Part B: Port Legion Advantages TO ADA (Legion -> ADA)

These are features where Legion is ahead and ADA should benefit.

### B1. Prompt Evolution with GEPA (HIGH priority)
**What Legion has**: [dspy_optimizer_service.py](backend/app/services/dspy_optimizer_service.py) — GEPA reflective prompt rewriting via structured LLM output. Creates canary variants at configurable traffic %, gated by `ENABLE_DSPY_EVOLUTION` env var.
**What ADA has**: [prompt_optimizer.py](C:/code/ADA/backend/services/learning/prompt_optimizer.py) — basic `PromptRegistry` + `PromptOptimizerAgent` with simple score-based promotion.

**Files to create in ADA**:
- NEW: `C:/code/ADA/backend/services/learning/prompt_evolution.py` (~300 lines)
  - Port the GEPA pattern: collect good/bad examples from recent calls, ask LLM to rewrite system prompt, persist as canary version
  - Use ADA's existing `PromptRegistry.add_version()` for storage
  - Add canary traffic % to `PromptVersion` dataclass
  - Gate behind `ENABLE_PROMPT_EVOLUTION=false` env var
  - Use ADA's `get_llm_client()` for the rewrite call (not Legion's `execute_structured`)
- MODIFY: `C:/code/ADA/backend/services/learning/prompt_optimizer.py` — integrate GEPA as a second optimization strategy alongside the existing simple optimizer

### B2. TextGrad Per-Call Critique (HIGH priority)
**What Legion has**: [textgrad_service.py](backend/app/services/textgrad_service.py) — fire-and-forget natural language gradient on every non-exempt LLM call. Persists `suggested_improvement` and `improvement_score` per call.
**What ADA has**: Nothing equivalent.

**Files to create in ADA**:
- NEW: `C:/code/ADA/backend/services/learning/textgrad_critique.py` (~200 lines)
  - Port fire-and-forget pattern: after each LLM call, spawn async task to critique the output
  - Persist critique to ADA's existing call tracking (add `suggested_improvement` column if not exists)
  - Budget cap ($2/day) to prevent runaway critique costs
  - Exempt list: `textgrad_critic`, `prompt_evolution`, `feedback_verifier`
- MODIFY: `C:/code/ADA/backend/infrastructure/llm_router.py` — add fire-and-forget hook after `_post_completion()` to trigger critique

### B3. Statistical Verification + Auto-Rollback (HIGH priority)
**What Legion has**: [feedback_loop_verifier.py](backend/app/services/feedback_loop_verifier.py) — Welch's t-test comparing before/after review scores, auto-promote on positive delta > 5.0 with p < 0.1, auto-rollback on regression.
**What ADA has**: Simple score comparison with fixed threshold in `PromptOptimizerAgent`.

**Files to create in ADA**:
- NEW: `C:/code/ADA/backend/services/learning/feedback_verifier.py` (~250 lines)
  - Port Welch's t-test comparison logic
  - 4 gates: MIN_SAMPLE_SIZE=50, DELTA_THRESHOLD=5.0, P_VALUE_THRESHOLD=0.1, ROLLBACK_COOLDOWN_HOURS=24
  - Pure-Python fallback if scipy unavailable
  - Hooks into ADA's existing daemon cycle (runs after prompt optimizer cycle)
  - Auto-promotes/rollbacks via `PromptRegistry` methods

### B4. Sprint/Session Quality Grading (MEDIUM priority)
**What Legion has**: 7-dimension sprint quality grading (execution, decomposition, routing, learning, QA, prompt, time) in [sprint_quality_grader.py](backend/app/services/sprint_quality_grader.py).
**What ADA has**: Basic completion tracking only.

**Files to create in ADA**:
- NEW: `C:/code/ADA/backend/services/learning/session_grader.py` (~200 lines)
  - Adapted grading for trading sessions (not sprints): trade_execution_quality, signal_accuracy, risk_management, learning_capture, timing_efficiency
  - Persist to new `ada_session_grades` table (or reuse existing table with JSON dimensions column)
  - Hook into ADA's session completion flow

### B5. Reasoning Capture (MEDIUM priority)
**What Legion has**: [reasoning_capture.py](backend/app/api/endpoints/reasoning.py) — 6 tables persisting brain decisions, RCA clusters, self-improvement cycles, quality grades, health findings, work discovery runs. Unified timeline API.
**What ADA has**: Structured logging only — reasoning is ephemeral.

**Files to create in ADA**:
- NEW: `C:/code/ADA/backend/services/learning/reasoning_capture.py` (~200 lines)
  - `persist_decision(kind, data)` — unified write to `ada_reasoning_events` table
  - Kinds: `trade_decision`, `risk_assessment`, `agent_reflection`, `health_finding`, `portfolio_rebalance`
  - Try/except wrapper so capture failure never blocks trading
- NEW: `C:/code/ADA/backend/api/reasoning.py` — timeline + detail endpoints
- NEW migration: `ada_reasoning_events` table (kind, data JSONB, created_at, agent_id)

### B6. Provider Override / Canary Routing (HIGH priority)
**What Legion has**: Per-source provider routing with canary traffic % (Learn-18/19). Prometheus tracked. Lets specific sources (e.g., `prompt_evaluator`) route 10% to Ollama while everything else stays on MiniMax.
**What ADA has**: Simple fallback chain (MiniMax -> Ollama -> fallback).

**Files to modify in ADA**:
- MODIFY: `C:/code/ADA/backend/infrastructure/llm_router.py` — add `provider_override` lookup before routing. Pattern: check `ada_provider_overrides` table for source/task_type match, dice roll against `canary_traffic_pct`, force provider if hit
- NEW: DB table `ada_provider_overrides` (source_filter, task_type, provider_override, canary_traffic_pct, is_active)
- Add API endpoints for managing overrides

### B7. Hunter Anomaly Detection (MEDIUM priority)
**What Legion has**: Hunter change-point detection running every 5 minutes, detecting anomalies in metric time series.
**What ADA has**: Basic Prometheus (optional) + structured logging. No anomaly detection.

**Defer to future sprint** — ADA's observability stack needs to be more mature first. Port after B1-B3 are verified.

---

## Part C: Cross-Project Comparison Skill

Create a reusable skill that compares ANY two projects bidirectionally, identifies gaps, suggests improvements, and tracks alignment over time. Applicable to Legion/ADA, Legion/FortressOS, or any future projects.

### Skill: `legion-cross-project-auditor`

**Location**: `C:/code/Legion/.claude/skills/legion-cross-project-auditor/`

**Structure**:
```
legion-cross-project-auditor/
  SKILL.md                          # Skill definition + execution instructions
  knowledge/
    comparison_history.json          # Timestamped comparison results
    alignment_registry.json          # Per-pair alignment scores + trends
    port_candidates.json             # Features identified for porting (bidirectional)
    improvement_patterns.md          # Patterns learned from successful ports
```

**SKILL.md** will define:
- **Triggers**: `compare projects`, `cross-project audit`, `alignment check`, `project comparison`
- **Parameters**: `--project-a <path>` `--project-b <path>` (defaults to Legion + ADA)
- **Execution phases**:
  1. **Discover**: Scan both codebases for capabilities (LLM layer, learning, agents, observability, resilience, testing)
  2. **Compare**: Score each capability 0-10 per project across 8 dimensions
  3. **Gap Analysis**: Identify where A > B and B > A
  4. **Port Candidates**: For each gap, assess effort (S/M/L) and impact (LOW/MEDIUM/HIGH)
  5. **Report**: Generate comparison table + recommended port actions
  6. **Update Knowledge**: Persist results for trend tracking

**Comparison dimensions** (8):
1. LLM Service Layer (routing, resilience, structured output, streaming, cost tracking)
2. Learning System (episodic memory, calibration, cross-project, prediction tracking)
3. Prompt Management (versioning, A/B testing, evolution, verification)
4. Quality Review (per-call critique, review daemons, auto-fix escalation)
5. Agent Architecture (framework maturity, routing, per-agent tracking)
6. Observability (metrics, tracing, anomaly detection, dashboards)
7. Knowledge/RAG (vector store, ingestion, retrieval pipeline)
8. Self-Improvement (reasoning capture, auto-grading, feedback loops)

**Reusable for other projects**: The skill takes project paths as parameters. For a new project pair (e.g., Legion/FortressOS), it auto-discovers capabilities by scanning for known patterns (Prometheus setup, LLM client files, learning service dirs, agent registries, etc.)

---

## Execution Order

### Sprint 1: Cross-Project Skill + ADA High-Priority Ports (THIS SPRINT)

| # | Task | Target | Effort | Files |
|---|------|--------|--------|-------|
| 1 | Create `legion-cross-project-auditor` skill | Legion | M | NEW skill dir + SKILL.md + 4 knowledge files |
| 2 | Output guardrails service (A1) | Legion | S | NEW guardrails.py + MODIFY unified_llm_service.py |
| 3 | Port GEPA prompt evolution to ADA (B1) | ADA | L | NEW prompt_evolution.py + MODIFY prompt_optimizer.py |
| 4 | Port TextGrad critique to ADA (B2) | ADA | M | NEW textgrad_critique.py + MODIFY llm_router.py |
| 5 | Port feedback verifier to ADA (B3) | ADA | M | NEW feedback_verifier.py |
| 6 | Port provider override routing to ADA (B6) | ADA | L | MODIFY llm_router.py + NEW DB table + NEW API |

### Sprint 2: Remaining Alignment Items (THIS SPRINT)

**Execution order** — Phase 1 (independent, parallel): B5 + A2. Phase 2 (parallel): B4 + B7. Phase 3 (largest scope): A5.

| # | Task | Target | Effort | New Files | Modified Files |
|---|------|--------|--------|-----------|----------------|
| 7 | Reasoning capture (B5) | ADA | M | 3 new (model, service, router) | 4 modified (models/__init__, migrations, main, outcome_tracker) |
| 8 | Per-agent performance tracking (A2) | Legion | S | 1 new (endpoint) | 3 modified (metrics_service, agent_swarm, router_registry) |
| 9 | Session quality grading (B4) | ADA | M | 2 new (model, service) | 3 modified (models/__init__, migrations, learning router) |
| 10 | Hunter anomaly detection (B7) | ADA | L | 3 new (model, service, router) | 3 modified (models/__init__, migrations, main) |
| 11 | RAG overhaul (A5) | Legion | L | 1 new (endpoint) | 5 modified (rag_service, episodic_memory, knowledge_ingestion, learning_engine, main) |

---

## Sprint 2 Implementation Details

### Task 7 (B5): Reasoning Capture for ADA

**Context**: ADA's trading decisions, risk assessments, and agent reflections are ephemeral (logs only). Port Legion's 6-table reasoning capture as a single-table JSONB pattern adapted for trading.

**New files**:

**`C:/code/ADA/backend/infrastructure/models/reasoning_event.py`** (~45 lines)
- `ReasoningEvent(Base, TimestampMixin, IntegerPrimaryKeyMixin)` — auto-named `reasoning_events`
- Columns: `kind` (String 50, indexed), `data` (JSONB), `agent_id` (String 100, nullable), `session_id` (String 100, nullable), `severity` (String 20, default "info")
- Follow pattern from [base.py](C:/code/ADA/backend/infrastructure/models/base.py): `Mapped[]` + `mapped_column()`

**`C:/code/ADA/backend/services/learning/reasoning_capture.py`** (~120 lines)
- `ReasoningCaptureService` with 3 methods:
  - `persist_decision(kind, data, agent_id, session_id, severity)` → try/except, NEVER raises
  - `get_timeline(kinds, limit, since)` → SELECT ORDER BY created_at DESC
  - `get_event(event_id)` → single row detail
- Uses `get_async_session()` from ADA's `sqlalchemy_config` (NOT Legion's `AsyncSessionLocal`)
- Gated by `ENABLE_REASONING_CAPTURE=false` env var

**`C:/code/ADA/backend/routers/reasoning.py`** (~50 lines)
- `GET /api/reasoning/timeline` — kinds as comma-separated query param
- `GET /api/reasoning/events/{event_id}` — single event detail

**Modified files**:
- `C:/code/ADA/backend/infrastructure/models/__init__.py` — add `ReasoningEvent` import + `__all__`
- `C:/code/ADA/backend/infrastructure/database_migrations.py` — add `reasoning_events` table (CREATE TABLE IF NOT EXISTS + 2 indexes)
- `C:/code/ADA/backend/main.py` — import + register reasoning router
- `C:/code/ADA/backend/services/outcome_tracker.py` — wire `persist_decision(kind="trade_decision")` in `record_recommendation()`
- `C:/code/ADA/backend/infrastructure/agent_learning.py` — wire `persist_decision(kind="agent_reflection")` in `record_outcome()`

---

### Task 8 (A2): Per-Agent Performance Tracking for Legion

**Context**: Legion records `model_name=f"agent:{agent.name}"` in `record_task_outcome()` but has no Prometheus counter, API endpoint, or dashboard for per-agent metrics.

**Modified files**:

**[metrics_service.py](backend/app/services/metrics_service.py)** (~5 lines)
- Add `agent_task_outcome_total` Counter with labels `{agent_name, result}` (result = completed/failed/skipped) in `MetricsService.__init__`

**[agent_swarm_service.py](backend/app/services/agent_swarm_service.py)** (~12 lines)
- At task completion path (advance_task_node success): `_metrics.agent_task_outcome_total.labels(agent_name=..., result="completed").inc()`
- At task failure path: same with `result="failed"`
- Agent name from `state.get("next_agent", "unknown")` or deterministic node name ("coder", "reviewer", "tester")
- Wrap in try/except so counter failure never breaks the swarm

**New files**:

**`backend/app/api/endpoints/agent_performance.py`** (~90 lines)
- `GET /api/agents/performance` — aggregate from `llm_call_details WHERE source LIKE 'agent:%'`: total_calls, avg_review_score, avg_latency_ms per agent. Query param `days` (default 7)
- `GET /api/agents/performance/{agent_name}` — single agent detail with daily trend
- Uses existing `LLMCallDetailDB` model — NO new tables
- Route note: prefix is `/agents/performance` so `{agent_name}` is safe (no literal/param collision)

**Modified files**:
- [router_registry.py](backend/app/api/router_registry.py) — import + register `agent_performance` router

---

### Task 9 (B4): Session Quality Grading for ADA

**Context**: Port Legion's 10-dimension [sprint_quality_grader.py](backend/app/services/sprint_quality_grader.py) (1042 lines) as a 5-dimension trading session grader. Session = one trading day (date-based).

**New files**:

**`C:/code/ADA/backend/infrastructure/models/session_grade.py`** (~50 lines)
- `SessionGrade(Base, TimestampMixin, IntegerPrimaryKeyMixin)` — auto-named `session_grades`
- Columns: `session_date` (Date, unique), `overall_score` (Float), `dimensions` (JSONB), `metadata_` (mapped to "metadata" column, JSONB), `trade_count` (Integer), `graded_at` (DateTime)

**`C:/code/ADA/backend/services/learning/session_grader.py`** (~250 lines)
- `SessionQualityGrade` dataclass with `set_dimension()`, `compute_overall()` (same pattern as Legion's grader)
- 5 dimensions with weights:
  1. `signal_accuracy` (25%) — win_count / total_resolved from recommendation_outcomes
  2. `risk_management` (25%) — max drawdown %, position sizing adherence
  3. `execution_quality` (20%) — fill quality, slippage from paper_trades
  4. `capital_efficiency` (15%) — total PnL / capital at risk
  5. `learning_capture` (15%) — IterationTracker improvements recorded
- `SessionGrader.grade_session(session_date)` — queries existing tables, scores, persists via UPSERT
- `_persist_grade()` — INSERT ON CONFLICT (session_date) DO UPDATE
- Emits reasoning event (`kind="session_grade"`) if B5 is wired
- Gated by `ENABLE_SESSION_GRADING=false`
- `_jsonable()` helper to coerce Decimal→float before JSONB (lesson from Observe-03)

**Modified files**:
- `C:/code/ADA/backend/infrastructure/models/__init__.py` — add `SessionGrade`
- `C:/code/ADA/backend/infrastructure/database_migrations.py` — add `session_grades` table + index on session_date
- `C:/code/ADA/backend/routers/learning.py` — add 2 endpoints:
  - `GET /api/learning/session-grades` (list, param `days`)
  - `GET /api/learning/session-grades/{session_date}` (detail)

---

### Task 10 (B7): Hunter Anomaly Detection for ADA

**Context**: Port Legion's [change_point_detector.py](backend/app/services/change_point_detector.py) (486 lines, simplified E-Divisive Means) adapted for trading metrics. Background daemon every 5 minutes.

**New files**:

**`C:/code/ADA/backend/infrastructure/models/anomaly_event.py`** (~40 lines)
- `AnomalyEvent(Base, TimestampMixin, IntegerPrimaryKeyMixin)` — auto-named `anomaly_events`
- Columns: `metric_name` (String 100, indexed), `change_point_at` (DateTime), `magnitude` (Float), `direction` (String 20: "increase"/"decrease"), `window_before` (JSONB), `window_after` (JSONB), `dedup_key` (String 100, unique partial index)

**`C:/code/ADA/backend/services/anomaly_detector.py`** (~350 lines)
- Port the simplified E-Divisive Means algorithm (pure Python, no numpy)
- 4 trading-relevant metrics:
  1. Trade execution latency p95 (from paper_trades or execution logs)
  2. Trade success rate — win/loss ratio over rolling window (from recommendation_outcomes)
  3. Risk escalation frequency — how often max position limits are hit (from error_logs)
  4. Session PnL regression — negative trend detection (from recommendation_outcomes)
- Each check: compare recent 1h window vs 24h baseline, detect magnitude > threshold
- `_persist_anomaly()` with 24h dedup via `dedup_key = f"{metric}:{date}"`
- `_sanitize_for_json()` helper (Decimal→float, same lesson as Observe-03)
- `anomaly_detection_loop()` — background daemon, 5-min cycle
- Gated by `ENABLE_ANOMALY_DETECTION=false`

**`C:/code/ADA/backend/routers/anomaly.py`** (~40 lines)
- `GET /api/anomalies` — recent events, param `days` + `limit`
- `GET /api/anomalies/{event_id}` — single event detail

**Modified files**:
- `C:/code/ADA/backend/infrastructure/models/__init__.py` — add `AnomalyEvent`
- `C:/code/ADA/backend/infrastructure/database_migrations.py` — add `anomaly_events` table + 3 indexes (metric_name, change_point_at DESC, unique dedup_key)
- `C:/code/ADA/backend/main.py` — import + register anomaly router + daemon registration in GROUP 3 (Optional) startup section using existing `resilient_task_wrapper` pattern

---

### Task 11 (A5): RAG Overhaul for Legion

**Context**: Episodic memory works (store/retrieve/inject). Knowledge ingestion has schema but no daemon. Qdrant container running but dormant (no indexing/retrieval). Need: (1) activate Qdrant indexing, (2) knowledge ingestion daemon, (3) wire RAG search into learning engine.

**Embedding strategy**: 3-tier fallback — Ollama embed API (`all-minilm`, 384-dim) → SentenceTransformer (already in rag_service.py, 384-dim) → hash-based dummy (384-dim). All produce 384-dim vectors matching existing `EMBEDDING_DIM` constant.

**Modified files**:

**[rag_service.py](backend/app/services/rag_service.py)** (~100 lines added)
- Add `_get_ollama_embedding(text)` — calls `POST {OLLAMA_URL}/api/embed` with `model=all-minilm`
- Add `_get_embedding_async(text)` — 3-tier fallback: Ollama → SentenceTransformer → hash
- Add `index_episode(episode_id, task_type, prompt, output)` — embed + upsert to Qdrant `sprint_history` collection
- Add `index_knowledge(knowledge_id, domain, title, summary)` — embed + upsert to Qdrant `documentation` collection
- Add `search(query, collection, top_k)` → `list[SearchResult]` — vector search

**[episodic_memory_service.py](backend/app/services/episodic_memory_service.py)** (~8 lines)
- After `store_episode()` success: call `rag.index_episode()` wrapped in try/except
- Gated by `ENABLE_RAG_SEARCH=false`

**[knowledge_ingestion_service.py](backend/app/services/knowledge_ingestion_service.py)** (~30 lines)
- Add `_ingest_cycle()` — scan configured dirs (backend/app/services/*.py, frontend/src/*.ts), chunk into 500-token segments, store in knowledge_sources, index in Qdrant
- Add `knowledge_ingestion_loop()` — 6-hour cycle daemon
- Cap: 500 files per cycle, 0.5s throttle per file, skip unchanged files (mtime check)
- Gated by `ENABLE_KNOWLEDGE_DAEMON=false`

**[learning_engine.py](backend/app/services/learning_engine.py)** (~20 lines)
- Add source #7 (RAG vector search) after existing source #5 in `enrich_task_context()`
- Query: `rag.search(f"{task_type}: {prompt[:200]}", collection="sprint_history", top_k=3)`
- Format results as context block, increment `LEARNING_ENGINE_SOURCES_INJECTED.labels(source="rag_search")`
- Gated by `ENABLE_RAG_SEARCH=false`

**[main.py](backend/main.py)** (~6 lines)
- Register knowledge daemon using existing `_supervised_task` pattern, gated by `ENABLE_KNOWLEDGE_DAEMON`

**New files**:

**`backend/app/api/endpoints/knowledge_search.py`** (~40 lines)
- `GET /api/knowledge/search?q=...&top_k=5` — manual vector search across documentation collection
- Returns empty `{"results": []}` when `ENABLE_RAG_SEARCH=false`

**Modified files**:
- [router_registry.py](backend/app/api/router_registry.py) — register `knowledge_search` router

---

## Sprint 2 Key Files Reference

### Legion sources (to port)
- [sprint_quality_grader.py](backend/app/services/sprint_quality_grader.py) — 10-dimension weighted grading pattern (for B4)
- [change_point_detector.py](backend/app/services/change_point_detector.py) — E-Divisive Means algorithm (for B7)
- [rag_service.py](backend/app/services/rag_service.py) — AgenticRAGService skeleton to activate (for A5)
- [learning_engine.py](backend/app/services/learning_engine.py) — `enrich_task_context()` injection point (for A5)
- [episodic_memory_service.py](backend/app/services/episodic_memory_service.py) — `store_episode()` hook point (for A5)
- [metrics_service.py](backend/app/services/metrics_service.py) — Counter creation pattern (for A2)

### ADA targets
- [base.py](C:/code/ADA/backend/infrastructure/models/base.py) — Base + TimestampMixin + IntegerPrimaryKeyMixin (model pattern for B4/B5/B7)
- [database_migrations.py](C:/code/ADA/backend/infrastructure/database_migrations.py) — idempotent migration pattern
- [main.py](C:/code/ADA/backend/main.py) — lifespan daemon registration + router include
- [outcome_tracker.py](C:/code/ADA/backend/services/outcome_tracker.py) — wire point for reasoning capture
- [agent_learning.py](C:/code/ADA/backend/infrastructure/agent_learning.py) — wire point for reasoning capture

---

## Verification

### After Sprint 1 completion (DONE):

1. **Cross-project skill**: `/legion-cross-project-auditor` — DONE, produces 8-dimension comparison
2. **Output guardrails**: `legion_guardrail_strips_total` Prometheus counter active — DONE
3. **GEPA in ADA**: `prompt_evolution.py` created, gated OFF — DONE
4. **TextGrad in ADA**: `textgrad_critique.py` created, gated OFF — DONE
5. **Feedback verifier in ADA**: `feedback_verifier.py` created — DONE
6. **Provider override in ADA**: `ProviderOverride` dataclass + management methods in llm_router.py — DONE

### After Sprint 2 completion:

**B5 — Reasoning Capture (ADA)**:
1. Migration runs: `SELECT * FROM reasoning_events LIMIT 1;` returns empty (no error)
2. `GET http://localhost:8000/api/reasoning/timeline` → `[]` (200 OK)
3. Insert test row via docker exec → re-query timeline → row appears
4. Set `ENABLE_REASONING_CAPTURE=true`, trigger a recommendation → verify `kind=trade_decision` row

**A2 — Per-Agent Performance (Legion)**:
1. `GET http://localhost:8005/api/agents/performance` → `{"agents": [...], "period_days": 7}`
2. `curl -s http://localhost:8005/metrics | grep legion_agent_task_outcome_total` → HELP/TYPE lines present
3. Wait for organic swarm execution → counter has samples: `grep "^legion_agent_task_outcome_total"`

**B4 — Session Quality Grading (ADA)**:
1. Migration runs: `SELECT * FROM session_grades LIMIT 1;` returns empty
2. Set `ENABLE_SESSION_GRADING=true`, call `SessionGrader().grade_session(date.today())` via docker exec
3. `GET http://localhost:8000/api/learning/session-grades` → row with 5 dimensions

**B7 — Hunter Anomaly Detection (ADA)**:
1. Migration runs: `SELECT * FROM anomaly_events LIMIT 1;` returns empty
2. `GET http://localhost:8000/api/anomalies` → `[]` (200 OK)
3. Set `ENABLE_ANOMALY_DETECTION=true`, restart → log shows `anomaly_detector_started`
4. Insert synthetic regression data, wait for 5-min cycle → anomaly row appears

**A5 — RAG Overhaul (Legion)**:
1. Set `ENABLE_RAG_SEARCH=true`. `GET http://localhost:8005/api/knowledge/search?q=test` → empty results (not error)
2. Manually index an episode via docker exec → re-search → result appears
3. Set `ENABLE_KNOWLEDGE_DAEMON=true`, restart → `knowledge_ingestion` daemon registered in logs
4. Check `LEARNING_ENGINE_SOURCES_INJECTED{source="rag_search"}` counter after a task execution

### Alignment score target:
- Pre-alignment: Legion 52% / ADA 55%
- Post-Sprint-1: Both ~70% (ACHIEVED)
- Post-Sprint-2 target: Both > 80%

### Risk mitigations:
- All ADA features gated OFF by default (`ENABLE_X=false`) — zero cost/risk until operator enables
- All ADA DB migrations use `CREATE TABLE IF NOT EXISTS` + `CREATE INDEX IF NOT EXISTS` — idempotent, safe to re-run
- Qdrant embedding dimension: all 3 fallback tiers produce 384-dim vectors matching existing config
- Knowledge daemon capped at 500 files/cycle with 0.5s throttle — won't overload DB
- All reasoning capture + session grading wraps persist in try/except — NEVER blocks trading
