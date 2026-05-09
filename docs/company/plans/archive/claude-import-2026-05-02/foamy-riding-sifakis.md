# Prompt Manager Hardening + Article Pattern Insights + Auditor Integration

## Context

The Prompt Manager system was fully built (Prompt-01 through Prompt-06: migration 026, 3 DB tables, 3 services, 15 API endpoints, 4-tab frontend page). However, post-build review found **15 gaps** preventing it from actually working in production — the evaluator daemon never starts (missing env var), prompts still come from hardcoded `prompt_library.py` (not DB), and agent seeding returns 0.

Separately, a 482-page book "Agentic Design Patterns" (21 patterns by Antonio Gulli) was reviewed for improvements applicable to Legion. Several patterns map directly to existing gaps.

Finally, the Prompt Manager needs to be added to the platform auditor's feature catalog so it gets graded.

---

## Sprint: Prompt-07: Prompt Manager Hardening

**3 phases, 10 tasks total** — all fixes, no new features.

---

### Phase 1: P0 Critical Fixes (daemon + template wiring)

#### Task 1: Enable evaluator daemon in Docker
**File**: `docker-compose.yml`
- Add `ENABLE_PROMPT_EVALUATOR=true` to `legion-backend.environment`
- This is why the daemon never runs — env var defaults to `"false"` and Docker never sets it

#### Task 2: Wire unified_llm_service.py to use DB-backed templates
**File**: `backend/app/services/unified_llm_service.py` (line 562-571)
- Currently imports from `prompt_library` (hardcoded):
  ```python
  from app.services.prompt_library import get_system_prompt, get_temperature
  ```
- Replace with DB lookup via PromptManagerService, falling back to prompt_library:
  ```python
  # Try DB-backed template first, fallback to hardcoded
  try:
      from app.services.prompt_manager_service import get_prompt_manager_service
      svc = get_prompt_manager_service()
      template = await svc.get_template_for_task_type(task_type)
      if template:
          system_prompt = template.system_prompt
          if temperature == 0.7:
              temperature = template.temperature or 0.7
      else:
          raise ValueError("not found")
  except Exception:
      # Fallback to hardcoded library
      from app.services.prompt_library import get_system_prompt, get_temperature
      system_prompt = get_system_prompt(task_type)
      if temperature == 0.7:
          temperature = get_temperature(task_type)
  ```

#### Task 3: Auto-seed templates on startup
**File**: `backend/main.py` (in startup event, after DB is ready)
- After health check, run seed if `prompt_templates` table is empty:
  ```python
  from app.services.prompt_manager_service import get_prompt_manager_service
  svc = get_prompt_manager_service()
  count = await svc.count_templates()
  if count == 0:
      lib_count = await svc.seed_from_library()
      logger.info(f"[Startup] Seeded {lib_count} prompt templates from library")
  ```
- Add `count_templates()` method to PromptManagerService (simple `select(func.count(...))`)

---

### Phase 2: P1 Correctness Fixes

#### Task 4: Sync EXEMPT_SOURCES between evaluator and LLM review
**File**: `backend/app/services/prompt_evaluator_agent.py` (line 111-114)
- Current evaluator only exempts 4 sources: `prompt_evaluator`, `llm_review_agent`, `verification_confidence`, `knowledge_ingestion`
- LLMReviewService exempts 13 sources (line 38-52 of `llm_review_service.py`)
- Fix: Extract a shared `EXEMPT_SOURCES` set to a common location (e.g., `app/core/constants.py`) and import in both services. Missing sources: `chain_grade_analysis`, `project_grader_structured`, `work_discovery`, `sprint_learning`, `sprint_tool`, `langchain_wrapper`, `project_grader`, `project_grader_docker_logs`, `unknown`

#### Task 5: Fix seed_from_agents() to actually extract prompts
**File**: `backend/app/services/prompt_manager_service.py` — `seed_from_agents()` method
- Currently checks `getattr(agent_class, "SYSTEM_PROMPT", None)` — agents use `_get_system_prompt()` instance methods instead
- Fix: Instantiate agents (they have no-arg constructors) and call `agent._get_system_prompt()`, or read from the agent registry's stored definitions
- Should seed ~26 agent templates instead of 0

#### Task 6: Fix priority assignment in auto_flag
**File**: `backend/app/services/annotation_queue_service.py` — `auto_flag_from_evaluator()` method
- Priority calculation only produces values 1-4, but schema allows 1-5
- Fix the threshold logic to use all 5 priority levels:
  - P5 (critical): both scores < 30
  - P4: either score < 40
  - P3: either score < 55
  - P2: either score < 70
  - P1: edge cases

---

### Phase 3: P2 Quality Fixes

#### Task 7: Fix N+1 in list_improvements()
**File**: `backend/app/services/annotation_queue_service.py` — `list_improvements()`
- Currently runs a DB query per improvement to get template info
- Fix: Use `joinedload(PromptImprovementDB.template)` or a single subquery join

#### Task 8: Set updated_at on new template versions
**File**: `backend/app/services/prompt_manager_service.py` — `update_template()` method
- When creating a new version row, `updated_at` is never explicitly set
- Fix: Set `updated_at=datetime.now(UTC).replace(tzinfo=None)` on the new template row

#### Task 9: Add improvement_type validation
**File**: `backend/app/models/prompt_manager.py`
- `improvement_type` accepts any string — should validate against: `request_rewrite`, `output_instructions`, `temperature_adjust`, `schema_fix`, `context_enrichment`
- Add `@validates("improvement_type")` on `PromptImprovementDB`

#### Task 10: Add Prompt Manager to platform auditor
**File**: `.claude/skills/legion-platform-auditor/knowledge/feature_catalog.json`
- Add new entry `"prompt_manager"` with id 29
- Update `total_features` from 28 to 29
- Include: route `/prompt-manager`, page file, 16 hooks, 18 API endpoints, 3 backend services, 4 sub_tabs
- Set importance: 1.2 (high — core to self-improvement loop)

---

## Article Insights: Agentic Design Patterns Mapped to Legion

The 482-page book covers 21 patterns. Here's how they map to Legion and where improvements are warranted. These are **recommendations for future sprints**, not part of Prompt-07.

### Patterns Legion Already Implements Well
| # | Pattern | Legion Implementation |
|---|---------|----------------------|
| 1 | Prompt Chaining | Sprint execution graph (plan->decompose->execute->verify->learn) |
| 2 | Routing | Task-type routing + keyword routing + learned routing |
| 3 | Parallelization | Agent swarm (concurrent task execution) |
| 6 | Planning | PlanningCortex + Brain decisions + Sprint decomposition |
| 7 | Multi-Agent | 29 agents, council system, swarm execution |
| 8 | Memory | Episodic memory + knowledge sources + sprint learnings |
| 12 | Exception Handling | ErrorRecoveryService in 4 execution paths |
| 18 | Guardrails | Safety configs, health gate, autonomy levels |
| 20 | Prioritization | Brain decisions, work discovery (10 sources) |

### Patterns with Improvement Opportunities (Future Sprints)

**Pattern 4 — Reflection (Self-Correction)**: Legion retries failed tasks with the same prompt. Book recommends feeding output + critique back for self-correction before retry. Add reflection step in `_execute_task()` when response_quality < 70.

**Pattern 9 — Learning/Adaptation (SICA)**: The Prompt Manager IS this pattern. After Prompt-07, consider auto-apply mode for high-confidence improvements (suggested 3+ times).

**Pattern 11 — Goal Setting/Monitoring**: Plans have grades but no automatic response to declining trends. Wire grade trend analysis into Brain's `plan_project()` — auto-investigate if grade declines 3+ cycles.

**Pattern 16 — Resource-Aware Optimization**: Task-type routing is static. Add complexity estimation (prompt length + keyword heuristics) to route simple tasks to smaller models.

**Pattern 17 — Reasoning Techniques**: No CoT prompting. Prompt templates should include step-by-step reasoning instructions for complex task types — this is a template content improvement via the improvement pipeline.

**Pattern 19 — Evaluation/A-B Testing**: No template version comparison. Add version quality trend charts to the analytics tab.

---

## Critical Files to Modify

| File | Change | Priority |
|------|--------|----------|
| `docker-compose.yml` | Add `ENABLE_PROMPT_EVALUATOR=true` | P0 |
| `backend/app/services/unified_llm_service.py` L562-571 | DB template lookup with fallback | P0 |
| `backend/main.py` ~L460 area | Auto-seed on startup | P0 |
| `backend/app/services/prompt_manager_service.py` | `count_templates()`, fix `seed_from_agents()`, fix `updated_at` | P1 |
| `backend/app/services/prompt_evaluator_agent.py` L111-114 | Sync EXEMPT_SOURCES | P1 |
| `backend/app/services/annotation_queue_service.py` | Fix N+1, fix priority levels | P1-P2 |
| `backend/app/models/prompt_manager.py` | Add improvement_type validation | P2 |
| `.claude/skills/legion-platform-auditor/knowledge/feature_catalog.json` | Add feature #29 | P2 |

---

## Verification

1. **Docker**: `docker-compose build legion-backend && docker-compose up -d` — verify `ENABLE_PROMPT_EVALUATOR=true` via `docker exec legion-backend env`
2. **Auto-seed**: Check logs for `[Startup] Seeded N prompt templates` on fresh start
3. **DB templates**: Make LLM call, verify system_prompt comes from DB (no "Prompt library lookup failed" in logs)
4. **Evaluator**: After 10 min, `docker logs legion-backend | grep PromptEvaluator` shows cycle completion
5. **Annotations**: After evaluator runs, `GET /api/prompt-manager/queue` returns flagged calls
6. **Auditor**: Run `/legion-platform-auditor`, verify Prompt Manager appears in graded features
7. **Build**: `cd frontend && npm run build` (TypeScript clean)
8. **Tests**: `cd backend && python -m pytest tests/ -k "prompt" -v`
