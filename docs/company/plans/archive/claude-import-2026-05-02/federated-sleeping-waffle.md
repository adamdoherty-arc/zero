# Plan: Learn-20 — Slash MiniMax Costs: Local-First LLM Strategy

## Context

MiniMax + Kimi are costing ~$55/week ($7.90/day). The goal is 100% local execution.

**Current 7-day cost breakdown (measured):**
| Provider | Calls | Est. Cost | % of Total |
|----------|-------|-----------|------------|
| MiniMax  | 19,689 | $39.38 | 73% |
| Kimi     | 5,313  | $15.94 | 24% |
| Ollama   | 1,934  | $0.00  | 3% |
| **Total** | **26,936** | **$55.32** | |

**Top cost sources (MiniMax + Kimi combined):**
| Source | Calls (7d) | % of Cloud | Task Type | Uses Structured Output |
|--------|-----------|------------|-----------|----------------------|
| `prompt_evaluator` | 19,551 | **74%** | GENERAL | Yes (execute_structured) |
| `llm_review_agent` | 2,430 | **9%** | planning | Yes |
| `sprint_tool` | 835 | 3% | mixed | No |
| `planning_cortex` | 686 | 3% | PLANNING | Yes |
| `agent:code_reviewer` | 324 | 1.3% | code_review | No |
| `claude_executor` | 233 | 0.9% | mixed | No |
| `textgrad_critic` | 214 | 0.9% | GENERAL | Yes |
| `annotation_queue` | 182 | 0.7% | GENERAL | Yes |

**Key insight**: `prompt_evaluator` alone = 74% of ALL cloud costs. It's a background daemon that does not need cloud models. Learn-18/19 overrides only divert 10% of its traffic to Ollama.

**Current local models (already pulled in Ollama):**
- `qwen3-coder-next` (51.7GB, 80B MoE / 3B active) — execution workhorse
- `qwen3.5:35b-a3b` (23.9GB, 36B MoE / 3B active) — already loaded, untested for planning
- `nomic-embed-text-v2-moe` (1.0GB) — embeddings

**Planning blocker**: qwen3-coder-next has broken structured JSON output in Ollama (GitHub #13206) and no thinking mode. Cannot reliably replace MiniMax for planning/decomposition tasks. BUT the Learn-18/19 override path IS working at 10% (1,934 calls, 0 rollbacks) because `execute_structured` has 3x retry.

## Strategy: 3-Phase Cost Reduction

### Phase 1: Ramp Overrides to 100% (DB-only, no code changes)
**Expected savings: ~$35/week (64% reduction)**

The 9 Learn-18/19 override rows already work at `canary_traffic_pct=10` with zero rollbacks. Ramp them to 100%:

```sql
-- Ramp all 9 Learn-18/19 override rows from 10% to 100%
UPDATE prompt_templates
SET canary_traffic_pct = 100
WHERE evolved_by IN ('learn18_seed', 'learn19_seed');
```

This captures:
- `prompt_evaluator` (74% of costs) → Ollama
- `llm_review_agent` (9%) → Ollama
- `agent:code_reviewer` (1.3%) → Ollama
- `work_discovery`, `project_grader_docker_logs`, `documentation`, `analysis-wide`, `external_knowledge_cross_ref`, `task_orchestration_evaluate` → Ollama

**Verification**: After ramp, check `SELECT provider, COUNT(*) FROM llm_call_details WHERE created_at > NOW() - INTERVAL '1 hour' GROUP BY provider` — Ollama count should dominate.

**Rollback**: `UPDATE prompt_templates SET canary_traffic_pct = 10 WHERE evolved_by IN ('learn18_seed', 'learn19_seed');`

### Phase 2: Cover Remaining High-Volume Sources (code changes)
**Expected savings: ~$8/week additional**

Add new provider override rows for sources NOT yet covered by Learn-18/19:

| Source | 7d Calls | Action |
|--------|----------|--------|
| `sprint_tool` | 835 | New override row, pct=100 |
| `textgrad_critic` | 214 | Already in LLM_EXEMPT_SOURCES — skip (it's self-referential) |
| `annotation_queue` | 182 | New override row, pct=100 |
| `claude_executor` | 233 | New override row, pct=100 |
| `sprint_execution` | 75 | New override row, pct=100 |
| `chain_grade_analysis` | 42 | New override row, pct=100 |
| `project_grader_structured` | 38 | New override row, pct=100 |
| `llm_endpoint` | 21 | Skip — user-facing, keep on MiniMax |

**Implementation**: Insert 6 new `prompt_templates` rows with `provider_override='ollama'`, `source_filter=<source>`, `canary_traffic_pct=100`, `evolved_by='learn20_seed'`.

**Files modified**:
- `backend/app/services/prompt_manager_service.py` — update `list_provider_overrides()` tier detection to include `'learn20-'` prefix as `'T3'`

### Phase 3: Fix TIER_ALIASES + Route Planning Locally (code changes)
**Expected savings: remaining ~$12/week (planning + Kimi)**

Currently ALL tier aliases point to MiniMax M2 (Recovery-01 Phase 1). This was needed when Ollama was disabled, but Ollama has been stable for 2+ weeks now.

**3a. Fix TIER_ALIASES** in [legion_config.py](backend/app/core/legion_config.py):
```python
# Before (Recovery-01 Phase 1 — ALL tiers → MiniMax):
TIER_ALIASES = {
    "primary": ModelType.MINIMAX_M2,
    "sonnet":  ModelType.MINIMAX_M2,
    "opus":    ModelType.MINIMAX_M2,
    "haiku":   ModelType.MINIMAX_M2,
}

# After (Learn-20 — Ollama primary, MiniMax for complex planning only):
TIER_ALIASES = {
    "primary": ModelType.OLLAMA_QWEN_CODER_NEXT,
    "sonnet":  ModelType.OLLAMA_QWEN_CODER_NEXT,
    "opus":    ModelType.MINIMAX_M2,    # Keep for explicit "give me the best" requests
    "haiku":   ModelType.OLLAMA_QWEN_CODER_NEXT,
}
```

**3b. Route PLANNING/ARCHITECTURE to Ollama with MiniMax fallback** in [legion_config.py](backend/app/core/legion_config.py):
```python
# Before:
TASK_MODEL_ROUTING = {
    TaskType.PLANNING:     [_MM, _KI],  # MiniMax first, Kimi fallback
    TaskType.ARCHITECTURE: [_MM, _KI],
    TaskType.RESEARCH:     [_MM, _KI],
    ...
}

# After (Learn-20 — Ollama first for everything, MiniMax fallback):
TASK_MODEL_ROUTING = {
    TaskType.PLANNING:     [_OQ, _MM],  # Ollama first, MiniMax fallback
    TaskType.ARCHITECTURE: [_OQ, _MM],
    TaskType.RESEARCH:     [_OQ, _MM],
    ...  # execution types already [_OQ, _MM]
}
```

**3c. Update PLANNING_MODEL constant**:
```python
PLANNING_MODEL: ModelType = ModelType.OLLAMA_QWEN_CODER_NEXT  # was MINIMAX_M2
```

**Risk assessment**: Planning quality may degrade with qwen3-coder-next (3B active params, no thinking mode). Mitigations:
1. MiniMax stays as fallback in routing table — if Ollama fails structured output, it retries then falls back
2. `planning_cortex` and `brain:plan_vote` are only 3% of costs — if quality degrades, we can add specific override rows that force these back to MiniMax
3. qwen3.5:35b-a3b is already pulled (23.9GB) — could be registered and used as planning model if qwen3-coder-next struggles

## Files Modified

| File | Action | Change |
|------|--------|--------|
| [legion_config.py](backend/app/core/legion_config.py) | MODIFY | Fix TIER_ALIASES, update TASK_MODEL_ROUTING, update PLANNING_MODEL |
| [prompt_manager_service.py](backend/app/services/prompt_manager_service.py) | MODIFY | Add 'T3' tier detection for `learn20-` prefix |
| DB (prompt_templates) | SQL | Ramp 9 existing rows to pct=100, insert 6 new T3 override rows |

## Verification

1. **Phase 1 verify**: After ramp SQL, wait 5 min, then:
   ```sql
   SELECT provider, COUNT(*) FROM llm_call_details
   WHERE created_at > NOW() - INTERVAL '30 minutes'
   GROUP BY provider;
   ```
   Expect: Ollama >> MiniMax (was opposite before)

2. **Phase 2 verify**: After inserting T3 rows + backend rebuild:
   ```bash
   curl -s http://localhost:8005/api/prompt-manager/overrides | python -c "import json,sys; data=json.load(sys.stdin); print(len(data), 'override rows')"
   ```
   Expect: 15 rows (9 existing + 6 new)

3. **Phase 3 verify**: After config changes + backend rebuild:
   ```bash
   # Check planning routes to Ollama
   docker logs legion-backend --tail 100 2>&1 | grep -i "planning_cortex\|brain:plan_vote"
   ```
   Expect: `provider=ollama` in log lines

4. **Cost verify** (after 24h):
   ```sql
   SELECT provider, COUNT(*),
          ROUND(SUM(CASE WHEN provider='minimax' THEN 0.002
                         WHEN provider='kimi' THEN 0.003 ELSE 0 END)::numeric, 2) as cost
   FROM llm_call_details WHERE created_at > NOW() - INTERVAL '1 day'
   GROUP BY provider ORDER BY cost DESC;
   ```
   Target: MiniMax < 500 calls/day (was ~2,800), Kimi < 200 (was ~760), Ollama > 3,000

5. **Quality gate**: Monitor rollback counter for 24h:
   ```sql
   SELECT COUNT(*) FROM rollback_history WHERE created_at > NOW() - INTERVAL '1 day';
   ```
   If any rollbacks appear, revert Phase 3 first (planning is highest risk).

## Expected Outcome

| Phase | Weekly Savings | Cumulative |
|-------|---------------|------------|
| Phase 1 (ramp overrides) | ~$35 | $35 (~64%) |
| Phase 2 (new overrides) | ~$8 | $43 (~78%) |
| Phase 3 (tier aliases + routing) | ~$12 | $55 (~100%) |

**Target**: $55/week → <$5/week (MiniMax as fallback only, not primary)
