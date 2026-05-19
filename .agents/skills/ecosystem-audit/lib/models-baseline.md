# Model registry baseline

The canonical model layout per [docs/ARCHITECTURE.md](../../../../docs/ARCHITECTURE.md)
and [shared-infra/README.md](../../../../shared-infra/README.md).

Audit Phase E reads `c:\code\shared-infra\docker-compose.vllm.yml` plus
`:4444/v1/models` and `:18800/v1/models` and diffs against this table.

## Local â€” llama.cpp + vLLM on RTX 5090

| Canonical name | Container | Image / source | Quant | VRAM (approx) | Notes |
|---|---|---|---|---|---|
| `qwen3-chat` | `vllm-chat` :18801 | **`Qwen/Qwen3-32B-AWQ`** | AWQ Marlin Int4 | ~20 GB | Primary local chat/reasoning model. Re-swapped 2026-05-17→18 from `llama-cpp-chat` (Q5_K_M GGUF) to real vLLM on the dense 32B-AWQ because Q5_K_M GGUF doesn't use Blackwell FP8 tensor cores; AWQ Marlin on vLLM does. Plus llama.cpp issues #20178 + #19894 (Qwen3.6-A3B JSON bugs + 35% CUDA regression). Result: 0.27s warm inference vs the previous 0.5-2s + occasional timeouts. |
| `qwen3-chat-thinking` | `vllm-chat` :18801 | same | same | shared | Reasoning-enabled route — same model, callers pass `/no_think` to skip thinking-block emission (Qwen3-32B's `enable_thinking` chat-template kwarg is a no-op on AWQ-Marlin in vLLM 0.19; the prompt-suffix is load-bearing). |
| `qwen3-embed` | `vllm-embed` :8001 | Qwen3-Embedding-0.6B | BF16 | ~1.5 GB | Vault embeddings; Matryoshka-truncate to 512 dims |
| `qwen3-rerank` | (planned) | Qwen3-Reranker-0.6B | BF16 | ~1.5 GB | Rerank stage of vault retrieval |
| `qwen3-coder` | (legacy / not active) | n/a | n/a | n/a | Removed from current shared LiteLLM config. Audit callers and route to `qwen3-chat` unless a dedicated coder model is reintroduced. |

Total pinned VRAM target: **~24 GB**. Headroom: **~8 GB** on the 32 GB 5090.

vLLM serve flags (current `vllm-chat` `command:` block — replaced llama.cpp 2026-05-17→18):
```
serve --model Qwen/Qwen3-32B-AWQ
--served-model-name Qwen3-32B-AWQ
--port 8000
--host 0.0.0.0
--quantization awq_marlin
--max-model-len 8192
--gpu-memory-utilization 0.92
--enforce-eager
--enable-prefix-caching
```

Flag rationale (2026-05-18 vLLM swap):
- `awq_marlin`: uses Blackwell FP8 tensor cores on the RTX 5090 — GGUF Q5_K_M does not.
- `--max-model-len 8192`: dense 32B has ~2× the KV footprint per token vs 35B-A3B MoE; 8K fits comfortably with `gpu_memory_utilization 0.92`. Plenty for voice turns.
- `--enforce-eager`: skips cudagraph capture that previously OOM'd on Blackwell with the QuantTrio AWQ port (see Failed swap log below).
- `--enable-prefix-caching`: vLLM-native prefix cache (works cleanly with dense attention; was the SWA limitation with Qwen3-A3B Gated Delta Net under llama.cpp).

Retired flags (2026-05-17 llama.cpp era, kept here for emergency rollback):
`--model …Q5_K_M.gguf --no-mmap --ctx-size 32768 --parallel 1 --cache-reuse 256 --flash-attn auto --cache-type-k q8_0 --cache-type-v q8_0 --jinja`. The Q5_K_M GGUF is on disk at `c:/code/zero/workspace/llm-models/` for 30 days.

## Failed swap log (do not re-attempt without addressing)

`QuantTrio/Qwen3.6-35B-A3B-AWQ` was tried as `qwen3-chat` on 2026-04-27 and reverted:

1. **OOM at 16K**: weights (22.2 GB) + cudagraph (~1.5 GB) + KV @ 16K (~5 GB) > 32 GB.
2. **OOM at 8K** (after dropping context): cudagraph profiling phase still pushed VRAM past KV-alloc ceiling.
3. **Stalled at vision-encoder profiling** (after `--enforce-eager`): the QuantTrio AWQ port carries `Qwen2VLImageProcessor` config even though Qwen3.6-35B-A3B is text-only. Combined with WSL's `pin_memory=False` slowdown, the encoder profile loop never completed in 5+ minutes.

Conditions to re-attempt: (a) clean AWQ port without multimodal config (watch `huggingface.co/Qwen/Qwen3.6-35B-A3B-AWQ` for an official one), OR (b) move vllm-embed to Ollama on host to free its 1.5 GB and run vllm-chat solo, OR (c) vLLM > 0.20 with Blackwell-MoE-aware cudagraph budgeting.

## Cloud â€” passthrough via LiteLLM proxy

| Canonical name | Provider | Use |
|---|---|---|
| `claude-opus-4-7` | Anthropic | Heavy reasoning, plan-mode, complex code review |
| `claude-sonnet-4-6` | Anthropic | Default cloud workhorse |
| `claude-haiku-4-5` | Anthropic | Cheap fast tasks |
| `gemini-pro` | Google | Long-context synthesis |
| `gemini-flash` | Google | Cheap fast |
| `kimi-k2.5` | Moonshot via OpenRouter | Long context, multilingual |
| `minimax-m2` | MiniMax | Comparative routing |
| `gpt-5` | OpenAI | Native router fallback (rare) |

## Routing partition rules

Per [docs/ARCHITECTURE.md](../../../../docs/ARCHITECTURE.md):

- `partition: trading` â€” **decisions** must route local (qwen3-chat). Synthesis
  may go cloud.
- `partition: personal` â€” local default, cloud allowed for synthesis (no PII).
- `partition: zero-dev` â€” cloud allowed (Anthropic).
- `partition: work` â€” must not exist in this ecosystem; hard-drop.

## Pin / version invariants

- LiteLLM image must be **`main-v1.83.7-stable` or newer in the 1.83 stable
  line**. Versions **1.82.7 and 1.82.8 are compromised** (March 2026
  credential-stealer incident), and versions **<=1.81.14** carry April 2026
  CVEs. Critical-severity finding if detected.
- vLLM image: latest stable supporting CUDA 12.8 / sm_120. Audit checks
  date-stamp on image tag is within 90 days.

## Recently promoted

| Model | Promoted | Why |
|---|---|---|
| `Huihui-Qwen3.6-35B-A3B-abliterated-Q4_K_M.gguf` | 2026-04-28 | Replaced Qwen3-32B-AWQ with a GGUF MoE served by llama.cpp; keeps host `:18800`, improves voice-loop latency, and avoids the vLLM AWQ multimodal-config failure path. |
| `Huihui-Qwen3.6-35B-A3B-abliterated.Q5_K_M.gguf` | 2026-05-17 | Quant bump from Q4_K_M (~21 GB) to Q5_K_M (~25 GB) — strict quality lift with no other infra change. Same compose slot, same alias. Compose tuned at the same time: `--parallel 1`, `--ctx-size 32768`, `--cache-reuse 256`, `--no-mmap` to mitigate Qwen3-A3B's Gated Delta Net prefix-cache miss pattern. **SUPERSEDED 2026-05-18 by Qwen3-32B-AWQ on vLLM** — kept on disk 30 days for emergency rollback. |
| `Qwen/Qwen3-32B-AWQ` on vLLM | 2026-05-18 | Re-swapped from llama.cpp Q5_K_M to real vLLM on the dense 32B-AWQ. Drivers: (1) llama.cpp #20178/#19894 — Qwen3.6-A3B JSON tool-call bugs + 35% CUDA regression on the 35B-A3B vs 30B-A3B path; (2) AWQ Marlin uses Blackwell FP8 tensor cores; Q5_K_M GGUF does not. Result: 0.27s warm inference, 124ms `bifrost-local-qwen` probe (vs 689ms on llama.cpp). The provider name `vllm-local` in Bifrost config is now ACCURATE for the first time since the 2026-04-28 swap. |

## Active candidates (filed 2026-04-27)

| Candidate | Source | Size / quant | Why it might beat current | Eval set |
|---|---|---|---|---|
| `Qwen/Qwen3-Coder-30B-A3B-Instruct` | HF | 30B total / 3B active | Code-specialist MoE; vLLM benches 1,157 tok/s at MCR=16 with sub-second TTFT on 5090 â€” dedicated `qwen3-coder` alias instead of aliasing to chat | code_review |
| `meta-llama/Llama-4-Scout-17B-16E-Instruct` | HF | 109B / 8B active, ~24 GB at Q4 | Highest reasoning ceiling on 32 GB hardware; "dense-7B speed with much larger reasoning quality" (18â€“22 tok/s); use as deep-thinker alias | reasoning |
| `deepseek-ai/DeepSeek-R1-Distill-Llama-70B` | HF | 70B at Q4, ~28 GB tight | Reasoning specialist; 15â€“18 tok/s on 5090; tight VRAM but works | reasoning |

Proposal: [vault: 00_Meta/_agent/proposals/model-swap-qwen3.6-moe.md](../../../../vault/ObsidianZero/00_Meta/_agent/proposals/model-swap-qwen3.6-moe.md)
Research: [state/ecosystem-audit/research/models/2026-04-27.md](../../state/ecosystem-audit/research/models/2026-04-27.md)

## Candidate evaluation criteria

When research/models writes a candidate row, it must include:
1. Source URL (HF / NVIDIA NGC / vendor blog).
2. Size + quant (must fit â‰¤30 GB VRAM at the chosen quant).
3. License (Apache-2.0, MIT, Llama-CLA, Qwen â€” note any non-commercial clauses).
4. One-line "why it might beat the current registry" â€” be specific (e.g., "15%
   lower p95 latency than `qwen3-chat` on `reasoning.json` at the same quality bar").
5. Eval set the candidate should be tested against from `Legion/backend/app/eval/`
   (`vault_qa.json`, `code_review.json`, `reasoning.json`, `summary.json`).

Actual A/B and swap is Legion `llm_ops` subgraph's job, not this skill's.

