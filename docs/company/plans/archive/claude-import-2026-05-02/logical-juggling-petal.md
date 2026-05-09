# Learn-20: Code Structure Graph Integration

## Context

Legion's sprint execution pipeline (swarm, grader, learning engine, work discovery) is structurally blind. When a sprint modifies `unified_llm_service.py`, the swarm has no idea that 40+ callers will be affected. The grader scores execution quality but not change risk. The learning engine injects episodic memory but zero structural awareness.

[code-review-graph](https://github.com/tirth8205/code-review-graph) is a mature (8.8K stars, v2.3.1) Python library that builds a persistent structural knowledge graph of codebases using Tree-sitter. It tracks functions, classes, imports, call relationships, and inheritance in SQLite. Key capabilities we're taking:
- **Blast radius**: Given changed files, traces callers/dependencies/tests within configurable depth, risk-scores each (0.0-1.0)
- **Flow tracing**: Detects entry points, BFS traversal of CALLS edges, criticality scoring
- **Dead code detection**: Functions with zero callers — directly actionable for Clean-XX sprints
- **Incremental updates**: SHA-256 hash check + targeted re-parse, sub-2-second updates

We're **NOT** taking: community detection (academic), semantic search (we have Qdrant), wiki gen (we have CLAUDE.md), visualization (low ops value), multi-repo registry (monorepo).

## Sprint: Learn-20 (5 tasks)

### Task 1: Add `code-review-graph` dependency + `CodeGraphService` skeleton

**Files to create/modify:**
- `backend/requirements.txt` — add `code-review-graph>=2.3.0`
- `backend/app/services/code_graph_service.py` — NEW (~200 lines)

**CodeGraphService API:**
```python
class CodeGraphService:
    _instance = None
    _store: Optional[GraphStore] = None
    _db_path: str = "/app/workspace/.code-review-graph/code.db"

    async def ensure_graph(self, repo_root: str = "/app/workspace") -> GraphStore
    async def update_graph(self, repo_root: str = "/app/workspace") -> dict
    async def get_blast_radius(self, changed_files: list[str]) -> dict
    async def get_risk_score(self, file_path: str) -> float
    async def find_dead_code(self, kind: str = "Function") -> list[dict]
    async def get_affected_files_for_task(self, task_prompt: str, project_path: str) -> list[str]
    async def format_structural_context(self, changed_files: list[str]) -> str

def get_code_graph_service() -> CodeGraphService  # singleton getter
```

**Key patterns:**
- All `code_review_graph` library calls are synchronous — wrap in `asyncio.to_thread()`
- `GraphStore` is the central object; store a singleton on the service
- `ensure_graph()` builds if SQLite doesn't exist, updates incrementally if it does
- `format_structural_context()` returns a compact string like:
  ```
  [Structural Context] Files affected by this change:
  - backend/app/services/unified_llm_service.py (risk: 0.82, callers: 43)
  - backend/app/services/agent_swarm_service.py (risk: 0.65, callers: 12)
  Untested functions: _enforce_provider_gate, _acquire_minimax_slot
  ```
- Feature-gated via `ENABLE_CODE_GRAPH` env var (default `"true"`)

### Task 2: Register graph update daemon in `main.py`

**File to modify:** `backend/main.py` — insert after the LLM quality grader block (line ~449)

**Daemon pattern** (follows existing `_supervised_task` pattern):
```python
# Start code graph update daemon (supervised, 4h cycle)
if os.getenv("ENABLE_CODE_GRAPH", "true").lower() == "true":
    try:
        from app.services.code_graph_service import start_code_graph_daemon
        t = asyncio.create_task(
            _supervised_task("code_graph_daemon", start_code_graph_daemon)
        )
        task_registry.register("code_graph_daemon", t, kind="daemon")
        print("   [OK] Code graph daemon starting (supervised, 4h cycle)")
    except Exception as e:
        print(f"   [WARN] Code graph daemon failed: {e}")
```

**Daemon function** (in `code_graph_service.py`):
```python
async def start_code_graph_daemon():
    interval = int(os.getenv("CODE_GRAPH_INTERVAL_SECONDS", "14400"))  # 4h
    svc = get_code_graph_service()
    # Initial build on first startup
    await svc.ensure_graph()
    while True:
        await asyncio.sleep(interval)
        try:
            result = await svc.update_graph()
            logger.info(f"[CodeGraph] Updated: {result.get('files_updated', 0)} files, "
                       f"{result.get('total_nodes', 0)} nodes")
        except Exception as e:
            logger.warning(f"[CodeGraph] Update failed: {e}")
```

**Also add to `docker-compose.yml`:**
```yaml
ENABLE_CODE_GRAPH: "true"
CODE_GRAPH_INTERVAL_SECONDS: "14400"
```

### Task 3: Wire structural context into `learning_engine.enrich_task_context()`

**File to modify:** [learning_engine.py:191](backend/app/services/learning_engine.py#L191) — add as source #5 after cross-project learnings

**Insertion point:** After line 191, before line 193 ("Combine all context parts"):

```python
# 5. Structural graph context (affected files for this task type)
try:
    from app.services.code_graph_service import get_code_graph_service
    graph_svc = get_code_graph_service()
    struct_ctx = await graph_svc.format_structural_context_for_task(
        task_type=task_type, base_prompt=base_prompt
    )
    if struct_ctx:
        context_parts.append(struct_ctx)
        LEARNING_ENGINE_SOURCES_INJECTED.labels(source="structural_graph").inc()
except Exception as e:
    logger.debug(f"Structural graph enrichment skipped: {e}")
```

**How `format_structural_context_for_task` works:**
- Extracts file mentions from `base_prompt` via regex (`[\w/]+\.py`, `[\w/]+\.tsx`, etc.)
- Calls `analyze_changes(store, mentioned_files)` from `code_review_graph.changes`
- Returns compact text with risk scores + review priorities + test gaps
- Returns `None` if no files extracted or graph not built yet (graceful skip)

### Task 4: Add `structural_risk` dimension to `sprint_quality_grader.py`

**File to modify:** [sprint_quality_grader.py](backend/app/services/sprint_quality_grader.py)

**4a. Update WEIGHTS** (line 82-90) — rebalance to add 8th dimension:
```python
WEIGHTS = {
    "task_decomposition": 0.15,
    "prompt_quality": 0.18,          # was 0.20
    "routing_effectiveness": 0.10,
    "execution_success": 0.20,
    "learning_capture": 0.12,        # was 0.15
    "qa_gate": 0.10,
    "time_efficiency": 0.10,
    "structural_risk": 0.05,         # NEW
}
```

**4b. Call grading method** — after time_efficiency dimension (~line 220), before `compute_overall()`:
```python
# 8. Structural Risk
sr_score, sr_details = await self._grade_structural_risk(db, s_id, s_project_id, task_data)
grade.set_dimension("structural_risk", sr_score, self.WEIGHTS["structural_risk"], sr_details)
```

**4c. Implement `_grade_structural_risk()`** — new method at end of class:

Scoring logic:
- **Baseline: 70** (no graph = neutral, doesn't punish sprints where graph isn't built yet)
- **+15** if all modified files have tests (TESTED_BY edges exist)
- **+15** if no high-risk functions modified (risk < 0.7)
- **-20** if any untested high-risk function modified
- **-15** per circular dependency introduced
- If graph not available: return `(70, {"graph_available": False, "note": "code graph not built yet"})`

**Bump `GRADER_VERSION`** to `"v4-learn20"`.

### Task 5: Wire dead code detection into `work_discovery_service.py`

**File to modify:** [work_discovery_service.py](backend/app/services/work_discovery_service.py)

**5a. Add as discovery source** — after the last existing source in `discover_work()`, before the sorting/dedup:

```python
# 11. Dead code detection (from structural graph)
try:
    sources_queried.append("dead_code_detection")
    dead_items = await self._discover_dead_code(project_id)
    work_items.extend(dead_items)
    if dead_items:
        logger.info(f"Found {len(dead_items)} dead code cleanup items")
except Exception as e:
    logger.debug(f"Dead code detection discovery skipped: {e}")
```

**5b. Implement `_discover_dead_code()`**:
```python
async def _discover_dead_code(self, project_id: int) -> list[dict]:
    from app.services.code_graph_service import get_code_graph_service
    svc = get_code_graph_service()
    dead = await svc.find_dead_code(kind="Function")
    items = []
    for d in dead[:10]:  # Cap at 10 per discovery run
        items.append({
            "title": f"Remove dead code: {d['name']} in {d['file']}",
            "description": f"Function `{d['qualified_name']}` at {d['file']}:{d['line']} has zero callers.",
            "priority": 5,  # Low priority — tech debt
            "category": "technical_debt",
            "source": "dead_code_detection",
            "metadata": {"qualified_name": d["qualified_name"], "file": d["file"], "line": d["line"]},
        })
    return items
```

## Files Modified (Summary)

| File | Change |
|------|--------|
| `backend/requirements.txt` | Add `code-review-graph>=2.3.0` |
| `backend/app/services/code_graph_service.py` | **NEW** — singleton service + daemon |
| `backend/main.py` | Register daemon (~line 449) |
| `backend/app/services/learning_engine.py` | Add source #5 (~line 192) |
| `backend/app/services/sprint_quality_grader.py` | Add 8th dimension, rebalance weights |
| `backend/app/services/work_discovery_service.py` | Add source #11 |
| `docker-compose.yml` | Add `ENABLE_CODE_GRAPH`, `CODE_GRAPH_INTERVAL_SECONDS` env vars |

## Verification

1. **Daemon startup**: After rebuild, check logs for `[OK] Code graph daemon starting`. First build should log `[CodeGraph] Initial build: N files, M nodes` within 30s.

2. **Learning enrichment**: After next organic LLM call, check Prometheus for `legion_learning_engine_sources_injected{source="structural_graph"}` incrementing.

3. **Grader dimension**: Force-grade a recent sprint via `POST /api/sprints/{id}/grade`. Response should include `structural_risk` in dimensions.

4. **Work discovery**: Trigger via `GET /api/agentic/work/3?max_items=20`. Should include items with `source="dead_code_detection"` if any dead code exists.

5. **Blast radius smoke test**: `docker exec legion-backend python -c "import asyncio; from app.services.code_graph_service import get_code_graph_service; svc = get_code_graph_service(); print(asyncio.run(svc.get_blast_radius(['backend/app/services/unified_llm_service.py'])))"` — should return affected files + risk scores.

## Rollback

- Set `ENABLE_CODE_GRAPH=false` in docker-compose → daemon stops, all 4 integration points gracefully return None/skip
- The 4 integration points use lazy imports + try/except — if `code-review-graph` package fails to install, Legion continues unchanged
- Grader returns `(70, {"graph_available": False})` when graph service unavailable — neutral score, doesn't penalize
