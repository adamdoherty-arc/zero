# Learn-20: ASI-Evolve Cognition + Swarm Tool Scoping + Session Resume

## Context

The ASI-Evolve paper (arxiv 2603.29640) validates Legion's learn-evolve-verify architecture but reveals a key gap: **the GEPA optimizer has no memory of prior experiment outcomes** (it may regenerate rolled-back variants). Meanwhile, the Claude Agent SDK demonstrates patterns Legion's swarm lacks: **per-agent tool scoping** (preventing nodes from using tools outside their role) and **session resume** (replaying prior context on retry instead of starting blind). This sprint wires all five patterns into the existing codebase with zero new migrations and zero new dependencies.

## Dependency Graph

```
F1 (Cognition Base)  ─── independent
F2 (Data Curation)   ─── independent (same file as F1, different function)
F3 (Tool Scoping)    ─── independent
F4 (Swarm Hooks)     ─── DEPENDS on F3 (hooks invoke inside scoped_tool_call)
F5 (Session Resume)  ─── independent
```

**Order**: F1 + F2 first (GEPA optimizer), then F3 → F4 (tool scoping + hooks), then F5 (session resume).

---

## Feature 1: ASI-Evolve Cognition Base

**File**: [dspy_optimizer_service.py](backend/app/services/dspy_optimizer_service.py)

**Problem**: `compile_template()` has no memory of prior optimization attempts. If a canary was rolled back (`regression=True`), the optimizer may generate the same failed variant again.

**Changes**:

### 1a. Add import (line 48)
Add `PromptImprovementDB` to the existing import from `app.models.prompt_manager`:
```python
from app.models.prompt_manager import PromptTemplateDB, PromptImprovementDB
```

### 1b. Add `_fetch_experiment_history()` helper (~30 lines, after line 311)
- Query `prompt_improvements` WHERE `prompt_template_id = template_id` AND `status IN ('applied', 'rolled_back')` AND `(verified_positive IS NOT NULL OR regression IS NOT NULL)`
- Order by `created_at DESC`, limit 10
- Return tuple: `(failed_experiments, successful_experiments)` — each a list of dicts with `{rationale, old_value_preview, new_value_preview, verification_delta, status}`
- Wrap entire function body in try/except returning `([], [])` on failure

### 1c. Call helper in `compile_template()` (insert between lines 229-231, after MiniMax breaker check)
```python
failed_experiments, successful_experiments = [], []
try:
    failed_experiments, successful_experiments = await _fetch_experiment_history(db, template_id)
except Exception as e:
    logger.debug(f"[DSPy] experiment history fetch failed: {e}")
```

### 1d. Extend `_build_rewrite_prompt()` signature (line 314)
Add two optional params: `failed_experiments: list = None`, `successful_experiments: list = None`

### 1e. Add two prompt sections in `_build_rewrite_prompt()` (insert between line 371 bad_blocks and line 372 "YOUR TASK")
- Section: `# PRIOR FAILED OPTIMIZATIONS (do NOT repeat these patterns)` — list each failed experiment's rationale + primary_change + delta
- Section: `# PRIOR SUCCESSFUL OPTIMIZATIONS (reinforce these patterns)` — list each successful experiment similarly
- Both sections render as empty string if their lists are empty (no noise when no history)

### 1f. Update call site (lines 232-237) to pass the experiment history
### 1g. Add counts to `OptimizerResult.metadata` dict (line 298): `"cognition_failed_count"`, `"cognition_successful_count"`

**Est. LOC**: ~60

---

## Feature 2: ASI-Evolve Data Curation

**File**: [dspy_optimizer_service.py](backend/app/services/dspy_optimizer_service.py)

**Problem**: Training examples are selected purely by recency. A call with `review_score=95` is no more likely to be selected than one with `review_score=71`. No diversity consideration.

**Changes**:

### 2a. Add tunables (near line 61, alongside other DSPY_ env vars)
```python
DSPY_MAX_GOOD_EXAMPLES = int(os.getenv("DSPY_MAX_GOOD_EXAMPLES", "10"))
DSPY_MAX_BAD_EXAMPLES = int(os.getenv("DSPY_MAX_BAD_EXAMPLES", "10"))
```

### 2b. Sort by quality (insert after line 199, after good/bad bucketing)
```python
good.sort(key=lambda c: c.review_score or 0, reverse=True)   # best first
bad.sort(key=lambda c: c.review_score or 0)                   # worst first
```

### 2c. Diversity boost for good examples (~10 lines after the sort)
Bump score by +5 for calls with `improvement_source` != `"evaluator"` (multi-source reviewed). Re-sort good by this composite score.

### 2d. Update call site (lines 232-237) to use new limits
```python
good_examples=good[:DSPY_MAX_GOOD_EXAMPLES],
bad_examples=bad[:DSPY_MAX_BAD_EXAMPLES],
```

### 2e. Add selection metadata to `OptimizerResult.metadata` (line 298)
- `"good_score_range"`: min-max review_score of selected good examples
- `"bad_score_range"`: min-max review_score of selected bad examples
- `"diversity_sources"`: unique `improvement_source` values in selected good examples

**Est. LOC**: ~30

---

## Feature 3: Subagent Tool Scoping

**File**: [agent_swarm_service.py](backend/app/services/agent_swarm_service.py)

**Problem**: All swarm nodes can import and call any tool. A reviewer can `git_push`, a diagnostician can `git_commit`. No access control whatsoever.

**Changes**:

### 3a. Add `SWARM_TOOL_POLICIES` dict (after line 68, near other module constants)
```python
SWARM_TOOL_POLICIES: dict[str, frozenset[str]] = {
    "supervisor":    frozenset(),
    "coder":         frozenset({"execute_llm_task"}),
    "critique":      frozenset({"execute_llm_task"}),
    "tester":        frozenset({"run_tests"}),
    "reviewer":      frozenset({"execute_llm_task"}),
    "committer":     frozenset({"git_commit", "git_status"}),
    "diagnostician": frozenset({"execute_llm_task"}),
    "advance_task":  frozenset(),
    "mark_failed":   frozenset(),
    "complete":      frozenset(),
}
```

### 3b. Add Prometheus counters (~10 lines)
- `legion_swarm_tool_denied_total{node, tool}` — denied calls
- `legion_swarm_tool_allowed_total{node, tool}` — allowed calls
- Wrapped in try/except for import safety

### 3c. Add `scoped_tool_call()` function (~30 lines)
```python
async def scoped_tool_call(
    node_name: str,
    tool_func,
    invoke_args: dict,
    *,
    hooks: Optional["SwarmHooks"] = None,
) -> str:
```
- Extract tool name via `getattr(tool_func, "name", ...)`
- Check against `SWARM_TOOL_POLICIES[node_name]`
- If denied: log warning, increment counter, return error string (don't raise — nodes expect string results)
- If allowed: increment counter, invoke `pre_tool_use` hooks, call `.ainvoke()`, invoke `post_tool_use` hooks, return result

### 3d. Replace direct `.ainvoke()` calls in each node
Each replacement is a 1-line change from `await tool.ainvoke(args)` to `await scoped_tool_call("node_name", tool, args, hooks=_active_hooks)`:

| Node | Line | Current | Change to |
|------|------|---------|-----------|
| coder (direct fallback) | 495 | `execute_llm_task.ainvoke(invoke_args)` | `scoped_tool_call("coder", execute_llm_task, invoke_args)` |
| coder (recovery callable) | 476 | `execute_llm_task.ainvoke` passed to recovery | Wrap: `lambda args: scoped_tool_call("coder", execute_llm_task, args)` |
| critique (fallback) | 585 | `execute_llm_task.ainvoke({...})` | `scoped_tool_call("critique", execute_llm_task, {...})` |
| reviewer | 672 | `execute_llm_task.ainvoke({...})` | `scoped_tool_call("reviewer", execute_llm_task, {...})` |
| committer | 699 | `git_commit.ainvoke({...})` | `scoped_tool_call("committer", git_commit, {...})` |
| diagnostician | ~753 | `execute_llm_task.ainvoke(invoke_args)` | `scoped_tool_call("diagnostician", execute_llm_task, invoke_args)` |

**Note on error_recovery_service**: `coder_node` line 476 passes `execute_llm_task.ainvoke` as a callable to `recovery.execute_with_recovery()`. Must wrap this as a lambda that goes through `scoped_tool_call` so the scoping check happens on every recovery attempt.

**Est. LOC**: ~55

---

## Feature 4: Swarm Hooks (Callback Pattern)

**File**: [agent_swarm_service.py](backend/app/services/agent_swarm_service.py)

**Depends on**: Feature 3 (hook invocation points are inside `scoped_tool_call`)

**Problem**: The swarm has no audit trail for tool usage. The existing class-based middleware (`backend/app/agents/middleware.py`) only works with `BaseAgent`, not LangGraph nodes.

**Changes**:

### 4a. Add `SwarmHooks` dataclass (near line 68, after AgentRole enum)
```python
@dataclass
class SwarmHooks:
    pre_tool_use: list = field(default_factory=list)   # async (node, tool, args) -> None
    post_tool_use: list = field(default_factory=list)   # async (node, tool, args, result) -> None
    on_node_enter: list = field(default_factory=list)   # async (node, state) -> None
    on_node_exit: list = field(default_factory=list)    # async (node, state, result) -> None
```

### 4b. Add default hook implementations (~20 lines)
- `_audit_post_tool()` — logs `[Swarm:Audit] node -> tool (task=X) -> result_preview` at INFO level
- `build_default_hooks()` — returns `SwarmHooks(post_tool_use=[_audit_post_tool])`

### 4c. Add module-level `_active_hooks` variable
```python
_active_hooks: Optional[SwarmHooks] = None
```

### 4d. Initialize hooks in `execute_sprint_via_swarm()` (near line 1268)
```python
global _active_hooks
_active_hooks = build_default_hooks()
```

### 4e. Hook invocation in `scoped_tool_call()` (already in F3 design)
The `scoped_tool_call` from Feature 3 already invokes `hooks.pre_tool_use` and `hooks.post_tool_use`. Just pass `hooks=_active_hooks`.

### 4f. Add `on_node_enter`/`on_node_exit` calls at top/bottom of each tool-using node
Simple 4-line block at top of each node:
```python
if _active_hooks:
    for cb in _active_hooks.on_node_enter:
        try: await cb("coder", state)
        except Exception: pass
```
And matching block at bottom before return.

**Est. LOC**: ~70

---

## Feature 5: Session Resume for Task Retries

**File**: [agent_swarm_service.py](backend/app/services/agent_swarm_service.py)

**Problem**: On retry, the coder starts blind — only the `diagnosis` string from the diagnostician is prepended. All prior LLM conversation context is lost. But `LLMCallDetailDB.sprint_task_id` already links every LLM call to its task.

**Changes**:

### 5a. Add `_build_retry_context()` helper (~40 lines, near line 1011 after advance_task_node)
```python
async def _build_retry_context(task_id: int, attempt_count: int) -> Optional[str]:
```
- Return `None` if `attempt_count <= 0` or `not task_id`
- Open fresh `AsyncSessionLocal()` (don't share caller's session)
- Query `LLMCallDetailDB WHERE sprint_task_id = task_id ORDER BY created_at ASC LIMIT 10`
- For each prior call, extract: prompt (300 chars), response (500 chars), error, suggested_improvement, review_summary
- Format as compact `# PRIOR ATTEMPT SUMMARY (N calls)` block
- Total output capped at 4000 chars to prevent token bloat
- Entire function body wrapped in try/except returning `None`

### 5b. Wire into `coder_node()` (insert at line ~416, after `attempt` assignment, BEFORE the enrichment block at line 425)
```python
if attempt > 0 and task.get("id"):
    try:
        retry_context = await _build_retry_context(task.get("id"), attempt)
        if retry_context:
            prompt = f"{retry_context}\n\n{prompt}"
            logger.info(f"[Swarm] Session resume: injected retry context for task {task.get('id')} (attempt {attempt})")
    except Exception:
        pass
```

**Prompt order on retry**: `[retry_context]` → `[learning enrichment]` (skipped, attempt > 0) → `[diagnosis prepend]` → `[original prompt]`

The retry context goes first because it's the broadest context. The diagnosis (lines 452-457) is more specific and overwrites the prompt structure. This ordering means the LLM sees: "here's what you tried before" → "here's what went wrong" → "here's the task".

**Est. LOC**: ~55

---

## Summary

| Feature | File | LOC | Risk |
|---------|------|-----|------|
| F1: Cognition Base | dspy_optimizer_service.py | ~60 | Low (additive, try/except) |
| F2: Data Curation | dspy_optimizer_service.py | ~30 | Low (sort + truncate) |
| F3: Tool Scoping | agent_swarm_service.py | ~55 | Medium (replaces .ainvoke calls) |
| F4: Swarm Hooks | agent_swarm_service.py | ~70 | Low (additive callbacks) |
| F5: Session Resume | agent_swarm_service.py | ~55 | Low (read-only DB query) |
| **Total** | 2 files | **~270** | |

---

## Verification

### F1 + F2 (GEPA optimizer changes)
- GEPA is gated OFF (`ENABLE_DSPY_EVOLUTION=false`), so changes are dormant until activated
- **Unit verification**: In a `docker exec` Python shell, instantiate `DSPyOptimizerService()` and call `compile_template(template_id)` for a template that has `prompt_improvements` rows — verify the rewrite prompt contains `PRIOR FAILED OPTIMIZATIONS` section
- Check `OptimizerResult.metadata` includes `cognition_failed_count`, `good_score_range`

### F3 + F4 (Tool scoping + hooks)
- After rebuild, wait for the next swarm sprint execution (or trigger manually)
- Check logs for `[Swarm:Audit]` entries showing `node -> tool (task=X)`
- Check Prometheus: `curl localhost:8005/metrics | grep legion_swarm_tool`
- Verify `legion_swarm_tool_allowed_total` has entries for coder/execute_llm_task, committer/git_commit, etc.
- Verify `legion_swarm_tool_denied_total` is 0 (all calls should be allowed under normal operation)

### F5 (Session resume)
- Wait for or trigger a task retry (attempt > 0) in the swarm
- Check logs for `[Swarm] Session resume: injected retry context for task X (attempt Y)`
- Verify the LLM call in `llm_call_details` contains the `PRIOR ATTEMPT SUMMARY` prefix
- Verify first attempts (attempt=0) do NOT trigger the context builder

### Full rebuild
```bash
docker-compose build legion-backend && docker-compose up -d legion-backend
docker logs legion-backend --tail 50
curl -s http://localhost:8005/health | python -m json.tool
```
