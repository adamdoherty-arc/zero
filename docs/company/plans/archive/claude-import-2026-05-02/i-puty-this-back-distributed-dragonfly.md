# Sprint System Transparency & MiniMax 2.7 Switch

## Context

User is reviewing the Deps-01 sprint detail modal and hit 5 distinct concerns:

1. **Automation kickoff feels broken** — clicking "Start Autonomous" leaves most tasks in `Pending` rather than visibly cycling through them.
2. **"QA Approved" with empty notes** — the `importlib_metadata 8.7.1 → 9.0.0` task shows the QA Approved badge but the "What Was Done" box says *"Task completed but no execution notes available."* — QA signed off on a void.
3. **MiniMax 2.7 should be the model** — user explicitly said "This needs to use minimax 2.7 for now".
4. **LLM requests/responses must be recorded for review** — the whole point of Legion is you can pull up the prompt + response for any decision.
5. **Project grader dimensions have no "why"** — the 52.5 grade shows bars for Code Quality 60 / Test Coverage 50 / Documentation 40 / etc., but no text explaining why each dimension landed on that number.

Investigation surfaced real bugs behind 2, 4, 5 and a real config gap behind 3. Concern 1 turned out to be working-as-designed (serial executor) but the UI is confusing. Plan addresses each with the smallest change that makes the behavior honest.

---

## Findings (diagnosis summary)

### 1. Kickoff — "pending" is actually correct, UI just doesn't say so
- `execute_sprint_autonomous` at [backend/app/api/endpoints/sprints.py:1625](backend/app/api/endpoints/sprints.py#L1625) schedules the executor via `background_tasks.add_task(run_sprint)` and returns immediately.
- The executor walks tasks **serially** via `_execute_all_tasks` at [backend/app/services/autonomous_sprint_executor.py:1315](backend/app/services/autonomous_sprint_executor.py#L1315). PENDING→RUNNING flips per-task when `mark_task_running` fires at [line 1933](backend/app/services/autonomous_sprint_executor.py#L1933).
- The live DB shows the `Running` task is genuinely the one currently executing; the `Pending` tasks are waiting their turn, as designed. So the status display is **accurate**, just not intuitive — the UI modal's "How it works" copy implies parallel execution.
- **Fix**: Copy tweak only — change the dialog wording to clarify serial execution. No engine change.

### 2. Script-executor path skips completion notes
- The script executor branch at [autonomous_sprint_executor.py:1889](backend/app/services/autonomous_sprint_executor.py#L1889) calls `await self.sprint_manager.mark_task_completed(task.id)` with **no `completion_notes=` argument**. All LLM completion paths (lines 1942, 1961, 2001, 2089, 2138, 2174) do pass notes.
- SprintTaskDB has the column `completion_notes` (backend/app/models/sprint_execution.py:157). Frontend reads `task.completion_notes || task.output_summary` and falls back to the "no execution notes available" placeholder.
- The importlib_metadata task went through the deterministic dep-upgrade script executor — hence the empty box even though QA approved the outcome.
- **Fix**: Capture script output and pass it as `completion_notes` in the completed / failed branches around line 1889 / 1900.

### 3. MiniMax 2.7 is configured but not primary
- MiniMax M2.7 is fully wired: [legion_config.py:627-639](backend/app/core/legion_config.py#L627-L639) defines the model; API mapping `MINIMAX_MODEL_MAP[MINIMAX_M2.value] = "MiniMax-M2.7"` at line 844.
- **Current routing** (Learn-20) makes Ollama primary and MiniMax fallback-only: [legion_config.py:686-687](backend/app/core/legion_config.py#L686-L687) `PLANNING_MODEL = EXECUTION_MODEL = OLLAMA_QWEN_CODER_NEXT`; `TASK_MODEL_ROUTING` at [line 694-707](backend/app/core/legion_config.py#L694-L707) uses `[_OQ, _MM]` order for every task type.
- User wants MiniMax M2.7 primary for now — flip the routing.
- **Fix**: Swap `PLANNING_MODEL`/`EXECUTION_MODEL` to `MINIMAX_M2`, flip `TASK_MODEL_ROUTING` entries to `[_MM, _OQ]`, update `FULL_MODEL_ESCALATION` to `[MINIMAX_M2, OLLAMA_QWEN_CODER_NEXT]`, update `TIER_ALIASES["primary"|"sonnet"|"haiku"]` to `MINIMAX_M2`, update comments. This is the Learn-20 → "MiniMax primary" switch.

### 4. LLM calls aren't linked to sprint tasks
- `llm_call_details.sprint_task_id` column exists and is FK-indexed, but live query shows **0 of 13 recent rows have it populated**.
- `unified_llm_service` consumes `_sprint_task_id` correctly via `kwargs.pop` at [unified_llm_service.py:1013, 1344, 1718, 1963, 2094, 2286](backend/app/services/unified_llm_service.py#L1013) and persists it via `tracker.start_call(sprint_task_id=...)`.
- **BUT** callers don't pass it. Only [sprint_tools.py:96](backend/app/services/sprint_tools.py#L96) passes `_sprint_task_id=`. The autonomous executor's 6+ LLM calls (e.g. [line 507-512](backend/app/services/autonomous_sprint_executor.py#L507-L512)) all omit it → every sprint-executed LLM row has `sprint_task_id=NULL`.
- Full prompts and responses ARE stored (`prompt_full`, `response_full` columns on `llm_call_details`) and LLMConsole.tsx shows them — but you can't cross-reference them back to a sprint task without a manual guess.
- **Fix**: Thread `_sprint_task_id=task.id` through every `llm_service.execute/chat/execute_with_tools` call inside `autonomous_sprint_executor.py` (the task.id is already in scope at every call site). Add a "View LLM calls for this task" deep-link in the sprint task detail.

### 5. Project grader never asks for per-dimension rationale
- `ProjectGradeResponse` schema at [schemas/llm_responses.py:164](backend/app/schemas/llm_responses.py#L164) has `grade_breakdown: GradeBreakdown` (flat `{code_quality: float, ...}`, no rationale) + `findings` (general list) + `improvement_areas`.
- The `PROJECT_REVIEW_PROMPT` at [project_grader_service.py:64-115](backend/app/services/project_grader_service.py#L64-L115) asks for raw scores — never asks the LLM to explain each number.
- So when the UI renders `Code Quality: 60`, there is genuinely no "why" recorded anywhere in the DB. Same hole applies to `DockerLogsGradeResponse`.
- `"Raw LLM Response: (structured output)"` placeholder is set on purpose at [project_grader_service.py:246](backend/app/services/project_grader_service.py#L246) when the Pydantic parse succeeds — we throw away the raw text because the schema captured it. That is the right call IF the schema has the rationale. Today it doesn't.
- Frontend UI at [frontend/src/pages/ProjectPlans.tsx:659-675](frontend/src/pages/ProjectPlans.tsx#L659-L675) renders scores from `grade.grade_breakdown` but has nowhere to look up a per-dimension explanation.
- **Fix**: Add `rationale_breakdown: Dict[str, str]` to both `ProjectGradeResponse` and `DockerLogsGradeResponse` (additive, non-breaking). Update the two prompts to require one sentence of reasoning per dimension. Persist it into `plan_grades.grade_breakdown` as a nested shape OR add a parallel `rationale_breakdown` JSON column. Update the frontend to show the rationale under each dimension bar (tooltip or expand-click).

---

## Implementation Plan

### Scope: one Legion sprint — `FE-Transparency-01: Sprint system honesty + MiniMax 2.7 switch`

Per CLAUDE.md, track as sprint in Legion DB (`project_id=3`) with tasks below.

### Task 1 — (PIVOTED 2026-04-22) Remove MiniMax from routing entirely — vLLM for everything

User redirected mid-execution: "Switch from minimax to local in vllm for everything now". vLLM is already running (`vllm-chat` container, healthy, serves `qwen3-chat` at `host.docker.internal:18800/v1`) and `LOCAL_LLM_BACKEND=vllm` is already set in both `.env` and docker-compose defaults. So the local tier (routed under the `LLMProvider.OLLAMA` identity) resolves to `VLLMClient` at runtime. What's left is to kill every routing path that still has MiniMax as a fallback, so no traffic ever lands there unless we reverse the decision.

**File**: [backend/app/core/legion_config.py](backend/app/core/legion_config.py)

- Line 651-656: `TIER_ALIASES["primary"|"sonnet"|"opus"|"haiku"]` → all `OLLAMA_QWEN_CODER_NEXT`. (`opus` used to be `MINIMAX_M2` — flip it.)
- Line 669-672: `FULL_MODEL_ESCALATION = [OLLAMA_QWEN_CODER_NEXT]` — drop MiniMax.
- Line 679-681: `OLLAMA_FALLBACK = {}` — remove the Ollama→MiniMax fallback. Hard fail on vLLM outage; operator can re-enable MiniMax with a one-line revert.
- Line 686-687: `PLANNING_MODEL = EXECUTION_MODEL = OLLAMA_QWEN_CODER_NEXT` (already correct).
- Line 694-707: `TASK_MODEL_ROUTING` — every entry becomes `[_OQ]` (drop `_MM`).
- Update the Learn-20 / Recovery-01 comments to record the 2026-04-22 removal of MiniMax from routing and the reason (operator directive, vLLM stable).

**File**: [backend/app/services/unified_llm_service.py:218](backend/app/services/unified_llm_service.py#L218)

- Replace the hardcoded `"active_provider": "minimax"` with a live derivation: if `LOCAL_LLM_BACKEND=vllm` and OLLAMA not disabled → `"vllm"`; else `"ollama"`; else `"minimax"`. Truthful labels over stale ones.

- **Verify**: `curl -s -X POST http://localhost:8005/llm/execute -H "Content-Type: application/json" -d '{"prompt":"Say ok","task_type":"general","_source":"verification"}'` → response's `provider = "ollama"`, `model = "qwen3-chat"` (vLLM's served model name). `/health` → `"active_provider": "vllm"`. Running the DB query `SELECT provider, COUNT(*) FROM llm_call_details WHERE created_at > NOW() - INTERVAL '10 minutes' GROUP BY provider` after some traffic shows only `ollama` (the routing identity), zero `minimax`.

### Task 2 — Populate completion notes from script executor
**File**: [backend/app/services/autonomous_sprint_executor.py:1889](backend/app/services/autonomous_sprint_executor.py#L1889)

Change the success branch from:
```python
await self.sprint_manager.mark_task_completed(task.id)
```
to:
```python
notes = (_sr.output or "Script executor completed task successfully.")[:2000]
await self.sprint_manager.mark_task_completed(task.id, completion_notes=notes)
```

Do the same for the failure branch at line 1900: pass `completion_notes=f"Script executor failed: {_sr.error}"` (via `mark_task_failed`'s `last_error` / notes field — check the signature first).

**Verify**: Re-run the `importlib_metadata` task via the "Re-run Task" button; after it completes, the modal's "What Was Done" box shows the script output.

### Task 3 — Thread `_sprint_task_id` through every autonomous-executor LLM call
**File**: [backend/app/services/autonomous_sprint_executor.py](backend/app/services/autonomous_sprint_executor.py)

Grep for every `self.llm_service.execute(`, `.chat(`, `.execute_with_tools(` inside the file. For every call that has access to a task object in scope, add `_sprint_task_id=task.id` (or whatever the local variable is named) to the kwargs. Call sites seen during investigation: lines 511, 600, 892, 2293, 2314, 2762 — grep will turn up the full list.

Also audit `agent_swarm_service.py` and `agent_execution_service.py` for LLM calls that have a `sprint_task_id` in scope but don't forward it.

**Verify**:
```bash
docker exec legion-db psql -U legion -d legion -c \
  "SELECT COUNT(*) FILTER (WHERE sprint_task_id IS NOT NULL) AS linked, COUNT(*) AS total FROM llm_call_details WHERE created_at > NOW() - INTERVAL '1 hour';"
```
After kicking off a sprint task, `linked` should be >0 and trending toward `total` for sprint-originated traffic.

### Task 4 — Add `rationale_breakdown` to grade schemas + prompts
**Files**:
- [backend/app/schemas/llm_responses.py:164](backend/app/schemas/llm_responses.py#L164) — add `rationale_breakdown: Dict[str, str] = Field(default_factory=dict, description="One-sentence reasoning per dimension")` to `ProjectGradeResponse` AND `DockerLogsGradeResponse`.
- [backend/app/services/project_grader_service.py:64-115 + 117-167](backend/app/services/project_grader_service.py#L64-L115) — update both prompt templates to include in the JSON shape:
  ```
  "rationale_breakdown": {
    "code_quality": "<one-sentence reason for this score>",
    "test_coverage": "<...>",
    ...
  }
  ```
- [backend/app/services/project_grader_service.py:241-252](backend/app/services/project_grader_service.py#L241-L252) — in the structured-output success branch, include `rationale_breakdown=structured_result.rationale_breakdown` on the `GradeResult` dataclass. Add that field to the `GradeResult` dataclass if it's not there.
- [backend/app/models/plan.py `PlanGradeDB`](backend/app/models/plan.py) — either (a) add a `rationale_breakdown` JSON column via Alembic migration, or (b) merge it into the existing `grade_breakdown` JSON as a nested shape. Prefer (a) — non-breaking.
- [backend/app/models/plan.py `PlanGradeDetailResponse`](backend/app/models/plan.py#L228) — add `rationale_breakdown: Optional[Dict[str, str]] = None`.

### Task 5 — Frontend: show rationale under each dimension
**File**: [frontend/src/pages/ProjectPlans.tsx:659-675](frontend/src/pages/ProjectPlans.tsx#L659-L675)

Where each `grade_breakdown` dimension bar is rendered, add either:
- A subtle expand-chevron that reveals `grade.rationale_breakdown[dim]` inline, OR
- A native `title=` tooltip with the rationale string (lower-friction, ships in one line).

Prefer inline-expand — more discoverable than a tooltip, and we already render `findings` + `improvement_areas` as expandable sections.

### Task 6 — Add "LLM calls for this task" deep-link
**Files**:
- Sprint detail modal — for each task card, add a small link reading `View N LLM calls` that deep-links to `/llm-console?sprint_task_id=<id>`.
- [frontend/src/pages/LLMConsole.tsx](frontend/src/pages/LLMConsole.tsx) — read the `sprint_task_id` query param and add it as a filter. Backend endpoint must already support filtering by `sprint_task_id` — verify and add if missing.

### Task 7 — Fix the "Automate Sprint" dialog wording
**File**: frontend dialog component (grep for "Claude Opus 4.5 plans each task")

- Remove/rewrite the "2. Free models (Ollama/Gemini) execute the code" line — inaccurate (Gemini is removed per CLAUDE.md, Ollama is now fallback under this change).
- Clarify: tasks execute serially, one at a time; the `Pending` badge means "queued, not yet started".
- Model line should read: "MiniMax M2.7 executes each task" (match the new primary).

---

## Verification (end-to-end)

After all tasks land:

1. **Restart stack**: `docker-compose build legion-backend legion-frontend && docker-compose up -d && docker logs legion-backend --tail 30`.
2. **Model flip**: `curl -s -X POST http://localhost:8005/llm/execute -H "Content-Type: application/json" -d '{"prompt":"Say hello","task_type":"general","_source":"verification"}'` — response JSON should show `provider: "minimax"` and a MiniMax model id.
3. **Re-run Deps-01 task**: Click "Re-run Task" on `Upgrade importlib_metadata 8.7.1 → 9.0.0`. After completion, "What Was Done" shows the script output (not the "no execution notes" fallback).
4. **Sprint→LLM linkage**: `SELECT COUNT(*) FILTER (WHERE sprint_task_id IS NOT NULL) FROM llm_call_details WHERE created_at > NOW() - INTERVAL '10 minutes';` is >0 after any task run.
5. **Project grader rationale**: Trigger a `Legion Project Review` via the Plans UI. Inspect the resulting grade — `grade.rationale_breakdown` populated for all 6 dimensions. Frontend shows rationale when you click/hover each bar.
6. **LLM Console filter**: From the sprint modal, click "View LLM calls" on the importlib_metadata task — LLMConsole opens filtered to exactly that task's calls, showing full prompts and responses.

---

## Rollback

- Task 1 (routing flip): revert the 6 lines in legion_config.py; restart backend.
- Task 4 (schema additive): `rationale_breakdown` default is `{}`, so existing callers keep working. Drop the column + field if it causes issues.
- Task 2 & 3 are additive (pass extra kwarg) — no rollback needed beyond the revert.
