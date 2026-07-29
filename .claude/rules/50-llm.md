---
paths: ["backend/**"]
---

# 50 — LLM architecture

## Always use the latest model

Providers ship faster than training data. Before pinning any LLM, vision, TTS, or embedding model, verify against the current model list. Current anchors (verify, don't cache):

- **Anthropic Claude**: Opus 4.7, Sonnet 4.6, Haiku 4.5.
- **Google Gemini**: 3.1 Pro, 3.1 Flash, 3.1 Flash-Lite (April 2026 — NOT 2.5).
- **OpenAI**: latest GPT-5 / o-series release.

Never hardcode an old model name into source. Route through a configurable name and let `shared-infra/litellm/config.yaml` map it.

## Shared LiteLLM router

The shared model map lives at `shared-infra/litellm/config.yaml`. The standalone LiteLLM gateway on `:4444` is **retired** (no container runs there). Cross-project LLM routing now serves through the **Bifrost gateway on `http://localhost:4445`** (see _Bifrost client_ below); health-check it at `:4445/health/liveliness`.

Use alias names — prefer them over pinned versions:
- `gemini-latest` — current top-tier Gemini.
- `gemini-flash-latest` — current fast Gemini (vision default).

Pin via `ZERO_VLM_MODEL` env var only when a specific test needs a specific model.

## Bifrost client (new)

Zero now routes via the **Bifrost client at `shared-bifrost:4445`** for cross-project LLM gateway. Bifrost wraps LiteLLM with cross-project skill routing, cost tracking, and shared rate-limit pooling. Use Bifrost over direct LiteLLM calls for new code.

## Local vLLM

- Default chat model: `qwen3-chat` served by vLLM on `:18801`. `qwen3-chat` is the **stable gateway alias** — Bifrost maps it (and the legacy `Qwen3-32B-AWQ` name) to whatever vllm-chat currently serves (Qwen3.5-35B-A3B since 2026-06-11), so local model swaps don't require Zero code changes.
- Default coder model: `qwen3-coder`.
- Probe: `curl http://localhost:18801/v1/models`.

## Provider quirks

- **Kimi K2.5/K2.6 require `temperature=1` EXACTLY.** `kimi_provider.py` clamps this for any `kimi-k2*` model. Don't pass other temps.

## Whisper (meeting transcription)

`meeting_processing_pipeline.py` uses `distil-large-v3` (~600MB faster-whisper) by default. Override via `REACHY_LOCAL_WHISPER_MODEL` env var — the name predates the 2026-07-11 robot removal but the var itself belongs to meeting transcription now, not Reachy.
