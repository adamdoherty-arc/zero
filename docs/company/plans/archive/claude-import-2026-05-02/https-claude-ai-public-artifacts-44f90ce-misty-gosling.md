# Zero Content Pipeline — Orchestration Hardening

## Context

A research artifact (Marvel/DC 24/7 content swarm blueprint) proposes a LangGraph + Temporal + ComfyUI + Wan 2.2 + Chatterbox architecture. Comparing it to Zero's existing Content Brain v2 (commit `f7eac50`), Zero already owns most of the orchestration spine: LangGraph supervisor ([orchestration_graph.py](backend/app/services/orchestration_graph.py)), 6-role voting swarm ([content_swarm_service.py](backend/app/services/content_swarm_service.py)), prompt breeder ([prompt_breeder_service.py](backend/app/services/prompt_breeder_service.py)), character dossiers + trending signals in Postgres, pgvector, image sourcing, and Piper/Edge TTS.

**What Zero is missing, scoped to orchestration hardening only (per user):**
1. `AsyncPostgresSaver` is configured in [checkpoint.py](backend/app/infrastructure/checkpoint.py) but **never invoked** in character-generation flows — a crash mid-carousel loses state.
2. No autonomous 24/7 driver — carousel generation is a manual API call; `TrendingSignalModel` exists but nothing consumes it on a loop.
3. Swarm QC is text-free-form — no structured rubric, no fail-retry loop back to the writer stage.
4. No swarm calibration scheduler job — `AgentPredictionModel` stores outcomes but role weights never auto-adjust.
5. No lore retrieval layer — character bios live in `CharacterModel.research_data` JSONB; no pgvector chunks for grounded quote/beat retrieval.
6. `CharacterCarouselModel` unpartitioned — fine today, painful at >100k rows.
7. No asset dedup — carousels can ship near-identical images/hooks.
8. Legal framing is undocumented (report calls this "load-bearing" but user chose advisory-only).

**Not in scope** (user chose "orchestration hardening only"): ComfyUI/Flux/LoRAs, Wan 2.2, Chatterbox, Temporal, MinIO, vLLM.

## Workstreams

### W1. Wire checkpointing into carousel generation
**Files:** [character_content_service.py](backend/app/services/character_content_service.py), [checkpoint.py](backend/app/infrastructure/checkpoint.py)

- Reuse existing `get_async_checkpointer()` from [checkpoint.py](backend/app/infrastructure/checkpoint.py).
- Convert the currently-monolithic carousel generation coroutine in [character_content_service.py](backend/app/services/character_content_service.py) into a small LangGraph `StateGraph` with explicit nodes: `research → synthesis → fact_extraction → image_sourcing → layout → swarm_review → finalize`. Nodes already exist as private methods; wrap them.
- Compile with `checkpointer=get_async_checkpointer()` and a `thread_id = f"carousel:{carousel_id}"`.
- Add a `resume_carousel(carousel_id)` entrypoint that detects incomplete `CharacterCarouselModel.status` on startup and resumes from the last checkpoint.

Guardrail: keep the existing public API shape (router unchanged); refactor is internal.

### W2. Autonomous 24/7 content loop
**New file:** `backend/app/services/autonomous_content_loop_service.py`
**Edit:** [scheduler_service.py](backend/app/services/scheduler_service.py)

- New scheduler job `autonomous_content_loop` (APScheduler, every 30 min).
- Logic: pull top-N unprocessed rows from `TrendingSignalModel` (existing) ordered by `signal_strength` and release recency → dedup against carousels produced in the last 24h for the same character → kick off the W1 graph per character with a budget ceiling (e.g. max 4 concurrent via asyncio.Semaphore, max 48/day per universe).
- Emit structured logs via `structlog` ([per project rules](CLAUDE.md)).
- Toggle via settings flag `ZERO_AUTONOMOUS_CONTENT_ENABLED` (default off; user can turn on per CLAUDE.md).

### W3. Structured swarm QC rubric + fail-retry loop
**Files:** [content_swarm_service.py](backend/app/services/content_swarm_service.py), [character_content_service.py](backend/app/services/character_content_service.py)

- Extend `critique_generated_carousel` to return a typed `SwarmRubric` Pydantic model with fields: `canon_accuracy (0-10)`, `hook_strength (0-10)`, `pacing (0-10)`, `visual_consistency (0-10)`, `platform_compliance (0-10)`, `safety (pass/fail)`, `commentary_framing (pass/fail)`, plus `issues: list[str]`.
- In the W1 graph, add a conditional edge after `swarm_review`: if weighted score < threshold (configurable, default 6.5) or any pass/fail fails, `Command(goto="synthesis", update={"feedback": rubric.issues})` up to max 2 retries. Persist attempt count on `CharacterCarouselModel.retries` (new column).
- Reuse existing `AgentPredictionModel` for per-role scores; just add the rubric fields to the JSON payload.

### W4. Swarm calibration scheduler
**Edit:** [scheduler_service.py](backend/app/services/scheduler_service.py), [content_swarm_service.py](backend/app/services/content_swarm_service.py)

- New job `swarm_calibration` (weekly, Sundays 03:00).
- Reads last 30 days of `AgentPredictionModel` rows where `outcome` is populated (carousel published and engagement measured).
- Computes per-role Brier score + rank correlation between predicted engagement and actual. Writes role weights to a new `swarm_role_weights` JSON in the existing config table (or add a small `SwarmRoleWeightModel`). Swarm voter reads weights at call time.

### W5. Lore retrieval layer
**Edit:** [backend/app/db/models.py](backend/app/db/models.py), new migration, [character_content_service.py](backend/app/services/character_content_service.py)

- New table `character_lore_chunks (id, character_id, source, source_license, text, embedding vector(1024), created_at)` with HNSW index on embedding (m=16, ef_construction=200) matching the pattern the report prescribes and Zero's existing pgvector usage.
- New table `character_quotes (id, character_id, text, source, source_license, embedding vector(1024))`.
- Ingestor job (new scheduler job `lore_ingestion`, runs nightly): walks `CharacterModel.research_data` → chunks existing research text → embeds via existing embedding provider → upserts. Starts with already-researched characters (no new scraping — user scoped this narrow).
- Synthesis node in W1 graph calls `lore_chunks` hybrid search (pgvector + text) to ground the writer, instead of dumping full `research_data` into the prompt.

### W6. Monthly partitioning + dedup
**Edit:** [backend/app/db/models.py](backend/app/db/models.py), new migration

- Convert `CharacterCarouselModel` to `PARTITION BY RANGE (created_at)`, managed by `pg_partman` (already on the Postgres image per memory; verify). Create initial monthly partitions for the current and next 3 months; schedule `pg_partman` monthly maintenance via its built-in bgworker.
- Add columns to `CharacterImageModel`: `sha256 bytea`, `phash bigint`. Backfill via one-shot script; add unique index on `(character_id, phash)` with a Hamming tolerance check at insert time (Python-side).
- Swarm pre-gen check rejects ideas whose proposed hook hashes within-Hamming-8 of any carousel shipped in last 14 days for the same character.

### W7. Advisory legal framing doc
**New file:** `docs/content-legal-framing.md`

Per user choice ("advisory only"), produce a one-page playbook covering: commentary/review framing, no-photorealism rule for IP characters, no actor likenesses, no official soundtracks, C2PA/AI-disclosure recommendation, YouTube "inauthentic content" policy risk. Reference the report's section I. No schema enforcement — just a doc checked into version control that the swarm's `commentary_framing` rubric field (W3) loosely references.

## Critical files to modify

- [backend/app/services/character_content_service.py](backend/app/services/character_content_service.py) — wrap into StateGraph (W1), retry loop (W3), lore retrieval call (W5)
- [backend/app/services/content_swarm_service.py](backend/app/services/content_swarm_service.py) — typed `SwarmRubric`, weight loader (W3, W4)
- [backend/app/services/scheduler_service.py](backend/app/services/scheduler_service.py) — three new jobs (W2, W4, W5 ingestion)
- [backend/app/services/autonomous_content_loop_service.py](backend/app/services/autonomous_content_loop_service.py) — new (W2)
- [backend/app/db/models.py](backend/app/db/models.py) — new tables + columns (W3 retries, W5 lore/quotes, W6 dedup, W4 weights)
- [backend/app/infrastructure/checkpoint.py](backend/app/infrastructure/checkpoint.py) — unchanged; reused (W1)
- New Alembic migration covering all schema changes
- `docs/content-legal-framing.md` — advisory (W7)

## Reused (do not rebuild)

- `orchestration_graph.py` routing/tracing pattern — W1 follows the same `_trace_node` conventions.
- `AsyncPostgresSaver` from `checkpoint.py` — already configured with `autocommit=True, row_factory=dict_row` (matches report's warning).
- `TrendingSignalModel`, `CharacterCarouselModel`, `AgentPredictionModel`, `PromptVariantModel` — all present in [db/models.py](backend/app/db/models.py).
- `content_swarm_service.evaluate_generation_idea()` / `critique_generated_carousel()` — extend, don't replace.
- `prompt_breeder_service` — unchanged; the feedback loop from W3 just increments its existing success/failure counters.
- Ollama semaphore + Kimi routing in existing LLM client — reuse for all new LLM calls.

## Verification

1. **W1 durability**: run `docker kill zero-api` mid-carousel generation; restart; confirm `resume_carousel` completes and `CharacterCarouselModel.status` reaches `ai_reviewed` with a single final row.
2. **W2 loop**: set `ZERO_AUTONOMOUS_CONTENT_ENABLED=true`, seed 3 trending signals, wait 30 min, assert 3 new carousels in DB with swarm scores.
3. **W3 rubric**: inject a carousel with a canon error (wrong universe); assert retry triggers and final carousel passes; verify `AgentPredictionModel` has typed rubric fields.
4. **W4 calibration**: backfill 30 predictions with known outcomes; run job manually via `scheduler.run_job_now("swarm_calibration")`; diff `swarm_role_weights` before/after.
5. **W5 lore**: ingest one character; assert `character_lore_chunks` rows and HNSW index present; run a synthesis and confirm the prompt includes retrieved chunks (log at DEBUG).
6. **W6 partitioning**: `\d+ character_carousels` in psql shows partitions; insert a row dated next month, confirm routed to the right partition. Insert a near-duplicate image, assert rejection.
7. **Docker**: rebuild per [CLAUDE.md](CLAUDE.md) (`docker compose -f docker-compose.sprint.yml build --no-cache zero-api && ... up -d zero-api`); check `docker logs zero-api` for migration + scheduler boot lines.
8. **Legion**: create a sprint + tasks for each workstream in `project_id=8` per [CLAUDE.md](CLAUDE.md) mandatory Legion tracking rule.

## Deferred (explicit non-goals)

Full generative media stack (ComfyUI, Flux, LoRAs, Wan 2.2, Chatterbox), Temporal, MinIO/R2, vLLM swap, video assembly, WhisperX, Satori/Playwright carousel rendering, hard-gated legal compliance. Each is a separate plan if Zero moves beyond orchestration hardening.
