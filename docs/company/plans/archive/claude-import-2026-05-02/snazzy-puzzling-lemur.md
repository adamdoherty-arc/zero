# Ollama Experiment Loop: Grading Framework + OllamaExperimentAgent + legion-ollama-experimenter Skill

## Context

**Why now**: The Learn-18 → Learn-19 roadmap (`radiant-wandering-rabbit.md`) brought Ollama back online for 4 Tier 1 sources at 10% canary and pre-wired 5 Tier 2 dormant rows at 0%. The plumbing is in place, but **nobody owns the loop**. Every layer (routing, recording, eval, verifier, frontend, metrics, alerts) is a separate service maintained by a different sprint, and there is no single grade that says "the Ollama re-introduction is X% of the way to 100." The user's request is to (a) measure that grade across every layer of the loop, (b) build a specialized agent that runs the loop autonomously, and (c) ship a Claude Code skill that grades the loop, surfaces gaps, and (optionally) creates fix sprints.

**The "AutoAgent" question is resolved**: User stated AutoAgent files were pulled from https://github.com/hkuds/AutoAgent, but two exhaustive searches found nothing in the Legion repository. The existing `radiant-wandering-rabbit.md` (Learn-18 → Learn-21 roadmap) already documents the decision: AutoAgent has a hard `litellm==1.55.0` dependency that Recovery-01 explicitly removed, Ollama support is broken upstream, and "decision (per user direction): steal the 3 best ideas natively, don't run AutoAgent at all." This plan therefore proceeds without an AutoAgent dependency and treats the harvested ideas (NL workflow synthesis, GEPA tool generation, zero-code sprint UI) as Learn-20/Learn-21 work.

**Intended outcome**:
1. A 12-layer grading framework that scores the Ollama experiment loop 0-100 per layer + an overall composite, persisted append-only and trended over time.
2. A new `OllamaExperimentAgent` registered in `agent_registry.py` that owns the experiment loop end-to-end: dice-roll source picks, Welch t-test verdicts, Tier-2-activation gate checks, prompt evolution proposals, and auto-rollback of regressions.
3. A new `legion-ollama-experimenter` Claude Code skill modeled after `legion-watchdog` that grades all 12 layers, identifies the lowest-scoring layer, proposes fixes, and supports both `--report` (default, read-only) and `--create-sprints` (autonomous, files PLANNED sprints) modes.
4. A markdown documentation file at `backend/docs/ollama_experiment_loop.md` describing the system end-to-end so future operators (and the next compaction round) have a single source of truth.

This plan does NOT modify the existing canary infrastructure, the verifier, the frontend, or any of the Learn-18/19 routing rows. It only adds (a) a grader, (b) an agent, (c) a skill, and (d) a doc.

---

## The 12-layer grading framework

Each layer is scored 0-100. Composite is weighted average. Persisted append-only to `.claude/skills/legion-ollama-experimenter/knowledge/grade_history.json`.

| # | Layer | What it measures | Source of truth | Weight |
|---|-------|------------------|-----------------|--------|
| 1 | **Routing — gate enforcement** | `_enforce_provider_gate` rejects all non-allowlisted Ollama calls; `legion_llm_provider_override_total{reason="leak"}` is 0 | `/metrics`, `llm_call_details` 24h | 10 |
| 2 | **Routing — pre-authorization** | `pre_authorized` counter increments at the dice-roll rate (~10% per Tier 1 source); no double dice-roll race | `legion_llm_provider_override_total{reason="pre_authorized"}` | 8 |
| 3 | **Recording — `prompt_template_id` capture** | `llm_call_details` rows with `prompt_template_id NOT NULL` as a fraction of all calls; target ≥10% (Learn-17 measured 0.25%) | `SELECT COUNT(*) FILTER (...) / COUNT(*) FROM llm_call_details WHERE created_at >= now() - interval '24h'` | 12 |
| 4 | **Recording — provider/source/task_type** | `provider`, `source`, `task_type` columns NOT NULL on every row in last 24h | Same query | 6 |
| 5 | **Eval — PromptEvaluator daemon liveness** | Daemon's last cycle within 15 min; `Batch complete: N reviewed, X flagged, avg=N` log line shows non-None avg | `legion_prompt_evaluator_cycles_total`, container logs | 8 |
| 6 | **Eval — LLMReview daemon liveness** | Same shape but 5-min cycle; `_sanitize_review_text()` is hot path; no NameError-class silent kills | `legion_llm_review_cycles_total`, container logs | 6 |
| 7 | **Eval — TextGrad fire-and-forget** | `improvement_source='textgrad'` rows accruing in last 24h; `legion_textgrad_critiques_total` non-zero | DB count + Prometheus | 6 |
| 8 | **Verifier — FeedbackLoopVerifier** | `/api/prompt-manager/verification/run` returns `total_verified > 0` OR documents `insufficient_data` honestly; `legion_provider_override_rolled_back_total` rate is bounded | Endpoint + Prometheus rate | 12 |
| 9 | **Frontend — Provider Overrides panel** | `/api/prompt-manager/templates/provider-overrides` returns 9 rows (4 T1 + 5 T2); panel renders Tier badges + Savings column without 5xx | curl + browse skill smoke | 6 |
| 10 | **Metrics — Prometheus surface** | All 6 expected counters/gauges present at `/metrics` with HELP+TYPE AND at least one sample row (anchored grep `^legion_…`) | `curl /metrics \| grep -E '^legion_(llm_provider_override\|provider_override_rolled_back\|llm_cost_savings\|improvements_)`' | 8 |
| 11 | **Alerts — Prometheus rules loaded** | Both `OllamaProviderOverrideQualityRegression` and `OllamaCallLatencyHigh` show `state=inactive` (or `firing` if a real regression); not `unloaded` | `curl prometheus:9090/api/v1/rules` | 6 |
| 12 | **Tier 2 activation gate** | 4 of 4 gate criteria met: (a) zero rollbacks for any Learn-18 source over 7d, (b) verifier verdict for ≥2 of 4 Tier 1 sources OR documented insufficient_data, (c) Sprint Creation Gate stays in `safe` mode, (d) 14d Fix- failure rate ≤ 0.05 | DB queries + `/health` + `/metrics` | 12 |

**Composite**: `sum(layer_score * weight) / sum(weights)`, rounded to 0.1.

**Grade bands**:
- 90-100: PRODUCTION-READY — flip Tier 2 to pct=10
- 70-89: STABLE — keep Tier 1 running, monitor Tier 2 dormant savings
- 50-69: DEGRADED — investigate lowest-scoring layer before any expansion
- 0-49: BROKEN — page operator, do not auto-create sprints

---

## OllamaExperimentAgent — design

**File**: `backend/app/agents/ollama_experiment_agent.py` (NEW)

**Registration**: `backend/app/agents/agent_registry.py` — add new entry under `AgentCategory.LEARNING` with priority `MEDIUM`. Pattern mirrors `prompt_evaluator_agent` and `llm_review_agent`.

**Agent class**: subclasses `BaseAgent` (NOT `BaseLearningAgent` — learning agents fan out via the council; this agent owns a single autonomous loop).

**Owned responsibilities**:
1. **Grade the loop** — calls a private `_compute_grade()` method that walks all 12 layers and returns a `LoopGrade` dataclass (composite + per-layer + bottleneck-layer name).
2. **Run the verifier** — wraps `feedback_loop_verifier.run_verification_cycle()` and persists the verdict to `prompt_improvements` (already does this; agent just schedules and reports).
3. **Check Tier 2 activation gate** — executes the 4-criteria check from Learn-19 against live data; if all 4 pass, log `[OllamaExperiment] Tier 2 gate PASSED — operator action recommended` and write a single Prometheus gauge `legion_ollama_tier2_gate_passed{template_id}=1`. **Does NOT auto-bump pct** — the gate-pass is operator-visible, not agent-actuated, per Recovery-01 constraint.
4. **Detect leaks** — query `llm_call_details WHERE provider='ollama' AND source NOT IN (allowlist) AND created_at >= now() - interval '15 minutes'`. If count > 0, log a warning and increment `legion_ollama_leak_calls_total{source}`.
5. **Propose prompt evolutions** — if a Tier 1 source has ≥50 calls in 7d AND `avg(review_score) < 60`, mark that source as a candidate for Learn-16 GEPA evolution by writing a row to a NEW append-only table `ollama_evolution_candidates` (or, if creating a table is too heavy, write to `agentic_loop_decisions` with `decision_type='ollama_evolution_candidate'`). Keep this **read-only by default** — actual GEPA invocation requires `ENABLE_DSPY_EVOLUTION=true` which is the operator's explicit opt-in.
6. **Cycle**: every 30 min (env var `OLLAMA_EXPERIMENT_INTERVAL_SECONDS`, default 1800). Cycle is supervised via existing `_supervised_task` pattern in `task_health_registry` with `kind="daemon"`.
7. **Failure-soft**: every step wraps in `try/except logger.warning(f"[OllamaExperiment] step X failed: {e}")` so the agent never crashes the daemon. Outermost catch is `logger.warning`, NEVER `logger.debug` (Learn-14 post-verification rule — silent excepts hide pre-existing bugs).

**Functions to reuse (DO NOT reimplement)**:
- `prompt_manager_service.list_provider_overrides()` ([prompt_manager_service.py:625-719](backend/app/services/prompt_manager_service.py#L625-L719)) — already returns enriched rows with tier + calls_7d + savings_7d_usd.
- `feedback_loop_verifier.run_verification_cycle()` — already does Welch t-test, p<0.1 gate, 24h cooldown.
- `unified_llm_service.execute()` for any LLM call the agent itself makes (use `_source="ollama_experiment_agent"` and add to `LLM_EXEMPT_SOURCES` to prevent self-referential critique loop, mirroring Learn-14's `textgrad_critic`/`dspy_optimizer`/`feedback_verifier` exemptions).
- `metrics_service` module-level singleton for ALL Prometheus increments. NEVER call a non-existent helper like `get_metrics_service()` (Learn-18 import bug).
- `LLMCallDetailDB` from `app.models.llm_call_detail` (SINGULAR — module file is `llm_call_detail.py`, table is `llm_call_details`. Learn-19 import bug.)
- `task_health_registry.register("ollama_experiment", task, kind="daemon")` for supervised lifecycle.

**Wiring point**: `backend/main.py` near the Learn-17 verifier hook, gated by env var `ENABLE_OLLAMA_EXPERIMENT_AGENT=true` (default true). Pattern mirrors the DSPy daemon registration: log `[--] OllamaExperimentAgent disabled` when off, `[OK] OllamaExperimentAgent daemon starting` when on.

---

## legion-ollama-experimenter — new skill

**Directory**: `c:\code\Legion\.claude\skills\legion-ollama-experimenter\` (NEW)

**Files** (mirrors `legion-watchdog` v2.0.0 conventions):
```
SKILL.md                              — frontmatter v1.0.0 + invocation guide
knowledge/
  grade_history.json                  — append-only (composite + per-layer over time)
  grade_dimensions.json               — current weights + thresholds (editable)
  experiment_history.json             — append-only (each invocation: timestamp, mode, composite, bottleneck, sprints_created)
  improvement_patterns.md             — accumulated playbook (e.g., "if layer 3 < 50, the fix is X")
  layer_playbooks.md                  — per-layer remediation steps (e.g., "layer 1 leak → check `_resolve_pre_routing_override` for new lazy import")
  README.md                           — short orientation for the next reader
```

**Frontmatter** (top of `SKILL.md`):
```yaml
---
name: legion-ollama-experimenter
description: Grade and improve the Ollama re-introduction experiment loop. Reviews 12 layers (routing, recording, eval, verifier, frontend, metrics, alerts, Tier 2 gate). Supports report-only and sprint-creation modes. Use when asked to "grade the Ollama loop", "check the experiment status", "audit the Ollama re-introduction", or before flipping any Tier 2 canary_traffic_pct off dormant.
version: 1.0.0
metadata:
  legion:
    category: ml-experiment
    triggers: ["grade the ollama loop", "audit ollama experiment", "check tier 2 gate", "ollama experiment status"]
    requires: ["docker", "psql", "curl", "Read", "Bash", "Write"]
    autonomous: true
    capabilities: ["grade", "verify-gate", "detect-leaks", "create-sprints"]
---
```

**Invocation modes**:
- `--report` (DEFAULT): grades all 12 layers, prints composite + bottleneck + 3 highest-priority remediations, persists a row to `experiment_history.json`. Reads only.
- `--create-sprints`: same as `--report` PLUS, for any layer scoring below 70, files a PLANNED sprint via `POST /api/sprints/` (which goes through `manual_api` allowlist of the Sprint Creation Gate, so `safe` mode is honored). Sprint name format: `Improve-NN: Lift Ollama Experiment Layer {N} ({layer_name})`. Idempotent dedup on existing PLANNED/ACTIVE Improve sprints with the same target layer.
- `--gate-check`: skips grading, runs ONLY the 4-criteria Tier 2 activation gate check from Learn-19, returns pass/fail per criterion. Used as a pre-flight before manually bumping any Tier 2 row.

**Workflow** (the skill's SKILL.md prompt body):
1. **Snapshot** — `curl /health`, `curl /metrics`, `docker exec legion-db psql ...` for the 12 source-of-truth queries. Save raw outputs to `/tmp/ollama_grade_<timestamp>.json` for the audit trail.
2. **Score** — apply the per-layer scoring rules from `grade_dimensions.json`. Each layer scoring function is a small Python snippet inside the skill body (no separate runtime) executed via `Bash python -c`.
3. **Persist** — append `{timestamp, composite, layer_scores, bottleneck, mode, sprints_created}` to `grade_history.json`.
4. **Report** — print a colored ASCII table of all 12 layers + composite + bottleneck + remediation for the bottleneck (looked up in `layer_playbooks.md`).
5. **(optional) Create sprints** — if mode is `--create-sprints`, file PLANNED sprints for each layer below 70.
6. **Update knowledge** — if a new pattern emerges (e.g., a previously-unseen leak source), append to `improvement_patterns.md`.

**Source-of-truth queries** (skill embeds these, doesn't hardcode them in the agent):
```sql
-- Layer 3: prompt_template_id capture rate (24h)
SELECT
  (COUNT(*) FILTER (WHERE prompt_template_id IS NOT NULL))::float / NULLIF(COUNT(*), 0) AS capture_rate,
  COUNT(*) AS total_calls
FROM llm_call_details
WHERE created_at >= now() - interval '24 hours';

-- Layer 1: leak detection (15min)
SELECT source, COUNT(*) FROM llm_call_details
WHERE provider='ollama'
  AND source NOT IN ('prompt_evaluator','llm_review_agent','work_discovery','project_grader_docker_logs')
  AND created_at >= now() - interval '15 minutes'
GROUP BY source ORDER BY 2 DESC;

-- Layer 12: Tier 2 gate criterion (a) — rollback counter
SELECT increase(legion_provider_override_rolled_back_total{source=~"prompt_evaluator|llm_review_agent|work_discovery|project_grader_docker_logs"}[7d])
-- (queried via Prometheus, not psql)

-- Layer 12: Tier 2 gate criterion (d) — 14d Fix- failure rate
SELECT
  (COUNT(*) FILTER (WHERE status='FAILED'))::float / NULLIF(COUNT(*) FILTER (WHERE status IN ('FAILED','COMPLETED')), 0)
FROM sprints
WHERE name LIKE 'Fix-%' AND created_at >= now() - interval '14 days' AND status != 'CANCELLED';
```

**Knowledge file conventions** (matches existing skills):
- JSON files are **append-only** — never overwrite history.
- MD files (`improvement_patterns.md`, `layer_playbooks.md`) are edited by appending sections under `## YYYY-MM-DD — N` headers.
- `grade_dimensions.json` is the only mutable source of truth for layer weights — operator can re-tune without code changes.

---

## Documentation deliverable

**File**: `backend/docs/ollama_experiment_loop.md` (NEW)

**Sections**:
1. **System diagram** (ASCII) — 12 layers + arrows showing call flow from `unified_llm_service.execute()` → override hook → gate → tracker → eval → verifier → metrics → alerts.
2. **Per-layer source map** — file paths + line numbers for the 12 layers, lifted directly from this plan and from the Learn-18/19 memory entries.
3. **Operator playbook** — "How to bump a Tier 2 row off dormant", "How to add a new Tier 1 source", "How to rollback a leaked source", "How to interpret an `insufficient_data` verifier verdict".
4. **Known limits** — 0.25% `prompt_template_id` capture rate, orphan-placeholder verifier skip pattern, ambient task_type catch-all rows surfacing pre-existing traffic, MiniMax tool_call leakage in reviewer chain.
5. **Roadmap pointer** — link to `radiant-wandering-rabbit.md` for the Learn-18 → Learn-21 sprint chain.

This file is the single source of truth so a future operator (or compaction round) doesn't need to walk back through 5 sprint-history MEMORY.md entries to understand the loop.

---

## Critical files to modify

### NEW files (4)
- `backend/app/agents/ollama_experiment_agent.py` — agent class + cycle loop + 12-layer grader + 4-criterion gate check + leak detector + evolution candidate writer.
- `backend/docs/ollama_experiment_loop.md` — operator documentation with system diagram + per-layer source map + playbook.
- `.claude/skills/legion-ollama-experimenter/SKILL.md` — skill definition with frontmatter, invocation modes, workflow body.
- `.claude/skills/legion-ollama-experimenter/knowledge/{grade_history.json, grade_dimensions.json, experiment_history.json, improvement_patterns.md, layer_playbooks.md, README.md}` — append-only knowledge files seeded with empty arrays / starter playbooks.

### EXISTING files modified (3)
- `backend/app/agents/agent_registry.py` — register `OllamaExperimentAgent` under `AgentCategory.LEARNING` with priority `MEDIUM`. ~5 lines.
- `backend/main.py` — add daemon registration block near the Learn-17 verifier hook, gated by `ENABLE_OLLAMA_EXPERIMENT_AGENT=true`. Mirror the DSPy daemon `[--] disabled` / `[OK] starting` pattern. ~12 lines.
- `backend/app/services/unified_llm_service.py` — add `"ollama_experiment_agent"` to `LLM_EXEMPT_SOURCES` set (defensive add, mirrors Learn-14 reserved exemptions). 1 line.

### NO changes to (explicitly out of scope)
- The 12-layer infrastructure itself — no edits to `prompt_manager_service.py`, `feedback_loop_verifier.py`, `prompt_evaluator_agent.py`, `llm_review_service.py`, `metrics_service.py`, `alert_rules.yml`, `LLMConsole.tsx`, `useProviderOverrides.ts`, or any of the routing override rows.
- Migration files — no new Alembic migration. The optional `ollama_evolution_candidates` table is deferred; in this plan the agent writes evolution candidates as `agentic_loop_decisions` rows with `decision_type='ollama_evolution_candidate'`.
- Sprint Creation Gate mode — stays at `safe`. The skill's `--create-sprints` mode uses `manual_api` allowlist, which is whitelisted in `safe` mode.

---

## Existing functions to reuse (verified live)

| Function | File | Purpose |
|----------|------|---------|
| `list_provider_overrides()` | [prompt_manager_service.py:625-719](backend/app/services/prompt_manager_service.py#L625-L719) | Returns enriched rows with `tier`, `calls_7d`, `savings_7d_usd`. Per-row try/except already isolates failures. |
| `get_provider_override(source, task_type)` | [prompt_manager_service.py:432-484](backend/app/services/prompt_manager_service.py#L432-L484) | Returns `(provider_name, template_id)` 2-tuple — agent uses this to compute hit rates for Layer 2 scoring. |
| `_resolve_pre_routing_override()` | [unified_llm_service.py:402-447](backend/app/services/unified_llm_service.py#L402-L447) | Pre-routing hook — agent reads source set from this to detect leaks (sources NOT in this allowlist that still produce Ollama rows). |
| `_enforce_provider_gate()` | [unified_llm_service.py:287-399](backend/app/services/unified_llm_service.py#L287-L399) | Layer 1 source of truth — agent checks `legion_llm_provider_override_total{reason}` labels emitted by this function. |
| `feedback_loop_verifier.run_verification_cycle()` | `backend/app/services/feedback_loop_verifier.py` | Welch t-test, p<0.1 gate, 24h cooldown — agent calls this directly for Layer 8 scoring. |
| `_LEARN19_MINIMAX_COST_PER_CALL_USD = 0.002` | `unified_llm_service.py` (module level) | Cost constant — agent uses this for any savings projection it surfaces. Mirrored in `LLMConsole.tsx` for the IIFE banner. |
| `task_health_registry.register(name, task, kind="daemon")` | `backend/app/services/task_health_registry.py` | Supervised lifecycle — agent registers itself this way so the existing supervisor handles crash backoff. |
| `metrics_service` (module-level singleton) | [metrics_service.py:1-20](backend/app/services/metrics_service.py#L1-L20) | All Prometheus increments. NEVER use a `get_metrics_service()` helper — it doesn't exist (Learn-18 bug). |
| `LLMCallDetailDB` | `backend/app/models/llm_call_detail.py` (SINGULAR) | DB model — module file is singular, table is plural. Learn-19 import bug. |
| `_supervised_task()` | `backend/app/services/task_health_registry.py` | Sliding-window backoff (1h window). Agent's cycle loop runs inside this wrapper. |

---

## Verification

After implementation, all of the following must be objectively verified before declaring the work done. Each step has a precise pass condition.

### Phase A — Smoke (5 min after deploy)
1. **Backend health**: `curl http://localhost:8005/health` returns 200, `database: connected`, `sprint_creation_mode: safe`.
2. **Agent registration**: `docker exec legion-backend python -c "from app.agents.agent_registry import get_agent; print(get_agent('OllamaExperimentAgent'))"` prints a non-None object.
3. **Daemon startup log**: `docker logs legion-backend --tail 100 | grep -i "ollama_experiment"` shows either `[OK] OllamaExperimentAgent daemon starting` or `[--] OllamaExperimentAgent disabled` depending on env var. **Both are pass states**.
4. **Spontaneous-fire rule (Recovery-01 / Learn-18)**: if enabled, the first cycle log line `[OllamaExperiment] cycle complete: composite=NN.N bottleneck=layer_K` must appear within **2 minutes** of startup. If it does not, the wiring is broken — investigate before proceeding.

### Phase B — Skill (15 min)
5. **Skill discovery**: `ls .claude/skills/legion-ollama-experimenter/SKILL.md` exists and frontmatter parses cleanly.
6. **`--report` mode** (default, read-only): invoke the skill via Skill tool with no args. Must print a 12-row colored ASCII table with composite score and bottleneck name. Must append exactly one row to `knowledge/grade_history.json`. Must NOT create any sprints. Must NOT modify any DB rows outside its own knowledge files.
7. **`--gate-check` mode**: invoke with `--gate-check`. Must print 4 criteria with PASS/FAIL/INSUFFICIENT_DATA verdicts. Must NOT touch grade_history.
8. **`--create-sprints` mode** (only run if Phase B6 shows the bottleneck score < 70): invoke with `--create-sprints`. Must file exactly one PLANNED sprint via `POST /api/sprints/` with name format `Improve-NN: Lift Ollama Experiment Layer {N} ({layer_name})`. Re-running the skill within 5 minutes must NOT create a duplicate (idempotent dedup).

### Phase C — Grade reality check (1 hour)
9. **First grade snapshot**: read the row just appended to `grade_history.json`. The composite score MUST be in the 70-89 band (STABLE). Anything below 70 means a critical layer is broken — investigate before continuing. Anything above 90 means the grader is over-scoring (likely a layer is passing when it shouldn't); review the per-layer scores for false positives.
10. **Per-layer sanity**: verify Layer 3 (`prompt_template_id` capture) honestly reports the known 0.25% sparseness — if it reports 100%, the query is wrong.
11. **Leak detection sanity**: Layer 1 should report 0 leaks if Learn-18's allowlist is complete. If it reports any, the agent has caught a real bug — investigate the source name and either add to allowlist or fix the bypass.

### Phase D — 24h soak
12. **Stability**: agent must run 48 cycles (30-min cycle × 24h) without crashing the daemon. Verify via `task_health_registry` showing `kind="daemon", crashes_in_window=0`.
13. **Grade trend**: read last 48 rows from `grade_history.json`. Composite must not drift more than ±5 points across the soak window. A sudden drop ≥ 10 points in a single cycle is a real regression — investigate.
14. **Verifier liveness**: at least 1 of the 48 cycles must include a verifier run that returned a non-`insufficient_data` verdict for at least 1 source (or the 7d gate criteria check must explicitly note that all 4 sources are still in `insufficient_data` — that's acceptable per Learn-17's known limit).

### Phase E — Idempotence + safety
15. **Repeated `--report` does not pollute grade_history**: invoke the skill 10 times in a row. Verify exactly 10 rows added — no duplicates, no overwrites.
16. **`--create-sprints` is safe in `safe` mode**: backend's `/health` continues to report `sprint_creation_mode: safe`. Sprint creation gate did not flip. The created Improve sprints came through `manual_api` allowlist as expected.
17. **Reversibility**: `ENABLE_OLLAMA_EXPERIMENT_AGENT=false` env var → restart → daemon stops cleanly, no orphaned cycles, no Prometheus counter for the agent's own activity continuing to increment.

---

## Out of scope (explicitly deferred)

- **Auto-bumping Tier 2 rows off dormant**: agent surfaces the gate-pass but does NOT actuate `bumpCanaryPct()`. Operator action remains the gate.
- **Actually invoking GEPA evolution**: agent writes "evolution candidate" rows but does NOT call the DSPy daemon or flip `ENABLE_DSPY_EVOLUTION`. That stays operator-gated.
- **AutoAgent integration**: per `radiant-wandering-rabbit.md`, the decision is "harvest 3 ideas natively, do not depend on AutoAgent." This plan does not change that.
- **New Alembic migration**: the optional `ollama_evolution_candidates` table is deferred; in v1 the agent reuses `agentic_loop_decisions` with a custom `decision_type`.
- **Frontend changes**: the existing LLMConsole Provider Overrides panel already exposes everything the agent needs to read. No new frontend pages or hooks.
- **New Prometheus metrics beyond `legion_ollama_leak_calls_total{source}` and `legion_ollama_tier2_gate_passed{template_id}`**: keep the new metric surface minimal.

---

## Open questions for after approval

None blocking. Two operational questions to revisit during implementation:
1. Where does `legion_ollama_tier2_gate_passed` get reset after a flip? (Probably never — it's a one-shot signal, and the operator clears it by deploying the bumped pct.)
2. Should the agent's evolution-candidate rows have a TTL? (Default: no — append-only, let the operator review and clear manually.)
