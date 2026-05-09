# Plan: Self-Learning Sprint Improvement System

## Context

Legion has a comprehensive sprint system (plan -> decompose -> execute -> QA -> learn) but sprint quality remains low (~38/100 self-rating). The root cause: **9 learning subsystems were built but only 2 are actually active** (Learning Aggregator + Episodic Memory). The remaining 7 (LLM Review, Prompt Evaluator, Prompt Manager, Annotation Queue, Routing Optimizer, Learning Engine, Knowledge Ingestion) are either disabled by default or never wired into the execution path. Meanwhile, the `LearningEngine` — designed to be the central coordinator consolidating all learning sources — has a **bug in `enrich_task_context()`** (doesn't unpack tuple from `format_few_shot_context`) proving it's never been called.

**Goal**: Activate all dormant learning infrastructure, wire the `LearningEngine` as the single entry point for task context enrichment, close the annotation-to-improvement feedback loop, and create a sprint quality audit skill that grades every sprint dimension 0-100.

## Phase 1: Fix Backend + Wire LearningEngine (Learn-14)

**Why first**: The backend is currently returning 502 (likely migration 026 not applied). Fix that, then replace the 3 ad-hoc learning calls in the executor with one `LearningEngine.enrich_task_context()` call — adding prompt evolution + cross-project learning to Auto-Sprints for free.

### 1.1 Fix Backend Startup
- Run `docker-compose build legion-backend && docker-compose up -d`
- Verify migration 026 (prompt_manager tables) applied
- Check `docker logs legion-backend --tail 100` for import errors
- Verify `curl http://localhost:8005/health` returns 200

### 1.2 Fix LearningEngine Bug
**File**: [learning_engine.py](backend/app/services/learning_engine.py)
- Line 147: `few_shot = await mem.format_few_shot_context(...)` doesn't unpack tuple
- Fix: `few_shot, episode_ids = await mem.format_few_shot_context(...)`
- Add Prometheus counters: `legion_learning_engine_enrichments_total`, `legion_learning_engine_sources_injected`

### 1.3 Replace Ad-hoc Calls with LearningEngine
**File**: [autonomous_sprint_executor.py:1790-1813](backend/app/services/autonomous_sprint_executor.py#L1790-L1813)

Replace the separate episodic memory + knowledge injection block (lines 1790-1813) with:
```python
from app.services.learning_engine import get_learning_engine
engine = get_learning_engine()
task.prompt = await engine.enrich_task_context(
    task_type=task_type_str,
    base_prompt=task.prompt,
    project_id=self._state.project_id,
    domain=task_type_str,
)
```

After task completion (~line 1885), add:
```python
await engine.record_outcome(task_type, success=True/False, ...)
```

This adds **prompt evolution** + **cross-project learning** to every Auto-Sprint task — two learning sources that were completely missing.

### 1.4 Enable Review Daemons in docker-compose.yml
**File**: [docker-compose.yml](docker-compose.yml)
- Set `ENABLE_LLM_REVIEW=true` (was false) — activates 5-min semantic review cycles
- Set `ENABLE_PROMPT_EVALUATOR=true` (was false) — activates 10-min quality evaluation cycles
- These daemons already exist and are production-ready, just need the env flag

### Files Modified
| File | Change |
|------|--------|
| `backend/app/services/learning_engine.py` | Fix tuple unpack bug, add Prometheus counters |
| `backend/app/services/autonomous_sprint_executor.py` | Replace lines 1790-1813 with LearningEngine call, add record_outcome |
| `docker-compose.yml` | `ENABLE_LLM_REVIEW=true`, `ENABLE_PROMPT_EVALUATOR=true` |

---

## Phase 2: Close the Feedback Loop (Learn-15)

**Why second**: With review daemons enabled (Phase 1), annotations will accumulate in `PromptAnnotationDB`. But annotations never become improvements — the pipeline is broken between "flagged" and "template updated". This phase closes that gap.

### 2.1 Add Improvement Processing to AnnotationQueueService
**File**: [annotation_queue_service.py](backend/app/services/annotation_queue_service.py)
- New method: `process_pending_improvements()` — queries priority 1-2 annotations, groups by template, calls Kimi K2.5 to generate improved prompt text
- Creates `PromptImprovementDB` entries with status `proposed`
- Adds Prometheus counter: `legion_prompt_improvements_proposed_total`

### 2.2 Add Auto-Apply to PromptManagerService
**File**: [prompt_manager_service.py](backend/app/services/prompt_manager_service.py)
- New method: `auto_apply_improvements()` — when 3+ annotations point to the same issue for a template, auto-approve and apply the improvement
- Creates new template version (existing `update_template()` handles versioning)
- Safeguard: `parent_version_id` allows one-click revert

### 2.3 Extend Prompt Evaluator Cycle
**File**: [prompt_evaluator_agent.py](backend/app/services/prompt_evaluator_agent.py)
- Every 3rd evaluation cycle (30 min), call `process_pending_improvements()` + `auto_apply_improvements()`
- This creates the closed loop: LLM call -> review -> annotate -> improve template -> better next call

### 2.4 Add API Endpoints
**File**: [prompt_manager.py](backend/app/api/endpoints/prompt_manager.py)
- `POST /prompt-manager/improvements/process` — manual trigger
- `POST /prompt-manager/improvements/{id}/approve` — approve specific improvement
- `POST /prompt-manager/improvements/{id}/apply` — apply to template

### Files Modified
| File | Change |
|------|--------|
| `backend/app/services/annotation_queue_service.py` | Add `process_pending_improvements()` |
| `backend/app/services/prompt_manager_service.py` | Add `auto_apply_improvements()` |
| `backend/app/services/prompt_evaluator_agent.py` | Call improvement processing every 3rd cycle |
| `backend/app/api/endpoints/prompt_manager.py` | Add 3 improvement endpoints |

---

## Phase 3: Sprint Quality Audit Skill + Grader (Learn-16)

**Why third**: With learning activated (Phase 1) and feedback loop closed (Phase 2), there's now data to grade. This phase creates the sprint-level quality grading system.

### 3.1 Create Sprint Quality Grader Service
**File**: `backend/app/services/sprint_quality_grader.py` (NEW, ~200 lines)

Grades each sprint across **7 dimensions** (pure DB queries, no LLM needed):

| Dimension | Weight | Data Source | What It Measures |
|-----------|--------|-------------|-----------------|
| **Task Decomposition** | 15% | `sprint_tasks` | Prompt length, title clarity, story point distribution |
| **Prompt Quality** | 20% | `prompt_annotations` joined to sprint's `llm_call_details` | Avg request/response quality scores |
| **Routing Effectiveness** | 10% | `sprint_learnings` (routing traces) | Learned vs static routing %, confidence |
| **Execution Success** | 20% | `sprint_tasks` status counts | Completion rate, first-attempt rate, retry count |
| **Learning Capture** | 15% | `episodes` + `sprint_learnings` for sprint_id | Episodes stored, outcomes recorded |
| **QA Gate** | 10% | `sprint_tasks` test results, qa_status | Test pass rate, fix cycles needed |
| **Time Efficiency** | 10% | Task timestamps (created_at -> completed_at) | Duration vs estimates, timeout rate |

Each dimension: 0-100 score. Weighted total = overall sprint quality grade.

### 3.2 Create API Endpoints
**File**: `backend/app/api/endpoints/sprint_quality.py` (NEW, ~50 lines)
- `GET /api/sprint-quality/{sprint_id}` — get quality grade
- `GET /api/sprint-quality/recent?project_id=3&limit=10` — recent grades with trends
- `POST /api/sprint-quality/{sprint_id}/grade` — trigger grading

### 3.3 Wire Into Sprint Completion
**File**: [sprint_manager.py](backend/app/services/sprint_manager.py)
- In `complete_sprint()`: after marking COMPLETED, trigger `grade_sprint()` asynchronously
- Store grade in existing `PlanGradeDB` infrastructure (trends/sparklines come for free)

### 3.4 Create Claude Code Skill
**Directory**: `.claude/skills/legion-sprint-auditor/`

- `SKILL.md` — Skill definition: `/legion-sprint-auditor` runs comprehensive audit
  - Queries backend for recent sprint quality grades
  - Compares against benchmarks (prompt quality >70, execution >80, etc.)
  - Identifies worst-performing dimensions across recent sprints
  - Suggests specific improvements for each low-scoring dimension
  - Updates knowledge file with findings

- `knowledge/sprint_audit_history.json` — Per-sprint scores, trends, improvement tracking
- `knowledge/improvement_patterns.md` — Which patterns correlate with high/low grades

### Files Modified/Created
| File | Change |
|------|--------|
| `backend/app/services/sprint_quality_grader.py` | NEW: 7-dimension sprint grading |
| `backend/app/api/endpoints/sprint_quality.py` | NEW: 3 API endpoints |
| `backend/app/api/router_registry.py` | Register sprint_quality router |
| `backend/app/services/sprint_manager.py` | Trigger grading on sprint completion |
| `.claude/skills/legion-sprint-auditor/SKILL.md` | NEW: Skill definition |
| `.claude/skills/legion-sprint-auditor/knowledge/` | NEW: Audit history + patterns |

---

## Phase 4: Frontend Sprint Quality Dashboard (FE-06)

**Why last**: Backend grading and APIs must exist before the UI can display them.

### 4.1 Create React Hook
**File**: `frontend/src/hooks/useSprintQuality.ts` (NEW, ~40 lines)
- `useSprintQuality(sprintId)` — fetch grade for one sprint
- `useRecentSprintQualities(projectId, limit)` — fetch grade trends

### 4.2 Create Sprint Quality Card Component
**File**: `frontend/src/components/sprint/SprintQualityCard.tsx` (NEW, ~120 lines)
- Radar chart showing 7 dimension scores (using recharts, already installed)
- Color-coded: green (>70), yellow (40-70), red (<40)
- Trend arrow: delta from previous sprint

### 4.3 Integrate Into Sprint Detail Dialog
**File**: [SprintDetailDialog.tsx](frontend/src/components/sprint/SprintDetailDialog.tsx)
- Add "Quality" tab to existing dialog tabs
- Shows SprintQualityCard when grade data available
- Shows "Not graded" message for sprints without grades

### 4.4 Extend Prompt Manager Page
**File**: [PromptManager.tsx](frontend/src/pages/PromptManager.tsx)
- Add Improvements tab showing proposed/approved/applied improvements
- Approve/Apply/Reject buttons per improvement
- Before/after template diff view

### Files Modified/Created
| File | Change |
|------|--------|
| `frontend/src/hooks/useSprintQuality.ts` | NEW: Quality grade hooks |
| `frontend/src/components/sprint/SprintQualityCard.tsx` | NEW: 7-dimension radar chart |
| `frontend/src/components/sprint/SprintDetailDialog.tsx` | Add Quality tab |
| `frontend/src/pages/PromptManager.tsx` | Add Improvements tab |

---

## Model Research Note

The user asked about model choice. Current setup:
- **Kimi K2.5** for planning/analysis — good for structured output, JSON schemas, strategic decisions
- **Ollama qwen3-coder-next** for code execution — strong at code gen, fast locally

**Recommendation**: Keep this setup. qwen3-coder-next is the right choice for code execution (optimized for coding tasks, runs locally with no API cost). Kimi K2.5 is the right choice for sprint quality analysis (better at reasoning over metrics). No model change needed. The improvement comes from **better prompts and learning feedback**, not different models.

---

## Verification Plan

After all phases:
1. `curl http://localhost:8005/health` — backend healthy
2. `docker logs legion-backend --tail 50 | grep "LearningEngine"` — enrichment calls logged
3. `docker logs legion-backend --tail 50 | grep "LLMReview"` — review daemon cycling
4. `docker logs legion-backend --tail 50 | grep "PromptEvaluator"` — evaluator cycling
5. Query DB: `SELECT count(*) FROM prompt_annotations` — annotations accumulating
6. Query DB: `SELECT count(*) FROM prompt_improvements` — improvements being proposed
7. Query DB: `SELECT slug, version FROM prompt_templates WHERE version > 1` — templates evolving
8. `curl http://localhost:8005/api/sprint-quality/recent?project_id=3` — grades returned
9. Frontend: Open Sprint Detail -> Quality tab shows radar chart
10. Run `/legion-sprint-auditor` — produces graded report with improvement suggestions

## Sprint Sizing

| Sprint | Estimate | New Files | Modified Files |
|--------|----------|-----------|----------------|
| Learn-14 (Wire LearningEngine) | Small | 0 | 3 |
| Learn-15 (Feedback Loop) | Medium | 0 | 4 |
| Learn-16 (Audit Skill + Grader) | Medium | 4 | 2 |
| FE-06 (Dashboard) | Medium | 3 | 2 |
