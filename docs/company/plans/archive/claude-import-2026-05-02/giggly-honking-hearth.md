# Plan: Sprint Execution Without LLM — Script Executor Framework

## Context

Every auto-created sprint in Legion (Deps-, Fix-, Health-, Plan- categories) routes **all** tasks through the LLM pipeline: `supervisor_node()` → `coder_node()` → `execute_llm_task()` → Ollama/MiniMax. There is no alternative execution path. Even completely deterministic work like "update protobuf from 6.33.6 to 7.34.1 and run tests" burns an LLM call to generate the exact bash commands the creating service already knows.

### What does NOT need an LLM

After reading every sprint-creation service, here's the verdict:

| Sprint Type | LLM Needed? | Why / Why Not |
|---|---|---|
| **Deps-NN** (minor/patch upgrades) | **NO** | `sed` the version in requirements.txt, `pip install`, `pytest`. The service already knows old_version, new_version, package_manager. Prompt is a rigid template. |
| **Deps-NN** (major upgrades) | **HYBRID** | Try script first. If tests fail → LLM to fix breaking API changes. |
| **Deps-NN** (security fixes) | **HYBRID** | Same as major — version bump is mechanical, only breaking changes need reasoning. |
| **Deps-NN** (modernization/replacement) | **YES** | Replacing library X with Y requires reading imports, understanding API surface. |
| **Health-NN** (diagnostics) | **NO** | Every finding pattern in `health_sprint_creator.py` maps to a deterministic diagnostic checklist: `docker logs`, `SELECT COUNT(*)`, `curl /metrics`. |
| **Fix-NN** (known error patterns) | **NO** for ~60% | Greenlet errors, pool timeouts, import errors — all have known fixes. RCA already has an ignore-list for 10 patterns; could have a fix-template-list for 20 more. |
| **Fix-NN** (unknown patterns) | **YES** | Novel error clusters genuinely need reasoning. |
| **Plan-NN** (daily improvements) | **YES** | Improvement areas like "add tests", "improve error handling" need code-level reasoning. Templates only cover ~30%. |
| **Auto-NN** (work discovery) | **YES** | Open-ended strategic work. This is the correct use of LLM. |
| **Learn-/Builder-/Recovery-** | **YES** | Architecture, evolution, meta-improvements — 100% LLM-appropriate. |
| **Sprint Sync** (ADA/FortressOS) | **N/A** | Just DB sync, no task execution — already script-like. |

### Evidence from code

1. **`dependency_review_service.py:651-773`** — `_build_tasks_from_findings()` creates tasks with rigid template prompts. The service already has `package_name`, `current_version`, `latest_version`, `package_manager`. The LLM just reads these and generates `pip install` / `npm install`.

2. **`health_sprint_creator.py:32-100`** — `FINDING_PATTERNS` is a list of regex patterns mapped to prompt templates. Each pattern maps to a specific diagnostic: "run docker logs", "check DB connectivity", "check Prometheus counter". All deterministic.

3. **`root_cause_analysis.py:441-447`** — Fix sprint prompts are: "Keywords: X, Sample error: Y, Occurrences: N. Root cause analysis and permanent fix required." For known patterns (greenlet, pool timeout, import error), the fix is always the same.

4. **`agent_swarm_service.py:243-258`** — `supervisor_node()` ALWAYS returns `"next_agent": "coder"` for new tasks. No branching for script-executable tasks. Line 247: `"next_agent": "coder"` is hardcoded.

5. **`sprint_tools.py:28-57`** — `execute_llm_task()` sends every prompt to Ollama. No check for "is this task scriptable?"

### Bottom line

**~60-70% of auto-created sprint tasks don't need an LLM.** They need `sed`, `pip install`, `pytest`, `docker logs`, `curl`, and `psql`. The LLM is a $0.02-0.07 per-task translator between a structured template and a bash command the service already knows how to construct.

---

## Proposed Implementation: Script Executor with LLM Fallback

### Architecture

```
supervisor_node() picks up task
       │
       ▼
ScriptExecutorRegistry.try_handle(task)
       │
  ┌────┴────┐
  │ Match?  │
  ├─YES─────┤──→ Execute script ──→ Tests pass? ──→ DONE (no LLM cost)
  │         │                            │
  │         │                        Tests fail?
  │         │                            │
  │         │                    ┌───────┴───────┐
  │         │                    │ should_fallback│
  │         │                    │ _to_llm=True?  │
  │         │                    ├──YES───────────┤──→ Fall through to coder_node()
  │         │                    ├──NO────────────┤──→ Mark FAILED
  │         │                    └────────────────┘
  │         │
  └─NO──────┘──→ Existing path: coder_node() → LLM
```

### Files to Create/Modify

#### 1. NEW: `backend/app/services/script_executor.py` (~200 lines)

Core framework:

```python
class TaskResult:
    success: bool
    output: str
    error: str | None
    should_fallback_to_llm: bool  # If True, swarm falls through to coder_node

class ScriptExecutor(ABC):
    async def can_handle(self, task: dict, sprint_name: str) -> bool: ...
    async def execute(self, task: dict, project_path: str) -> TaskResult: ...

class ScriptExecutorRegistry:
    _executors: list[ScriptExecutor]

    async def try_handle(self, task, sprint_name, project_path) -> TaskResult | None:
        for executor in self._executors:
            if await executor.can_handle(task, sprint_name):
                return await executor.execute(task, project_path)
        return None  # No match → fall through to LLM
```

Three concrete executors (start with these, expand later):

**A. `DependencyUpgradeExecutor`**
- Matches: sprint name starts with `Deps-`, task title matches `Upgrade X Y → Z` or `Update N minor/patch dependencies`
- Execution: parse package/version from title → `sed` requirements.txt or `npm install pkg@version` → `pytest` / `npm test`
- Fallback to LLM: if tests fail (breaking changes need reasoning)

**B. `HealthDiagnosticExecutor`**
- Matches: sprint name starts with `Health-`, task title matches known `FINDING_PATTERNS` keys
- Execution: run the diagnostic checklist as shell commands (DB queries, curl, grep logs)
- Fallback to LLM: never (diagnostics either pass or the system is broken beyond script capability)

**C. `KnownFixExecutor`**
- Matches: sprint name starts with `Fix-`, task prompt contains known error pattern keywords
- Execution: template-driven fix scripts (e.g., greenlet → add AsyncSessionLocal, pool → increase pool_size)
- Fallback to LLM: if template fix doesn't resolve the error

#### 2. MODIFY: `backend/app/services/agent_swarm_service.py` (~15 lines)

In `supervisor_node()`, before the hardcoded `"next_agent": "coder"` at line 247:

```python
# Check if task can be executed without LLM
from app.services.script_executor import get_script_registry
registry = get_script_registry()
sprint_name = state.get("sprint_name", "")
script_result = await registry.try_handle(task, sprint_name, project_path)

if script_result is not None:
    if script_result.success:
        # Skip LLM entirely — go straight to testing
        return {
            "current_task": task,
            "phase": "testing",
            "next_agent": "tester",
            "cli_output": script_result.output,
            "attempt_count": 0,
        }
    elif not script_result.should_fallback_to_llm:
        return {"next_agent": "mark_failed", "phase": "failed",
                "errors": [script_result.error]}
    # else: fall through to coder_node (LLM) as normal
```

#### 3. MODIFY: `backend/app/services/agent_swarm_service.py` — pass sprint_name through state

The `sprint_name` needs to be available in `SwarmState`. It's already set when the swarm is invoked from `sprint_lifecycle_graph.py`. Verify and thread if needed.

### What this does NOT change

- **No DB schema changes** (no migration needed)
- **No new API endpoints** (this is internal execution logic)
- **No frontend changes**
- **Existing LLM path is 100% preserved** as fallback
- **Sprint creation logic untouched** — same services create the same sprints, just execution is smarter

### Prometheus metrics to add

```python
# In script_executor.py
legion_script_executor_total = Counter(
    "legion_script_executor_total",
    "Tasks executed via script (no LLM)",
    ["executor", "result"]  # result: success, failed, fallback_to_llm
)
```

### Verification

1. **Unit test**: Create a mock Deps task, verify `DependencyUpgradeExecutor.can_handle()` returns True, verify `execute()` returns a `TaskResult`
2. **Integration test**: Create a real Deps sprint with a known minor patch upgrade, verify it completes without any LLM calls (check `llm_call_details` table — should have 0 rows for this sprint's task IDs)
3. **Prometheus check**: After deploy, `curl /metrics | grep legion_script_executor_total` should show non-zero counts for `executor=dependency_upgrade, result=success`
4. **Fallback verification**: Create a Deps sprint with a known breaking major upgrade, verify it tries script first, fails, then falls through to LLM coder_node

### Risk assessment

- **LOW risk**: LLM fallback means any script failure just reverts to current behavior
- **No blast radius**: Only affects auto-created sprints, not manual or strategic ones
- **Incremental**: Start with Deps only, add Health/Fix executors after validation
