# Local LLM brains for Reachy Interactive Mode

Reachy's Local (vLLM) backend routes through the shared LiteLLM gateway at `host.docker.internal:4444`. The gateway forwards to one of two vLLM servers on the Windows host:

- `vllm-chat` on port `18800` — the always-on default. Serves `qwen3-chat` / `qwen3-coder` (currently `Qwen/Qwen3-32B-AWQ`).
- `vllm-heretic` on port `18801` — optional; serves uncensored Qwen3.5 variants for the companion persona.

## Heretic catalog

| LiteLLM name | HF repo | Size | Context | VRAM (fp8) | Notes |
| --- | --- | --- | --- | --- | --- |
| `qwen3-heretic-9b` | DavidAU/Qwen3.5-9B-Claude-4.6-HighIQ-THINKING-HERETIC-UNCENSORED | 9B | 128K | ~10 GB | Default companion brain |
| `qwen3-heretic-27b` | DavidAU/Qwen3.5-27B-HERETIC-Polaris-Advanced-Thinking-Alpha-uncensored | 27B | 128K | ~30 GB | Larger; pick if VRAM allows |
| `qwen3-heretic-40b` | DavidAU/Qwen3.5-40B-Claude-4.6-Opus-Deckard-Heretic-Uncensored-Thinking | 40B | 256K | ~45 GB | Top-tier; vision-capable |
| `qwen3-josiefied-8b` | (HF: Qwen3-8B-64k-Josiefied-Uncensored) | 8B | 64K | ~9 GB | Lightweight fallback |
| `oxy-1-small` | oxyapi/oxy-1-small | 14B | 32K | ~16 GB | Qwen2.5 base, roleplay-tuned |

These models have abliterated refusal vectors. Gate behind explicit persona or picker selection — they should never be the global default. The persona system prompt is the only guardrail.

## Launch (Windows host)

```powershell
# 9B default — fits comfortably on a 5090 alongside the chat baseline.
vllm serve DavidAU/Qwen3.5-9B-Claude-4.6-HighIQ-THINKING-HERETIC-UNCENSORED `
  --max-model-len 32768 `
  --quantization fp8 `
  --enable-prefix-caching `
  --served-model-name qwen3-heretic-9b `
  --port 18801
```

`--enable-prefix-caching` matters — the persona system prompt is reused on every turn, so caching it saves significant prefill time.

To run the larger 27B / 40B variants, swap the HF repo and `--served-model-name` and bump `--max-model-len` to 65536 / 131072 if you want long-context. They cannot share a single vLLM process; spawn separate processes per port (e.g. `:18802`, `:18803`) and add corresponding LiteLLM entries.

## Persona-bound model

A persona under `backend/app/data/reachy_profiles/<id>/` can pin its preferred local brain by writing a one-line `model.txt`:

```
qwen3-heretic-9b
```

The realtime session picks this up automatically when the user selects the persona, unless they override the model in the unified settings modal. The first persona to use this is `companion_girlfriend`.

## When NOT to use heretic models

- The user has explicitly asked for a tool / fact lookup. The chat baseline (`qwen3-chat`) is faster and just as accurate for that.
- You want emoji-free, professional output — heretic variants are tuned toward expressive prose, not corporate.
- You're routing background work (digests, scheduler tasks). Use Kimi / Gemini / `qwen3-chat`, not heretic.
