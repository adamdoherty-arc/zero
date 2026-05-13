---
name: llm-routing
type: knowledge
triggers: [llm, routing, hint, model, gemini, kimi, vllm, ollama, bifrost, gateway]
agent: any
---

Zero's LLM routing has two layers:

1. **In-process router** (`app.infrastructure.llm_router.get_llm_router`)
   resolves task_types AND `hint:*` strings to provider/model + fallbacks.
2. **Bifrost gateway** (shared infra at `BIFROST_GATEWAY_URL`) honors the
   same hint taxonomy and centralizes budgets/fallbacks. Call via
   `app.infrastructure.bifrost_client.get_bifrost_client()`.

Hint taxonomy (`llm_hints.py`):

- Local-eligible: `hint:reaction`, `classify`, `format`, `sentiment`,
  `summarize`, `medium`, `tool_lite`, `reflection`.
- Cloud-only: `hint:reasoning`, `agentic`, `coding`, `vision`.

Presets (env `ZERO_HINT_PRESET`):

- `default` — per-hint primary as in `_PRESET_OVERRIDES`.
- `embeddings_only` — push everything to cloud.
- `memory_reflection` — local for summarize/reflection/tool_lite.
- `everything_local` — local for all eligible hints.

Pin temperature=1 for Kimi K2.5/K2.6 (the kimi provider clamps).
