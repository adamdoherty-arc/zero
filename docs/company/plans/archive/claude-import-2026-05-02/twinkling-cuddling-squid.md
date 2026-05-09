# Zero Brain: Autonomous Learning Employee System

## Context

Zero currently has AI Company agents, a Council, Deep Research, and Experiment Lab — but these are **reactive tools**, not a learning system. ADA and Legion both act as autonomous employees that continuously learn, self-benchmark, evolve their prompts, and improve without being asked. Zero needs the same brain — particularly for content creation (TikTok pipeline), which should run experiments and learn what works 24/7.

**What we're building:** A closed-loop learning engine that makes Zero think like ADA (episodic memory, outcome tracking, self-benchmarking, calibration, reflection) and execute like Legion (prompt evolution, domain learning, cross-project insights, intelligent recovery). The content creation pipeline becomes the primary beneficiary — learning which products, scripts, hooks, and posting times drive engagement.

---

## Phase 1: Database + Models

### Migration `backend/app/migrations/versions/018_zero_brain.py`

7 new tables:

| Table | Purpose |
|-------|---------|
| `episodic_memories` | Facts/decisions/outcomes extracted from LLM interactions. pgvector 768-dim embeddings, 90-day TTL, importance scoring |
| `brain_outcome_records` | Every decision + measured result. Strategy used, predicted vs actual score, domain-tagged |
| `prompt_variants` | Prompt templates per task type with success/failure counts, avg score, generation lineage |
| `benchmark_scores` | Current 10-dimension employee scores |
| `benchmark_history` | Snapshots over time for trend tracking |
| `learning_cycles` | Audit log of every learning/benchmark/evolution cycle |
| `content_experiments` | A/B tests for content strategies (hook styles, templates, posting times) |

### Pydantic Models `backend/app/models/brain.py` (new)

Enums: `BrainDomain` (content/research/experiment/task/money/system), `MemoryNamespace`, `BenchmarkDimension`

Request/Response models: `EpisodicMemoryCreate`, `EpisodicMemory`, `MemorySearchResult`, `OutcomeRecordCreate`, `OutcomeRecord`, `PromptVariant`, `BenchmarkScore`, `BenchmarkSnapshot`, `BrainStatus`, `LearningCycle`, `ContentExperiment`

### ORM Models — additions to `backend/app/db/models.py`

7 new classes following existing `Mapped[]` + `mapped_column()` pattern: `EpisodicMemoryModel`, `BrainOutcomeRecordModel`, `PromptVariantModel`, `BenchmarkScoreModel`, `BenchmarkHistoryModel`, `LearningCycleModel`, `ContentExperimentModel`

---

## Phase 2: Core Services (7 new files)

### 2a. `backend/app/services/episodic_memory_service.py`
- `extract_and_store(text, source_type, source_id, namespace, context)` — LLM extracts facts/decisions/outcomes, embeds via `get_ollama_client().embed_safe()`, stores with 90-day TTL
- `search(query, namespace, limit)` — pgvector cosine similarity search
- `enrich_prompt(task_description, namespace, limit)` — returns formatted few-shot context block for injection into any LLM call
- `cleanup_expired()` — TTL enforcement, high-importance memories get extended retention

### 2b. `backend/app/services/outcome_learning_service.py`
- `record_outcome(domain, action_type, action_id, strategy_used, predicted_score, actual_score, metrics)` — records to `brain_outcome_records`, auto-extracts learnings via LLM
- `get_strategy_metrics(domain, strategy, days)` — per-strategy win rate, avg score, calibration error (MAE)
- `get_calibration_report(domain, days)` — bucket predicted vs actual into confidence ranges (0-20, 20-40, etc.)
- `get_best_strategy(domain, action_type)` — returns highest-performing strategy with min sample threshold
- `extract_learnings(domain, days)` — LLM synthesizes insights from recent outcomes

### 2c. `backend/app/services/prompt_evolution_service.py`
- `register_variant(task_type, variant_name, prompt_template, is_baseline)` — register prompt variant
- `select_best(task_type)` — Thompson Sampling: `random.betavariate(success+1, failure+1)` for exploration/exploitation balance
- `record_usage(variant_id, score, success)` — update counts and avg_score
- `evolve(task_type)` — LLM mutates best variant informed by outcome data. Only evolves when best has 10+ uses. Creates child variant with `generation + 1`

### 2d. `backend/app/services/employee_benchmark_service.py`

10 dimensions (weighted), all scored from live DB queries except 2 LLM-evaluated:

| Dimension | Weight | Data Source |
|-----------|--------|-------------|
| Content Quality | 15% | `content_performance` avg engagement, scripts generated, content published |
| Learning Velocity | 15% | `benchmark_history` score improvement rate over last 5 snapshots |
| Research Depth | 12% | `deep_research_reports` completed count + LLM grades top 3 |
| Task Execution | 12% | `agent_tasks` completed/total ratio |
| System Health | 10% | `scheduler_audit_log` job success rate 24h |
| Experiment Rigor | 10% | `content_experiments` + council decisions completion rate |
| Cost Efficiency | 8% | `llm_usage` cost/output ratio |
| Communication Quality | 8% | LLM grades last 5 briefings |
| Calibration Accuracy | 5% | MAE from outcome_learning_service |
| Knowledge Growth | 5% | New episodic memories + notes last 30 days vs prior 30 |

Methods: `run_benchmark()`, `get_latest()`, `get_history(limit)`, `spawn_improvement(dimension)` (creates AgentTask for CEO to fix weakest dimension)

### 2e. `backend/app/services/content_learning_engine.py`
- `process_content_outcomes()` — hourly: query new `content_performance` records, record to brain outcomes, extract learnings, store as episodic memories
- `get_product_performance_insights()` — which product categories/template types perform best
- `get_content_strategy_leaderboard()` — rank strategies by avg performance
- `run_content_experiment(type, hypothesis, control, variant)` — start A/B test
- `check_experiments()` — check sample sizes, compute significance, declare winner
- `get_posting_time_analysis()` — engagement by hour-of-day

### 2f. `backend/app/services/reflection_service.py`
- `reflect(content, content_type, criteria, max_iterations=3)` — Analyze→Critique→Improve→Validate loop. Returns `{final_content, iterations, improvements_made, quality_scores}`
- `reflect_on_decisions(decisions, domain)` — periodic meta-reflection on recent decisions, stores insights as episodic memories

### 2g. `backend/app/services/zero_brain_service.py` (Central Hub)
- `get_status()` — full BrainStatus (benchmark scores, memory count, experiments, etc.)
- `run_learning_cycle()` — orchestrates: process outcomes → extract memories → update metrics → content learning → check experiments
- `run_benchmark()` — delegates to EmployeeBenchmarkService
- `run_improvement(dimension?)` — auto-improve weakest dimension
- `enrich_task_prompt(task_description, domain)` — before any LLM task: inject episodic memory + best prompt variant + recent learnings
- `record_interaction_outcome(domain, action_type, ...)` — record + extract memory
- `search_memory(query, namespace, limit)` — search episodic memory
- `get_learnings(domain, days)` — recent learnings
- `get_calibration(domain)` — calibration report

All services use `@lru_cache()` singleton pattern (e.g., `get_zero_brain_service()`).

---

## Phase 3: API Router

### `backend/app/routers/brain.py` (new)

Prefix: `/api/brain`, auth: `Depends(require_auth)`

| Endpoint | Method | Returns |
|----------|--------|---------|
| `/status` | GET | BrainStatus |
| `/benchmark` | GET | BenchmarkSnapshot |
| `/benchmark/history` | GET | List[BenchmarkSnapshot] |
| `/learnings` | GET | List (query: domain, days, limit) |
| `/calibration` | GET | Calibration report |
| `/outcomes` | GET | Outcome dashboard |
| `/improve` | POST | Trigger improvement cycle |
| `/memory` | GET | Memory search (query: q, namespace, limit) |
| `/memory/recent` | GET | Recent memories |
| `/prompts` | GET | Prompt variants (query: task_type) |
| `/prompts/best` | GET | Best variant for task type |
| `/experiments` | GET | List content experiments |
| `/experiments` | POST | Create experiment |
| `/experiments/{id}` | GET | Single experiment |
| `/content/insights` | GET | Product performance insights |
| `/content/strategies` | GET | Strategy leaderboard |
| `/content/posting-times` | GET | Posting time analysis |
| `/cycles` | GET | Recent learning cycles |
| `/cycles/run` | POST | Trigger manual cycle |

Register in `backend/app/main.py`: `app.include_router(brain.router)`

---

## Phase 4: Scheduler Integration

Add 9 jobs to `DAILY_SCHEDULE` in `backend/app/services/scheduler_service.py`:

| Job | Schedule | Handler |
|-----|----------|---------|
| `brain_benchmark` | Every 6h (`0 */6 * * *`) | Run full 10-dimension benchmark |
| `brain_learning_cycle` | Every 4h (`0 */4 * * *`) | Process outcomes, extract memories, update metrics |
| `brain_content_learn` | Every 1h (`0 * * * *`) | Process content performance outcomes |
| `brain_experiment_monitor` | Every 2h (`0 */2 * * *`) | Check experiments for completion |
| `brain_prompt_evolve` | Every 12h (`0 */12 * * *`) | Evolve prompt variants from outcome data |
| `brain_episodic_extract` | Every 30m (`*/30 * * * *`) | Extract memories from recent LLM interactions |
| `brain_improvement` | Daily 3 AM (`0 3 * * *`) | Auto-improve weakest dimension |
| `brain_reflection` | Every 8h (`0 */8 * * *`) | Reflect on recent decisions |
| `brain_memory_cleanup` | Daily 4 AM (`0 4 * * *`) | Cleanup expired memories |

Add handler methods + `_get_handler()` mapping entries.

---

## Phase 5: Orchestration Graph Integration

In `backend/app/services/orchestration_graph.py`:
- Add `"brain"` to `VALID_ROUTES`
- Add keywords: `["brain", "benchmark", "learning", "self-improve", "employee score", "calibration", "prompt evolution", "episodic memory", "brain status", "how am i doing", "improvement"]`
- Add `brain_node` function that delegates to `get_zero_brain_service()`
- Add to classification system prompt

---

## Phase 6: Frontend

### `frontend/src/hooks/useBrainApi.ts` (new)
React Query hooks: `useBrainStatus()`, `useBenchmarkHistory()`, `useBrainLearnings()`, `useCalibrationReport()`, `useBrainExperiments()`, `useMemorySearch()`, `useContentInsights()`, `useTriggerImprovement()`, `useTriggerLearningCycle()`

### `frontend/src/pages/BrainDashboardPage.tsx` (new)
- Top stats row: Overall Score, Weakest Dimension, Total Memories, Active Experiments
- Radar chart (recharts `RadarChart`) of 10 dimensions
- Score history line chart from benchmark_history
- Dimension breakdown table with trends
- Recent learnings feed with domain badges
- Active content experiments cards
- Calibration report panel
- Memory search with results
- Action buttons: Run Benchmark, Trigger Learning Cycle, Improve Weakest

### Sidebar + Routes
- Add `{ label: 'Brain', href: '/brain', icon: Brain }` to `frontend/src/components/layout/AppSidebar.tsx` in AI Company section
- Add `<Route path="/brain" element={<BrainDashboardPage />} />` to `frontend/src/App.tsx`

---

## Phase 7: Existing System Integration

Wire the brain into existing services (light-touch, 1-3 lines each):

1. **`content_agent_service.py`** — after `run_improvement_cycle()`, call `brain.record_interaction_outcome(domain="content", ...)`
2. **`tiktok_video_service.py`** — before generating scripts, call `brain.enrich_task_prompt()` for memory/prompt injection
3. **`tiktok_shop_service.py`** — on product status transitions, record outcomes to brain
4. **`deep_research_service.py`** — enrich research queries with episodic memories, store findings as memories
5. **`council_service.py`** — record council decisions as outcomes, update when results known
6. **`continuous_enhancement_service.py`** — record enhancement outcomes for learning velocity
7. **`orchestration_graph.py`** — enrich router context with episodic memories

---

## Phase 8: Claude Code Skill

### `.claude/skills/zero-brain.md` (new)

Modes:
- `--status` — Show benchmark scores, weakest dimension, active experiments, proactive insights
- `--benchmark` — Trigger full benchmark, display radar chart of results
- `--improve` — Identify weakest dimension, research root cause, propose and execute fix
- `--learn` — Show recent learnings, calibration report, outcome trends
- `--experiment <type> <hypothesis>` — Start a content A/B experiment
- `--reflect` — Run reflection cycle on recent decisions
- `--audit` — Full system audit (scheduler health, brain job success rates, memory growth, cost)
- `--memory <query>` — Search episodic memory

---

## Files Modified (existing)

| File | Changes |
|------|---------|
| `backend/app/db/models.py` | Add 7 ORM model classes |
| `backend/app/main.py` | Register brain router |
| `backend/app/services/scheduler_service.py` | Add 9 jobs + 9 handlers + mapping |
| `backend/app/services/orchestration_graph.py` | Add brain route + keywords + node |
| `backend/app/services/content_agent_service.py` | Record outcomes to brain after improvement cycles |
| `backend/app/services/tiktok_video_service.py` | Enrich prompts before script generation |
| `backend/app/services/tiktok_shop_service.py` | Record product outcomes |
| `backend/app/services/deep_research_service.py` | Enrich with memories, store findings |
| `backend/app/services/council_service.py` | Record council outcomes |
| `backend/app/services/continuous_enhancement_service.py` | Record enhancement outcomes |
| `frontend/src/components/layout/AppSidebar.tsx` | Add Brain nav item |
| `frontend/src/App.tsx` | Add /brain route |

## Files Created (new)

| File | Purpose |
|------|---------|
| `backend/app/migrations/versions/018_zero_brain.py` | 7 tables |
| `backend/app/models/brain.py` | Pydantic models |
| `backend/app/services/episodic_memory_service.py` | Memory extraction + storage + search |
| `backend/app/services/outcome_learning_service.py` | Decision tracking + calibration |
| `backend/app/services/prompt_evolution_service.py` | Prompt variant tracking + evolution |
| `backend/app/services/employee_benchmark_service.py` | 10-dimension scoring |
| `backend/app/services/content_learning_engine.py` | Content-specific learning |
| `backend/app/services/reflection_service.py` | Analyze→Critique→Improve→Validate |
| `backend/app/services/zero_brain_service.py` | Central hub |
| `backend/app/routers/brain.py` | API endpoints |
| `frontend/src/hooks/useBrainApi.ts` | React Query hooks |
| `frontend/src/pages/BrainDashboardPage.tsx` | Dashboard page |
| `.claude/skills/zero-brain.md` | Claude Code skill |

---

## Verification

1. **Migration**: Run `docker exec zero-api alembic upgrade head` — all 7 tables created
2. **API Health**: `curl http://localhost:18792/api/brain/status` returns BrainStatus JSON
3. **Benchmark**: `curl -X POST http://localhost:18792/api/brain/benchmark` returns 10-dimension scores
4. **Memory**: Create a memory via the service, then `curl http://localhost:18792/api/brain/memory?q=test` returns semantic results
5. **Scheduler**: Check `docker logs zero-api` for `brain_benchmark`, `brain_learning_cycle` job executions
6. **Frontend**: Navigate to `http://localhost:5173/brain` — radar chart renders, stats populate
7. **Integration**: Generate TikTok content, verify outcome appears in `/api/brain/outcomes`
8. **Docker rebuild**: `docker compose -f docker-compose.sprint.yml build --no-cache zero-api && docker compose -f docker-compose.sprint.yml up -d zero-api`, then restart zero-ui

---

## Implementation Order

1. Migration + ORM models + Pydantic models
2. Episodic Memory Service
3. Outcome Learning Service
4. Prompt Evolution Service
5. Reflection Service
6. Employee Benchmark Service
7. Content Learning Engine
8. Zero Brain Service (hub)
9. API Router + main.py registration
10. Scheduler jobs
11. Orchestration graph integration
12. Frontend hook + page + sidebar + routes
13. Existing system integration (content, tiktok, research, council, enhancement)
14. Claude Code skill
15. Docker rebuild + verification
