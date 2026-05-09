# Optimize vLLM throughput without sacrificing model quality

## Context

We just migrated Zero's local LLM from Ollama to vLLM to eliminate VRAM-contention crashes and gain real concurrency. The migration succeeded end-to-end: chat + embed servers healthy, `zero-api` generated a carousel (`cc-bb92952656e1`, "Boyd Stevens") through the full vLLM path.

**But throughput is unacceptable.** Current `Qwen/Qwen3-32B-AWQ` on the RTX 5090 is running at ~3 tok/s measured from vLLM's own scheduler logs:

```
Avg generation throughput: 2.4–4.6 tokens/s, Running: 1 reqs, GPU KV cache usage: 17–19%
```

A 5090 at sm_120 Blackwell should be delivering 40–80 tok/s on a 32B model at Int4/FP8. We're getting ~10× less. Root cause is almost certainly that vLLM 0.19.1's **AWQ-Marlin W4A16 kernels are not yet optimized for Blackwell** — FP8 on Blackwell goes through dedicated hardware tensor cores, AWQ-Int4 does not.

**User constraint**: don't fix this by downgrading to a smaller model. The fix must preserve 32B-class quality.

## Approach

Two changes that together keep (or raise) quality while reclaiming speed.

### Change A — swap AWQ-Int4 → FP8 (primary lever)

Switch `ZERO_VLLM_CHAT_MODEL` to `Qwen/Qwen3-30B-A3B-Instruct-2507-FP8` (**best local model for this class** — MoE with 3B active params per token, same-or-better benchmark quality than dense 32B, dramatically faster because only 3B params are hit per token). This is the model we originally picked but couldn't fit at FP8 because weights took 29.1 GiB and left no room for KV cache.

Now we can fit it by pairing with `--kv-cache-dtype fp8` (halves KV-cache memory footprint without meaningful quality loss — widely used in production), plus trimming `max-model-len` to 8192 (carousel prompts are well under 2k tokens; 8k is plenty and the old unused 24k of context was costing ~6 GiB of KV reservation).

Expected math on 32 GiB 5090:
- weights FP8: ~17 GiB
- activations / workspace: ~6–8 GiB
- KV cache fp8 @ 8k ctx: ~1.5 GiB
- total: ~25–26 GiB ← fits comfortably at `--gpu-memory-utilization 0.90`

**Fallback if that still OOMs at KV-cache check**: `Qwen/Qwen3-32B-FP8` (dense 32B, FP8, ~20 GiB weights, officially published by Qwen). Still best-in-class quality, native Blackwell FP8 tensor-core path = 3–5× faster than the AWQ-Marlin path we're on today. No quality regression vs current AWQ.

### Change B — vLLM version + kernel/attention tuning

- **Upgrade image** from `vllm/vllm-openai:latest` (currently resolves to 0.19.1) to an explicit recent tag that has Blackwell kernel work (`vllm/vllm-openai:v0.20.0` or `v0.21.0` if available — pinned, not floating). Image changes are cheap to roll back.
- Add `--kv-cache-dtype fp8` to chat server (per above).
- Drop `--enable-auto-tool-choice --tool-call-parser hermes` unless we're actually doing tool calling through vLLM today — they add per-request overhead and we aren't using them (the MCP/tool path goes through Claude Agent SDK, not this server).
- Leave `--max-model-len 8192`, `--gpu-memory-utilization 0.90`, `--dtype auto`.

**Not doing**: `--enforce-eager` (would bypass torch.compile, usually slower on Blackwell), attention backend swap (FLASH_ATTN v2 is the right default), quantization-to-CPU offload (quality/latency tradeoff user rejected).

## Verification

After both changes, hit the following in order:

1. `docker logs zero-vllm-chat | grep "Model loading took"` — confirm FP8 weights fit (expect ~17 GiB, not 29.1).
2. `docker logs zero-vllm-chat | grep "KV cache"` — confirm no "No available memory" error.
3. `curl -sf http://localhost:18800/health` → 200.
4. One-shot tok/s benchmark:
   ```bash
   time curl -sf http://localhost:18800/v1/chat/completions \
     -H "Content-Type: application/json" \
     -d '{"model":"qwen3-chat","messages":[{"role":"user","content":"Write a 500-word story about a dragon."}],"max_tokens":600,"temperature":0.7}'
   ```
   Target: ≥ 30 tok/s generation throughput from vLLM's scheduler log lines. If we get ≥ 40 tok/s, we're in the expected Blackwell regime.
5. End-to-end via Zero API:
   ```bash
   TOKEN=$(grep ZERO_GATEWAY_TOKEN .env | cut -d= -f2 | tr -d '\r')
   curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
     -d '{"count": 1}' http://localhost:18792/api/characters/batch-smart
   ```
   Target: carousel generation returns in < 90 seconds (currently ~5–7 minutes).

## Files to change

- [docker-compose.sprint.yml](docker-compose.sprint.yml)
  - `zero-vllm-chat.image`: pin from `:latest` to an explicit Blackwell-ready version tag
  - `zero-vllm-chat.command`:
    - change `--model` default from `Qwen/Qwen3-32B-AWQ` → `Qwen/Qwen3-30B-A3B-Instruct-2507-FP8`
    - set `--max-model-len 8192` (from 12288)
    - set `--gpu-memory-utilization 0.90` (from 0.75)
    - add `--kv-cache-dtype fp8`
    - remove `--enable-auto-tool-choice --tool-call-parser hermes`

No backend Python changes are needed — `workspace/llm/router_config.json` and [backend/app/infrastructure/llm_providers/vllm_provider.py](backend/app/infrastructure/llm_providers/vllm_provider.py) reference the model by `served-model-name` (`qwen3-chat`), not by HF path, so the router is decoupled from which model vLLM is actually serving.

## Rollback

If the new model fails to fit or throughput doesn't improve:
1. Revert `docker-compose.sprint.yml` changes (`git checkout`).
2. `docker compose -f docker-compose.sprint.yml up -d zero-vllm-chat` restores the AWQ build.
3. No backend code rollback needed.

## Out of scope (explicitly)

- Moving vLLM out of Docker/WSL2 (would need its own session; user didn't ask for this yet).
- Upgrading to a larger card (hardware change).
- Running a second GPU (user has one 5090).
- Swapping to a smaller parameter count model (user rejected).
