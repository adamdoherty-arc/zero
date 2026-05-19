# 50 — LLM architecture (always loaded)

## Always use the latest model

Providers ship faster than training data. Before pinning any LLM, vision, TTS, or embedding model, verify against the current model list. Current anchors (verify, don't cache):

- **Anthropic Claude**: Opus 4.7, Sonnet 4.6, Haiku 4.5.
- **Google Gemini**: 3.1 Pro, 3.1 Flash, 3.1 Flash-Lite (April 2026 — NOT 2.5).
- **OpenAI**: latest GPT-5 / o-series release.

Never hardcode an old model name into source. Route through a configurable name and let `shared-infra/litellm/config.yaml` map it.

## Shared LiteLLM router

The shared LiteLLM config lives at `shared-infra/litellm/config.yaml` and serves cross-project LLM routing on `http://localhost:4444`.

Use alias names — prefer them over pinned versions:
- `gemini-latest` — current top-tier Gemini.
- `gemini-flash-latest` — current fast Gemini (vision default).

Pin via `ZERO_VLM_MODEL` env var only when a specific test needs a specific model.

## Bifrost client (new)

Zero now routes via the **Bifrost client at `shared-bifrost:4445`** for cross-project LLM gateway. Bifrost wraps LiteLLM with cross-project skill routing, cost tracking, and shared rate-limit pooling. Use Bifrost over direct LiteLLM calls for new code.

## Local realtime (vLLM)

- Default chat model: `qwen3-chat` served by vLLM on `:18800`.
- Default coder model: `qwen3-coder`.
- Probe: `curl http://localhost:18800/v1/models`.

The realtime voice path (Reachy) uses `reachy_realtime/local_handler.py` (streaming Whisper → vLLM qwen3-chat → Piper/edge-tts) by default. Cloud realtime backends (OpenAI Realtime, Gemini Live) are surfaced through the LLM badge popover but never auto-selected, even if their API keys are configured.

Preferred-backend resolution lives in `backend/app/routers/reachy_realtime.py` `_enriched_config` — change there if the policy ever flips.

## vLLM provider refactor + realtime config

The vLLM provider was refactored to centralize realtime LLM routing config. Key change: realtime-specific routing (latency-optimized models, streaming defaults) is now resolved through `_enriched_config` rather than being scattered across handlers.

## Provider quirks

- **Kimi K2.5/K2.6 require `temperature=1` EXACTLY.** `kimi_provider.py` clamps this for any `kimi-k2*` model. Don't pass other temps.
- **LLMStatusBadge** in the TopBar reflects `GET /api/reachy-intent/providers/status` (1-token probes, 15s cache, 5s per-provider timeout). Green/amber/red dot tells the user which brain is active.

## Whisper default

Bumped to `distil-large-v3` (~600MB faster-whisper). Override via `REACHY_LOCAL_WHISPER_MODEL`.

## Realtime engine flag

`REACHY_REALTIME_ENGINE` selects `legacy` (default) or `pipecat`. `pipecat` is a no-op safety alias until the Pipecat bridge lands — flipping it does not break voice.
