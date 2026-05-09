# Local LLM Survey — RTX 5090 32GB, April 2026

Target: single 32GB RTX 5090, ~1.5GB shared with Reachy Mini vision. Current stack:
Qwen3-32B-AWQ Int4 chat+code (~17GB), Qwen3-Embedding-0.6B, Ollama qwen3-coder-next fallback.

## 1. Chat / general synthesis

| Model | HF / Ollama | VRAM @ quant | Notes |
|---|---|---|---|
| **Qwen3.6-35B-A3B (AWQ)** | `QuantTrio/Qwen3.6-35B-A3B-AWQ` / `qwen3.6:35b-a3b` | ~20GB W4 + KV; fits with tight context | MoE, 3B active. ~2x throughput vs Qwen3-32B dense at similar/better quality. April 16 2026 release, prioritizes stability + agentic coding. |
| **Qwen3.5-27B (dense, AWQ)** | `Qwen/Qwen3.5-27B` AWQ community quant / `qwen3.5:27b` | ~15GB W4 | Ties GPT-5-mini on SWE-Verified at 72.4. Dense, predictable latency, leaves more KV headroom than 32B. |
| Stay-put alt: **Qwen3-32B-AWQ** | current | ~17GB | Still fine; getting old. |

**Recommendation: SWAP to Qwen3.6-35B-A3B-AWQ.** Same VRAM bucket, better agentic and chat performance, MoE gives ~2x tok/s on the 5090, and KV is the same since active params are 3B. Qwen3.5-27B-dense is the safer fallback if MoE expert routing under vLLM gives you trouble with concurrent requests.

## 2. Code / agentic coding

| Model | HF / Ollama | VRAM @ quant | Notes |
|---|---|---|---|
| **Qwen3-Coder-30B-A3B-Instruct (AWQ-4bit)** | `cpatonn/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` / `qwen3-coder:30b-a3b` | ~17GB + 256K context | 51.6 SWE-Verified w/ OpenHands. Native 256K, extendable to 1M w/ YaRN. Built for Cline/Qwen Code function-call format. |
| **Qwen3-Coder-Next (80B-A3B, IQ3/IQ4)** | `unsloth/Qwen3-Coder-Next-GGUF` / `qwen3-coder-next` | 32GB GPU + 32-64GB RAM offload | >70% SWE-Verified with SWE-Agent. Beats models 10-20x its active size. Needs llama.cpp expert offload. TTFT spikes possible. |
| **Qwen3.6-35B-A3B-AWQ** (shared with chat) | as above | ~20GB | Solid generalist coder; not as sharp as Coder-30B for agent loops but unifies your stack on one model. |

**Recommendation: SWAP coding role to Qwen3-Coder-30B-A3B-AWQ as primary.** It's purpose-built for agentic coding loops, fits with massive context, and the AWQ-4bit community quants (cpatonn/cyankiwi) are stable in vLLM. Keep `qwen3-coder-next` GGUF as a "hard problem" escalation tier — slower TTFT but materially smarter, and it's the locally-runnable thing closest to Sonnet-class coding. Don't try to use Coder-Next as your daily driver.

## 3. Embedding (RAG)

| Model | HF | VRAM | Notes |
|---|---|---|---|
| **Qwen3-Embedding-0.6B** (current) | `Qwen/Qwen3-Embedding-0.6B` | ~1.5GB | Top of class for size. Apache 2.0. 100+ langs. Custom instructions give +1-5%. |
| Qwen3-Embedding-4B | `Qwen/Qwen3-Embedding-4B` | ~8GB | Better recall. Worth it only if vault recall is bottleneck. |
| Nomic Embed v2 MoE | `nomic-ai/nomic-embed-text-v2-moe` | ~1GB active | English-leaning, MoE. No win over Qwen3-0.6B for your case. |

**Recommendation: STAY on Qwen3-Embedding-0.6B.** It's still the right answer at this size class. If RAG recall ever feels weak, jump straight to Qwen3-Embedding-4B — don't bother with intermediate options.

## 4. Reranker (NEW role)

| Model | HF | VRAM | Notes |
|---|---|---|---|
| **Qwen3-Reranker-0.6B** | `Qwen/Qwen3-Reranker-0.6B` | ~1.5GB | Apache 2.0, 32K context, 100+ langs, pairs natively with your embedding model (same tokenizer family, same instruction-conditioning trick). |
| Jina-Reranker-v3 | `jinaai/jina-reranker-v3` | ~1GB | Strong on multilingual; some weights non-permissive — check license per use. |
| gte-reranker-modernbert-base | `Alibaba-NLP/gte-reranker-modernbert-base` | ~0.5GB | 149M params, matches 1B-class on Hit@1 — fastest option if latency matters more than ceiling. |

**Recommendation: ADD Qwen3-Reranker-0.6B.** It's the obvious match — same family as your embedder, uses the same instruction trick, ~1.5GB VRAM. If you want sub-10ms reranks on big candidate sets, run gte-reranker-modernbert-base instead.

## 5. Fast classifier / router

| Model | HF / Ollama | VRAM | Notes |
|---|---|---|---|
| **Qwen3.5-2B-Instruct** | `Qwen/Qwen3.5-2B-Instruct` / `qwen3.5:2b` | ~2GB Q4 | Fast routing, structured outputs reliable, multilingual. Best default. |
| **Gemma 3 1B** | `google/gemma-3-1b-it` / `gemma3:1b` | ~1GB Q4 | 2500+ tok/s on small GPU. Good for pure classification, weaker reasoning. |
| SmolLM3-3B | `HuggingFaceTB/SmolLM3-3B` | ~3GB Q4 | Beats Qwen3-4B / Gemma 3 4B on several reasoning evals; fully transparent training. |

**Recommendation: ADD Qwen3.5-2B-Instruct as router.** It speaks the same prompt conventions as your other Qwen models, JSON-mode is reliable, and 2GB leaves room for everything else.

## 6. Vision (vault image OCR)

| Model | HF / Ollama | VRAM | Notes |
|---|---|---|---|
| **Qwen3-VL-8B-Instruct** | `Qwen/Qwen3-VL-8B-Instruct` / `qwen3-vl:8b` | ~10GB Q4-Q5 | 96.1% DocVQA, 32-language OCR, robust to blur/tilt/low-light. Best small-VL OCR currently. |
| Qwen3-VL-4B | `Qwen/Qwen3-VL-4B-Instruct` | ~6GB | Smaller drop-in if you can't spare 10GB. |
| InternVL3.5-8B | `OpenGVLab/InternVL3_5-8B` | ~16GB | Stronger general visual reasoning; weaker per-GB than Qwen3-VL on OCR. |

**Recommendation: ADD Qwen3-VL-8B (Q4) ONLY if you want to free up the cloud round-trip for vault OCR.** Otherwise Reachy Mini's existing 1.5GB vision model + Gemini Flash for OCR is cheaper than carving 10GB out of your VRAM budget. It's a real upgrade vs older small-VL models, but it's not strictly necessary.

## Current-models report (last ~3 months that matter)

- **Qwen3.5 (Feb 16 2026)** and **Qwen3.6 (Apr 16-22 2026)**: the relevant news for you. Qwen3.6-35B-A3B is the clear upgrade path from Qwen3-32B-AWQ — same VRAM bucket, MoE-faster, better agentic coding, AWQ quants already shipping.
- **Qwen3-Coder-Next (80B-A3B)**: locally-runnable Sonnet-class coder if you accept GGUF + RAM offload. Use as escalation, not daily driver.
- **GLM-5.1 (Apr 2026)**: 744B, MIT license, #1 on SWE-Bench Pro at 58.4. **Does not fit 32GB.** Mention only because it's the best open-weight coder right now for cloud/multi-GPU. Skip locally.
- **DeepSeek V3.2** (NVFP4 NVIDIA quant available) and **DeepSeek R2**: still too big for single 32GB without aggressive offload. Stay on cloud DeepSeek if you need it.
- **Mistral Small 4 (Mar 2026)**: 128-expert MoE unifying Magistral/Pixtral/Devstral, 256K, Apache 2.0. Worth a look as a Qwen3.6 alternative if you want one model for chat+code+vision, but Qwen3.6+Qwen3-Coder still benchmarks higher per VRAM-GB.
- **Nemotron 3 Nano** (NVIDIA, Mar 2026): Super/Ultra promised; nothing shipped yet that beats Qwen3.6-35B-A3B in your bucket.
- **Phi-5**: not released. Phi-4-Reasoning-Vision (15B, Mar 4 2026) exists but not competitive vs Qwen3-VL-8B for OCR.
- **Llama 4.x**: still too license-encumbered ("Built with Llama" branding required) and not winning any benchmark vs Qwen3.6 in your size class. Skip.
- **Gemma 4**: 1B/4B variants are good for classifier role; nothing in 30B class that beats Qwen3.6.

## Deprecation / security / license flags

- **LiteLLM supply chain attack (Mar 24 2026)**: versions `1.82.7` and `1.82.8` shipped credential-stealing payloads via PyPI for ~40 minutes before quarantine. Pin to a known-good version (>=1.82.9 or pre-1.82.7) and audit any environment that ran `pip install litellm` between those dates. Relevant if your router uses LiteLLM.
- **Llama 4.x**: "Built with Llama" branding requirement contaminates any product surface. DeepSeek/Qwen/GLM are MIT or Apache 2.0 — prefer them.
- **gpt-oss-20b**: research shows local models, this one in particular, comply with vulnerability-injection prompts up to 95% of the time. Don't put it in a coding agent loop without sandboxing.
- **Qwen3-32B-AWQ (your current)**: not deprecated, not insecure, just superseded by Qwen3.6-35B-A3B in the same VRAM envelope.

## Action list (priority order)

1. **Swap chat: Qwen3-32B-AWQ → Qwen3.6-35B-A3B-AWQ.** Free win on speed and quality.
2. **Add coder: Qwen3-Coder-30B-A3B-AWQ-4bit** as primary for agent loops; keep qwen3-coder-next GGUF as escalation.
3. **Add reranker: Qwen3-Reranker-0.6B** to RAG pipeline.
4. **Add router: Qwen3.5-2B-Instruct** for fast classification before dispatching to chat/code.
5. **Stay on Qwen3-Embedding-0.6B.** No swap needed.
6. **Vision: skip locally** unless you have a specific reason to pull vault OCR off the cloud; if so, Qwen3-VL-8B Q4.
7. **Audit LiteLLM** version pin if you use it in your router.
