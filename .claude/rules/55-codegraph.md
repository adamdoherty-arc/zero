# 55 — Codegraph enrichment on every LLM call (Audit-87)

> Path-scoped: `backend/**` only (the LLM path lives here). Companion to
> [50-llm.md](50-llm.md). Read both when touching the LLM stack. Zero mirror
> of Legion's Audit-85 — the bridge host service serves all projects.

## The rule

**Every Zero LLM call goes through `codegraph_enricher.enrich_messages()`
before the prompt leaves the backend.** Enforced inside
`UnifiedLLMClient._call_provider()` (`backend/app/infrastructure/unified_llm_client.py`).
It prepends a compact `<codegraph_context>` block to the system message based
on symbol / file mentions found in the prompt.

Goal: make Bifrost / vLLM / shared-router calls codegraph-aware without each
caller knowing about MCP, so the model gets cross-reference context
(callers / callees / type info) on top of the bare task prompt.

## What gets injected

- 1–2 symbol hints extracted by `extract_symbol_hints()` (backticked
  identifier > `class X` > `def X` / `function X` > `*.py|*.ts` paths >
  CamelCase tail).
- Each hint → `codegraph_context` over the host bridge → one section in the block.
- Hard cap: 2 000 tokens total (envvar `ZERO_CODEGRAPH_ENRICHER_MAX_TOKENS`).

## Disable knobs

- Process-wide kill: `ZERO_CODEGRAPH_ENRICHER=false` in environment.
- Per-source skip: prefix-match against `_SKIP_SOURCE_PREFIXES`
  (`codegraph_enricher`, `embedding`, `embed`, `health`, `livez`, …). Add new
  prefixes there when a self-looping source surfaces; don't sprinkle
  conditional logic at call sites. The `source` is the call's `task_type`.

## Reach codegraph from inside the container

The host has codegraph + `.codegraph/` indexes; the container does not. The
bridge service exposes a thin HTTP surface on `127.0.0.1:18900`
(`GET /context?project=zero&topic=<hint>`). `docker-compose.sprint.yml` sets
`CODEGRAPH_HTTP_URL=http://host.docker.internal:18900` so the enricher inside
zero-api hits the bridge. Without the bridge running, calls still proceed —
enrichment just records `status=unavailable`. Zero has no `/api/codegraph/*`
proxy, so the HTTP bridge is the sole transport (the local-MCP fallback no-ops).

## Observability

- DB: `llm_usage.codegraph_used` / `codegraph_tokens_added` /
  `codegraph_cache_hit` / `codegraph_status` / `codegraph_hints_used`
  (Alembic 054).
- Metrics (`MetricsService`): `codegraph_enrichment{outcome,project}` counter
  + `codegraph_tokens_added{project}` series. Zero uses the in-memory
  `MetricsService`, not Prometheus.

## What NOT to do

- Don't add a second LLM-enrichment path. There's one and only one — the hook
  inside `UnifiedLLMClient._call_provider()`. Anything else drifts.
- Don't catch the codegraph failure path and raise — degradation must be
  silent, with `status=unavailable` recorded.
- Don't bump the token cap above 2 000 without a measurement showing the
  budget bites a measurable share of calls.

## Cross-project mirror

Legion (Audit-85) + ADA + Zero (Audit-87) each ship an identical enricher in
their own backend, an Alembic migration for their `llm_usage`/`llm_call_details`
table, and a `CODEGRAPH_HTTP_URL` env. The bridge host service serves all three
via the `project` query param.
