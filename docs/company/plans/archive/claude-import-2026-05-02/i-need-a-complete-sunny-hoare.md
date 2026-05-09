# LLM Operations — Legion-owned cross-project initiative

## Context

The user runs three interconnected Python/FastAPI projects — **Zero** (`c:\code\zero`), **ADA** (`c:\code\ada`), **Legion** (`c:\code\legion`) — each of which calls LLMs through its own router. Each project is currently reporting errors, LiteLLM + vLLM usage is inconsistent, there is no unified view of cost/latency/success across the stack, and there is no mechanism to keep up with the fast-moving model landscape (Ollama, Hugging Face, OpenRouter, Anthropic, Google, Moonshot/Kimi, MiniMax).

Rather than fix this once and drift again, the user wants **Legion to permanently own this responsibility as a new managed project**. Legion already has a mature surface for that — `ProjectDB`, `SprintDB`/`SprintTaskDB`, an 80-agent registry with the "Clean-10" blueprint roles, APScheduler + croniter, an `AlertService` wired to Telegram, a multi-agent QA sign-off gate, `AutonomousBrain` 30s loop, and a `MANAGED_PROJECTS` config for cross-project polling. The plan reuses all of it.

Outcome: one new Legion project `llm-operations` with four agents, four DB tables, a scheduled daily cycle, a unified cross-project response trace, a daily model-discovery and health report delivered to Telegram, Langfuse as the shared observability plane, Promptfoo as the regression gate, and a test suite that proves Legion can run this indefinitely after this chat ends.

---

## Audit findings (current state)

### Zero — `c:\code\zero\backend`
- Router: `app/infrastructure/llm_router.py` (339 lines) + `app/infrastructure/unified_llm_client.py`.
- 7 providers — vLLM (primary @ `host.docker.internal:4444`), Ollama, Kimi k2.6, Gemini 3.1-pro, MiniMax M2.7, OpenRouter, HuggingFace.
- **LiteLLM not active** (only a stale `ZERO_LITELLM_URL` path in `vision_vlm_service.py`).
- Usage in `llm_usage` table (metadata only). Budget $5/day, reset via `scheduler_service`.
- `services/ecosystem_health_service.py` monitors Zero/Ada/Legion/Ollama/Reachy — but **not vLLM, Kimi, Gemini, MiniMax, OpenRouter, HF**.
- Tests: `backend/tests/infrastructure/test_llm_router_live.py`, `test_llm_router_backend_toggle.py`.

### ADA — `c:\code\ada\backend`
- Router: `infrastructure/llm_router.py` (1,747 lines, `OllamaLLMRouter` singleton) + `services/ada_llm_service.py`.
- Primary qwen3.6:35b-a3b-q4_K_M → MiniMax fallback; Kimi planning only.
- LiteLLM optional via `LITELLM_URL`; vLLM optional via `LOCAL_LLM_BACKEND=vllm`.
- Circuit breakers per provider; health router `routers/ai_health.py`.
- **Dead code to remove**: `backend/services/llm_client.py` (DeepSeekClient), `src/services/intelligent_llm_router.py`.
- Daily markdown logs — not queryable.

### Legion — `c:\code\legion\backend`
- `app/services/unified_llm_service.py` — two-tier (Kimi planning + vLLM execution + MiniMax fallback).
- LiteLLM **is** the transport layer via `docker/litellm/config.yaml` on `host.docker.internal:4444`. `LLMUsageDB` + `LLMCallDetailDB` tables. Langfuse enabled.
- **Bugs found in recent `logs.txt`:**
  - **B1** `UnifiedLLMService.generate()` missing — called from `autonomous_sprint_executor.py:478`; service exposes `.execute()`.
  - **B2** `QAPipelineService.run_sprint_validation(level=…)` signature drift at `autonomous_sprint_executor.py:1949`.
  - **B3** `litellm` unpinned in `backend/requirements.txt` — supply-chain risk.
  - **B4** `langsmith` drags in `pydantic.v1` → test collection fails on Python 3.14.

---

## 1. Rewritten prompt (clean spec, paste-ready)

**Project: LLM Operations**

- **Mission** — keep the LLM stack across Zero, ADA, and Legion healthy, current, observable, and cost-efficient as an always-on Legion project, not a one-off audit.
- **Owner** — Legion. Reuses Legion's `ProjectDB`, `SprintDB`, Agent Registry, `AlertService`, QA gate, APScheduler, Telegram notifier.
- **Managed surfaces** — Zero's `llm_router.py`/`unified_llm_client.py`; ADA's `llm_router.py`/`ada_llm_service.py`; Legion's `unified_llm_service.py`/`docker/litellm/config.yaml`.
- **G1 — Daily health check** — every 24h verify every provider endpoint, budget, circuit breaker, fallback rate, and router degradation across all three projects.
- **G2 — Daily model research** — pull fresh listings from Ollama, Hugging Face Hub, OpenRouter `/models`, and vendor release feeds; diff against a known catalog.
- **G3 — Unified response trace** — every LLM call from any project lands in `llm_response_trace` with hash, model, latency, cost, success, error type, project, agent.
- **G4 — Daily report** — one Markdown + JSON artefact per UTC day in `llm_daily_report`, delivered via Telegram + dashboard.
- **G5 — Self-improvement** — regressions (latency, fallback, success, cost) or interesting new models automatically open a Legion sprint via `llm_ops_planner`.
- **G6 — Fix-before-build** — B1–B4 land first.
- **G7 — Observability consolidation** — Langfuse + LiteLLM Router as shared layer; add Promptfoo for regression gating.
- **G8 — Dependency hygiene** — pin `litellm`, `langsmith`; add `huggingface-hub`, `langfuse>=3.0.0` in Legion.
- **G9 — QA gate** — `TASK_MODEL_ROUTING` or `MODEL_REGISTRY` changes require multi-agent QA sign-off.
- **G10 — Tests prove handover** — `pytest -k llm_ops` green end-to-end; Promptfoo runs in CI.
- **Non-goals** — replace project routers, fine-tune models, real-time human chat, GPU scheduling, prompt authoring UI.
- **Success criteria** — ≥14 consecutive daily reports without intervention, ingestion lag ≤1h and ≥99% coverage, ≥1 regression-or-discovery-driven sprint in the first 30 days, CI blocks Promptfoo regressions, dependencies pinned.

---

## 2. Pre-work: Legion bug fixes (must land first)

| ID | File:Line | Change | Test |
|---|---|---|---|
| **B1** | `backend/app/services/autonomous_sprint_executor.py:478` | Replace `self.llm_service.generate(...)` with `self.llm_service.execute(prompt=..., task_type="analysis", ...)` | `test_autonomous_sprint_executor.py::test_ai_analyze_and_suggest_fix_uses_execute` |
| **B2** | `backend/app/services/autonomous_sprint_executor.py:1949` | Read `services/enhanced_qa_pipeline.py` for current `run_sprint_validation` signature; drop `level=`, use new kwarg (likely `validation_profile=`) | `test_autonomous_sprint_executor.py::test_run_sprint_validation_kwargs` |
| **B3** | `backend/requirements.txt` | Pin `litellm==<latest stable>` (confirm with `pip index versions litellm`) | `test_dependency_pins.py::test_litellm_pinned` |
| **B4** | `backend/requirements.txt` | Pin `langsmith>=0.3.0,<0.4.0`; add `langchain-core>=0.3.0` if transitively dragged back | `test_dependency_pins.py::test_langsmith_pydantic_v2` |

CI gate: `pytest -k "pre_work or dependency_pins"` must be green before any new-project code merges.

---

## 3. New Legion project: `llm-operations`

### 3.1 ProjectDB row (Alembic data migration `20260425_llm_ops_project.py`)

| Field | Value |
|---|---|
| `name` | `LLM Operations` |
| `slug` | `llm-operations` |
| `path` | `c:\code\legion` |
| `tech_stack` | `["python","fastapi","sqlalchemy","apscheduler","litellm","langfuse","promptfoo"]` |
| `auto_sprint_enabled` | `true` |
| `autonomous_mode_enabled` | `true` |
| `status` | `active` |
| `architecture_summary` | one-paragraph summary (see §3.2) |

### 3.2 Product doc

Architecture: LLM Operations treats the three projects' LLM stacks as a single managed substrate. A daily scheduler fans out four agents (monitor → researcher → curator → report) with a fifth planner (`llm_ops_planner`) that opens Legion sprints on regressions or interesting discoveries. Cross-project response traces are pulled from each project's Postgres (`llm_usage`) into Legion's `llm_response_trace` (phase 1); phase 2 migrates to LiteLLM proxy callbacks flowing into Langfuse. Promptfoo gates prompt/model regressions in CI.

### 3.3 New DB tables — `backend/app/models/llm_ops.py` (migration `20260425_llm_ops_schema.py`)

**Decision: do not extend `LLMUsageDB` / `LLMCallDetailDB`.** They are Legion's internal write path. Aggregate side-by-side.

- **`llm_model_catalog`** — authoritative model record. Unique `(provider, model_id)`. Fields: `provider` enum, `model_id`, `display_name`, `context_window`, `input_cost_per_mtok_usd`, `output_cost_per_mtok_usd`, `capabilities` jsonb, `license`, `release_date`, `first_seen_at`, `last_seen_at`, `deprecated_at`, `source_url`, `notes`.
- **`llm_model_discoveries`** — daily diff rows. `scan_date`, `provider`, `model_id`, `discovery_type` enum (`new|reappeared|deprecated|capability_change|price_change`), `payload` jsonb, `catalog_id` FK.
- **`llm_response_trace`** — unified cross-project log (metadata only; `prompt_hash` = sha256 or proxy). Unique `(project, source_row_id)` for idempotent pull. Monthly partitions, 12-month retention. Indexes on `(project, created_at_src DESC)`, `(provider, model, created_at_src DESC)`, `(success, created_at_src DESC)`.
- **`llm_daily_report`** — unique on `report_date`. Fields: `summary_md`, `metrics` jsonb, `findings_ids` jsonb array, `telegram_message_id`, `generated_at`.
- **`llm_ingest_cursor`** — small checkpoint table: `project` PK, `last_created_at`.

Seed `llm_model_catalog` in the migration from Legion's `MODEL_REGISTRY` in `backend/app/core/legion_config.py` so day-1 diffs are meaningful.

### 3.4 Agents — new blueprint role `llm_ops`

All subclass `BaseAgent`, register in `backend/app/agents/agent_registry.py::AGENT_REGISTRY`.

| Agent | Role | File | Purpose |
|---|---|---|---|
| `LLMStackMonitorAgent` | `llm_ops.monitor` | `backend/app/agents/llm_ops/stack_monitor.py` | Probe each project's health endpoints + TCP/HTTP probes of vLLM/Kimi/Gemini/MiniMax/OpenRouter/HF (filling Zero's monitoring gap). Emits `health_finding_snapshot` rows via `AlertRule`. |
| `ModelResearcherAgent` | `llm_ops.research` | `backend/app/agents/llm_ops/model_researcher.py` | Per-provider `ProviderAdapter.fetch()` against Ollama, HF Hub, OpenRouter, vendor feeds; diffs against catalog; writes `llm_model_discoveries`. |
| `LLMResponseCuratorAgent` | `llm_ops.curate` | `backend/app/agents/llm_ops/response_curator.py` | Pull ingestion from Zero + ADA Postgres (ON CONFLICT DO NOTHING); computes p50/p95/p99, success rate, fallback rate, cost/success; 7-day Z-score regression detection. |
| `LLMReportGeneratorAgent` | `llm_ops.report` | `backend/app/agents/llm_ops/report_generator.py` | Jinja template → `llm_daily_report` row + Telegram (via `notify-telegram.sh`) + WS broadcast. Idempotent re-runs edit Telegram message by ID. |
| `LLMOpsPlannerAgent` | `llm_ops.plan` | `backend/app/agents/llm_ops/planner.py` | On regression severity ≥ medium OR interesting discovery → create `SprintDB` + `SprintTaskDB` tagged `model_promotion`, `requires_qa_signoff=true`. |

**Supporting API changes:**
- Add `UnifiedLLMService.health_snapshot()` in `backend/app/services/unified_llm_service.py`.
- Add `ProjectDB.get_by_slug()` helper if missing.
- Add `app/routers/llm_ops.py` with `/api/llm-ops/reports/latest`, `/api/llm-ops/discoveries`, `/api/llm-ops/trace/summary`.

### 3.5 Scheduler wiring — `backend/app/scheduler/llm_ops_jobs.py`

All jobs registered with `task_health_registry.register_task(...)` and priority `background`.

| Job | Cron (UTC) |
|---|---|
| `llm_ops.monitor.hourly` | `5 * * * *` |
| `llm_ops.curator.hourly` | `15 * * * *` |
| `llm_ops.monitor.daily` | `0 8 * * *` |
| `llm_ops.researcher.daily` | `10 8 * * *` |
| `llm_ops.curator.daily` | `20 8 * * *` |
| `llm_ops.report.daily` | `30 8 * * *` |
| `llm_ops.planner.daily` | `40 8 * * *` |

### 3.6 Ingestion — **Pull (primary)**

Chosen over push-webhooks (too chatty; touches hot path) and LiteLLM callback (phase 2; requires code change in Zero + ADA).

- Add `LEGION_READONLY_ZERO_DB_URL` and `LEGION_READONLY_ADA_DB_URL` to secrets.
- Curator opens read-only SQLAlchemy engines (`pool_size=1, pool_pre_ping=True`).
- `SELECT id, provider, model, task_type, prompt_tokens, completion_tokens, cost_usd, latency_ms, success, error_message, created_at FROM llm_usage WHERE created_at > :since AND created_at < :until ORDER BY id ASC LIMIT 10000`.
- Checkpoint `(project, max(created_at))` in `llm_ingest_cursor`.
- Idempotent insert into `llm_response_trace` with `ON CONFLICT (project, source_row_id) DO NOTHING`.
- Also parse ADA's `/c/code/ada/logs/daily/*.md` as a fallback source for any calls that never reached a DB.

### 3.7 Phase 2 — LiteLLM proxy standardization

After 30 days stable on Phase 1:

1. Pin `litellm==<Legion's version>` in ADA + Zero `requirements.txt`.
2. **Zero** — add `transport="litellm"` branch in `unified_llm_client.py` pointed at `http://host.docker.internal:4444/v1`; feature-flag `ZERO_USE_LITELLM_PROXY` with 7-day shadow mode; delete `ZERO_LITELLM_URL` stale path in `vision_vlm_service.py`.
3. **ADA** — introduce `LLMTransport` interface (`OllamaTransport`/`OpenAITransport`/`LiteLLMTransport`) in `infrastructure/llm_router.py`; delete `DeepSeekClient` + `intelligent_llm_router.py`.
4. Add Langfuse callbacks in `c:\code\legion\docker\litellm\config.yaml`:
   ```yaml
   litellm_settings:
     success_callback: ["langfuse"]
     failure_callback: ["langfuse"]
     service_callback: ["langfuse"]
   ```
5. Once LiteLLM → Langfuse coverage ≥99% for 14 days, curator's source swaps from Postgres pull to Langfuse trace API.

### 3.8 QA gate

In `QAAgentRegistryDB` add:
- `llm_ops_model_promotion_reviewer`
- `llm_ops_regression_reviewer`

In `QASignOffRequirementDB`: condition = sprint task tagged `model_promotion` OR file change matches `backend/app/core/legion_config.py`; `min_required_signoffs=2`; `unanimous=false`; no auto-approval.

---

## 4. New tools to adopt

| Tool | Decision | Why |
|---|---|---|
| **Langfuse** | Mandatory (already enabled) | Single observability plane; LiteLLM has native callback |
| **LiteLLM Router** | Phase 2 standard | Legion already runs it; unifies transport, retries, budget |
| **Promptfoo** | New | Directly satisfies G10 (handover tests); CI-friendly CLI |
| LangSmith / Helicone / Arize / TruLens | Reject | Overlap with Langfuse; not worth the cognitive load |

---

## 5. Dependency updates

**Legion — `c:\code\legion\backend\requirements.txt`**
```
litellm==1.55.4              # B3
langsmith>=0.3.0,<0.4.0      # B4
langfuse>=3.0.0,<4.0.0
huggingface-hub>=0.26.0
promptfoo-python>=0.2.0      # or shell out to node CLI
```
Dev:
```
freezegun>=1.5.0
responses>=0.25.0
pytest-asyncio>=0.24.0
```

**ADA — phase 1:** delete `backend/services/llm_client.py`, `src/services/intelligent_llm_router.py`. Phase 2: pin `litellm==<Legion's>`.

**Zero — phase 1:** remove stale `ZERO_LITELLM_URL` branch in `app/infrastructure/vision_vlm_service.py`. Phase 2: pin `litellm`.

---

## 6. Tests — `pytest -k llm_ops` is the handover gate

All under `c:\code\legion\backend\tests\`.

- **`tests/agents/test_llm_stack_monitor.py`** — golden path, Zero unreachable, ADA unreachable, Legion self-unhealthy, external provider probes (vLLM/Kimi/Gemini/MiniMax/OpenRouter/HF).
- **`tests/agents/test_model_researcher.py`** — Ollama new-model detection, HF trending ingest, OpenRouter price-change, deprecated detection, resilient when one provider fails.
- **`tests/agents/test_llm_response_curator.py`** — idempotent pull, p95 correctness, fallback-rate math, regression at Z≥2, prompt-hash-proxy path.
- **`tests/agents/test_llm_report_generator.py`** — Jinja snapshot (`tests/fixtures/daily_report_2026_04_25.md`), DB + Telegram both called, idempotent re-run edits Telegram message.
- **`tests/integration/test_llm_ops_daily_cycle.py`** — freezegun to `2026-04-25 07:59 UTC`, advance one minute six times; assert all agents ran in order, exactly one `llm_daily_report` row, Telegram sent, no `task_health_registry` exceptions. Resilience test: researcher raises → cycle still produces report with skip note + alert.
- **`tests/test_dependency_pins.py`** — litellm pinned, langsmith pydantic-v2, langfuse present, huggingface-hub present.
- **`tests/promptfoo/llm_ops.yaml`** — golden prompts for planning/execution/analysis tiers with latency+cost+rubric assertions, invoked by `tests/test_promptfoo_golden.py`.

---

## 7. Verification

Run from `c:\code\legion\backend` in an updated venv.

```bash
# (a) migrations
alembic -c alembic.ini upgrade head

# (b) dry-run daily cycle
python -m app.cli.llm_ops run-daily-cycle --date 2026-04-25 --dry-run

# (c) Telegram preview (sends to LLM_OPS_TELEGRAM_PREVIEW_CHAT)
python -m app.cli.llm_ops run-daily-cycle --date 2026-04-25 --telegram-preview

# (d) tests
pytest -k "llm_ops or pre_work or dependency_pins" -v
pytest -k test_promptfoo_golden -v

# (e) API smoke
curl -s http://localhost:8000/api/projects/llm-operations | jq .
curl -s http://localhost:8000/api/llm-ops/reports/latest | jq .
```

Acceptance: all tests green; project row returns `auto_sprint_enabled=true`; dry-run report renders; Telegram preview delivers.

---

## 8. Critical files to create/modify

**New**
- `backend/app/agents/llm_ops/__init__.py`, `stack_monitor.py`, `model_researcher.py`, `response_curator.py`, `report_generator.py`, `planner.py`
- `backend/app/agents/llm_ops/templates/daily_report.md.j2`
- `backend/app/agents/llm_ops/provider_adapters/` — `ollama.py`, `huggingface.py`, `openrouter.py`, `anthropic.py`, `google.py`, `openai.py`, `moonshot.py`, `minimax.py`
- `backend/app/models/llm_ops.py`
- `backend/app/routers/llm_ops.py`
- `backend/app/scheduler/llm_ops_jobs.py`
- `backend/app/cli/llm_ops.py`
- `backend/alembic/versions/20260425_llm_ops_project.py`, `20260425_llm_ops_schema.py`
- Test files listed in §6

**Modified**
- `backend/app/services/autonomous_sprint_executor.py` (B1, B2)
- `backend/app/services/unified_llm_service.py` (add `health_snapshot()`)
- `backend/app/agents/agent_registry.py` (register 5 agents + `llm_ops` blueprint role)
- `backend/app/services/scheduler_service.py` (import llm_ops_jobs)
- `backend/requirements.txt`, `backend/requirements-dev.txt`
- `backend/app/core/legion_config.py` (seed data for catalog; optionally add `readonly_db_url` keys to MANAGED_PROJECTS)
- `docker/litellm/config.yaml` (phase 2 callbacks)

**Phase 2 / other projects (deferred)**
- `c:\code\zero\backend\app\infrastructure\unified_llm_client.py`
- `c:\code\zero\backend\app\infrastructure\vision_vlm_service.py` (stale path cleanup — phase 1)
- `c:\code\ada\backend\infrastructure\llm_router.py`
- `c:\code\ada\backend\services\llm_client.py` (delete — phase 1)
- `c:\code\ada\src\services\intelligent_llm_router.py` (delete — phase 1)

---

## 9. Risks & open questions

- **Cross-DB credentials.** Pull ingestion needs read-only Postgres creds for Zero + ADA. Store in Legion secrets, not repo `.env`. Add `LEGION_READONLY_{ZERO,ADA}_DB_URL`.
- **vLLM unmonitored in Zero.** Monitor agent fills it from Legion; a follow-up sprint should extend Zero's own `ecosystem_health_service.py`.
- **Background-task budget.** Legion runs 31 tasks; adding 7 may push `AutonomousBrain` cycle >30s. Profile before merge; if over, move hourly monitor to 3h.
- **Python/Pydantic drift.** Once `langsmith` pins, watch for langchain upgrade dragging it back. Weekly CI import sanity check.
- **PII.** Trace stores hashes, not prompts. Quality scoring needing real prompt text should go via Langfuse (phase 2), not a second Postgres column.
- **Rate limits.** HF + OpenRouter daily pulls well within free tier; back off with `tenacity`; 24h cache.
- **Promptfoo harness choice.** If `promptfoo-python` is flaky, shell out to the node CLI behind a `@pytest.mark.integration` marker.
- **Open — alert routing for discoveries.** Recommendation: only `deprecated|price_change|capability_change|interesting=true` pings Telegram; bulk `new` rows go to daily report only.
- **Open — catalog seeding.** Recommendation: seed from `legion_config.MODEL_REGISTRY` in the migration so day-1 diffs are meaningful (vs. generating on first research run).

---

## Execution order summary

1. Land B1–B4. Green `pytest -k "pre_work or dependency_pins"`.
2. Migration: `20260425_llm_ops_schema.py` (tables + indexes + seed catalog).
3. Migration: `20260425_llm_ops_project.py` (project + product doc rows).
4. Add `UnifiedLLMService.health_snapshot()`.
5. Agent files + provider adapters + templates.
6. Register in `agent_registry.py` (new `llm_ops` role).
7. Scheduler wiring in `scheduler_service.py`.
8. Router `app/routers/llm_ops.py`.
9. CLI `app/cli/llm_ops.py`.
10. Tests (including Promptfoo).
11. Dry-run (`--dry-run`), preview Telegram, then enable live crons.
12. After 30 days stable → Phase 2 LiteLLM consolidation in Zero + ADA.
