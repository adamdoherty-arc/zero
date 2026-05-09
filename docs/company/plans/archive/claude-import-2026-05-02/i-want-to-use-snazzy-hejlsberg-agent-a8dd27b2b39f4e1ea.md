# vLLM Crash Diagnosis: Qwen3-32B-AWQ on RTX 5090 / WSL / NSSM

## TL;DR

Two independent bugs are stacked:

1. **Args mismatch** — the running container is NOT using your compose file. Something is injecting `max_model_len=16384`, `gpu_memory_utilization=0.72`, and `num_gpu_blocks_override=512`. None of those are in your compose. Find that source first; fixing the KV math is meaningless until the container actually reads your config.
2. **KV cache underflow** — even at the values shown (0.72 util, 16K ctx, 512 forced blocks), the math doesn't fit: 18.14 GiB weights + ~0.64 GiB CUDA-graph + forced 512 KV blocks > 0.72 * 32 GiB headroom = `Available KV cache memory: -4.76 GiB`. vLLM 0.19's new CUDA-graph profiler is now charging that 0.64 GiB against KV budget where 0.18.x didn't, so an ostensibly-working config tipped negative on upgrade.

Fix order: (1) find the phantom args source, (2) rewrite the compose with the args below, (3) replace the NSSM-wraps-`compose-up` pattern with NSSM-wraps-a-supervisor + Docker `restart: unless-stopped`.

---

## 1. Root cause of args mismatch

The compose file is not being honored. Phantom values you're seeing (`16384`, `0.72`, `num_gpu_blocks_override=512`, `served_model_name=qwen3-chat`) are very specific — they came from somewhere. Check in this order:

1. **`docker-compose.override.yml` next to `docker-compose.vllm.yml`** — auto-merged by Compose. Most likely culprit. `ls` the directory and `docker compose -f docker-compose.vllm.yml config` to see the *resolved* effective config.
2. **NSSM `AppParameters`** — `nssm get SharedInfra-Stack AppParameters`. NSSM may be invoking compose with a different `-f` flag or extra `-f override.yml`, or pointing at an old path.
3. **NSSM stale cache** — NSSM caches `AppParameters` in registry under `HKLM\SYSTEM\CurrentControlSet\Services\SharedInfra-Stack\Parameters`. Edits to compose after `nssm install` don't matter; only registry. `nssm dump SharedInfra-Stack` to see what it's actually running.
4. **Multiple `vllm` services in compose** — confirm there isn't a second service inheriting via `extends:` or a profile.
5. **Image entrypoint env vars** — `VLLM_*` env vars in compose `environment:` block override CLI flags. Specifically check for `VLLM_MAX_MODEL_LEN`, `VLLM_GPU_MEMORY_UTILIZATION`, `VLLM_NUM_GPU_BLOCKS_OVERRIDE`. The `served_model_name: qwen3-chat` and `num_gpu_blocks_override: 512` smell like a leftover tuning attempt baked into env.
6. **HuggingFace cache config** — `~/.config/vllm/` or `/root/.config/vllm/` inside the container can carry a config.json. Less likely but cheap to check: `docker exec <container> ls -la /root/.config/vllm/`.

Concrete commands to run (read-only, safe):
```
docker compose -f docker-compose.vllm.yml config | grep -E "max_model_len|gpu_memory|num_gpu_blocks|served_model"
nssm dump SharedInfra-Stack
docker inspect <container_id> | grep -A5 "Cmd\|Env"
ls -la <compose-dir>/docker-compose.override.yml 2>/dev/null
```

The `num_gpu_blocks_override=512` in particular is **the smoking gun** — that flag is never set by default. Someone set it manually trying to fix a previous OOM, and it's now forcing 512 KV blocks regardless of headroom, which is what's driving the negative-memory error.

## 2. KV cache error: canonical fix

**(e) all of the above, weighted.** Specifically:

- **Remove `--num-gpu-blocks-override` entirely.** This is the #1 cause. It bypasses vLLM's auto-sizing.
- **Lower `--max-model-len` to 8192** (your compose value). 16384 is what the container is actually using. At Q4 AWQ + fp8 KV, every doubled context roughly doubles per-request KV footprint.
- **Raise `--gpu-memory-utilization` to ~0.80**, not 0.72. With 32 GB total, `0.80 * 32 = 25.6 GB` budget; weights consume 18.14 GiB, leaving ~7.4 GiB for CUDA graphs (0.64 GiB) + KV cache (~6.7 GiB). At fp8 KV, 6.7 GiB ≈ 35-50K tokens of cache — plenty.
- **Keep `--kv-cache-dtype fp8`**. Halves cache footprint, mandatory at this scale.
- **Keep `--enable-prefix-caching`**. It uses already-allocated KV blocks — does NOT add memory pressure.
- **Set `VLLM_MEMORY_PROFILER_ESTIMATE_CUDAGRAPHS=1` explicitly.** The log warning says 0.19's profiler is changing semantics; setting it makes the accounting deterministic and matches the log's own recommendation.

The 1.5 GB embed model and Reachy daemon are NOT the cause — they're external to vLLM, and if `--gpu-memory-utilization` is interpreted as a fraction of *free* memory at startup (it is, in v1 engine), they're already accounted for. The crash is purely internal accounting.

## 3. Recommended exact docker-compose args

Replace the `command:` block with:

```yaml
services:
  vllm:
    image: vllm/vllm-openai:v0.19.1   # pin, see section 6
    environment:
      - VLLM_MEMORY_PROFILER_ESTIMATE_CUDAGRAPHS=1
      - VLLM_LOGGING_LEVEL=INFO
      - HF_HUB_ENABLE_HF_TRANSFER=1
    command:
      - --model=Qwen/Qwen3-32B-AWQ
      - --served-model-name=qwen3-chat
      - --host=0.0.0.0
      - --max-model-len=8192
      - --gpu-memory-utilization=0.80
      - --kv-cache-dtype=fp8
      - --enable-prefix-caching
      - --max-num-batched-tokens=2096   # avoid Qwen3 attn-block alignment crash
      - --disable-log-requests
      - --disable-frontend-multiprocessing  # smaller mem footprint, single-user OK
    deploy:
      resources:
        reservations:
          devices: [{driver: nvidia, count: 1, capabilities: [gpu]}]
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 180s
```

Explicitly **remove** any `--num-gpu-blocks-override`, `--enforce-eager` (unless debugging), and any env var setting `VLLM_NUM_GPU_BLOCKS_OVERRIDE`.

If you still see `Available KV cache memory: -X GiB` after this, drop `--max-model-len` to 4096 first before touching utilization further — going above 0.85 with a co-resident desktop daemon is asking for OOM during inference autotune.

## 4. Architectural alternative

Recommend **(a) downgrade to Qwen3-14B-AWQ**, not (c) Ollama swap, not (d) Coder-30B-A3B.

Reasoning:
- The Reachy daemon's GPU footprint will fluctuate (camera/display workloads spike). 18 GiB of resident weights leaving only ~7 GiB for KV + Reachy spikes is fragile. 14B-AWQ is ~9 GiB resident, leaving ~18 GiB headroom — fits 32K context comfortably and survives Reachy spikes.
- (c) Ollama for the embed model only saves ~0.6 GiB of overhead (the model weights are already counted). Not worth running two inference stacks.
- (d) Qwen3-Coder-30B-A3B FP8 has lower *active* params but the same resident-weight footprint as 32B-AWQ (~19 GiB at FP8). No win on this GPU.

If you need the 32B reasoning quality specifically, pin `--max-model-len=4096` and accept the limitation. Otherwise 14B-AWQ at 32K context is the better engineering tradeoff for a co-resident GPU.

## 5. Production hardening flags

Must-haves for shared-GPU long-running vLLM:
- `--disable-log-requests` — cuts log volume by ~10x, avoids disk-fill restarts.
- `--disable-frontend-multiprocessing` — single API worker, lower memory, avoids fork-related CUDA context issues on WSL. Tradeoff: reduced concurrent request throughput (fine for desktop/single-user).
- **Avoid `--enforce-eager`** unless debugging. CUDA graphs are ~3-8x faster on Blackwell/WSL2 2.7+. Eager mode is a debugging tool, not production.
- **Avoid sleep mode** (`--enable-sleep-mode`) for now — it's still flaky in 0.19 with AWQ on Blackwell per recent issues.
- Set `VLLM_MEMORY_PROFILER_ESTIMATE_CUDAGRAPHS=1` explicitly (matches future default).
- Set `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` env to reduce fragmentation when sharing with Reachy.
- Healthcheck with `start_period: 180s` (model load takes ~90s; don't let Docker kill during warmup).

## 6. vLLM 0.19 known issues — pin recommendation

Confirmed regressions relevant to your stack:
- 0.19 changed CUDA-graph memory accounting (your exact error).
- Multiple Blackwell + AWQ + FP8 KV CUDA-graph capture crashes filed against 0.19.x.
- `--max-num-batched-tokens` default is too low for Qwen3 attention-block alignment (causes secondary FLASH_ATTN crashes).

**Pin to `vllm/vllm-openai:v0.19.1`** (current 0.19.1 with the explicit env var workaround) rather than `:latest`. Re-evaluate at 0.20.x once the CUDA-graph profiler defaults flip. Do NOT downgrade to 0.18.x — Blackwell sm_120 support there is incomplete.

## 7. NSSM-Docker pattern fix

Your current pattern (NSSM runs `docker compose up` in foreground) is wrong. Failure modes:
- When the container exits, `docker compose up` exits, NSSM restarts compose, which re-pulls/re-creates — slow, racy, and the 30-second restart you see is NSSM's exponential backoff.
- 570 restarts in 4h ≈ one every 25s — confirming NSSM is doing the restarting, not Docker.
- Docker's own `restart: unless-stopped` policy never gets a chance to engage.

Correct pattern:
1. **Make compose declarative & idempotent**: `restart: unless-stopped` on the service (already shown above).
2. **NSSM wraps a supervisor script, not `compose up` directly.** The script's job is to ensure `docker compose up -d` (detached) has been called once after Docker daemon is healthy, then sit and monitor:
   ```powershell
   # supervisor.ps1
   while (-not (docker info 2>$null)) { Start-Sleep 5 }
   docker compose -f C:\path\docker-compose.vllm.yml up -d
   while ($true) {
     Start-Sleep 60
     $status = docker inspect -f '{{.State.Health.Status}}' vllm 2>$null
     if ($status -ne 'healthy' -and $status -ne 'starting') {
       docker compose -f C:\path\docker-compose.vllm.yml up -d  # idempotent kick
     }
   }
   ```
3. **NSSM throttle**: `nssm set SharedInfra-Stack AppThrottle 60000` (60s minimum runtime before NSSM considers it "successfully started"). This kills the tight restart loop even if the supervisor itself crashes.
4. **NSSM exit action**: `nssm set SharedInfra-Stack AppExit Default Restart`, `nssm set SharedInfra-Stack AppRestartDelay 30000`.
5. **Order dependency**: `nssm set SharedInfra-Stack DependOnService com.docker.service` so NSSM doesn't start the supervisor before Docker daemon is up.

This separates concerns: Docker handles container lifecycle (restart-on-crash), the supervisor handles "is the container present at all", and NSSM handles "is the supervisor running". Each layer has appropriate timescale (seconds / minutes / boot).

---

## Action checklist (read-only diagnostics first)

1. `docker compose -f docker-compose.vllm.yml config` — confirm what compose actually resolves to.
2. `nssm dump SharedInfra-Stack` — confirm what NSSM actually runs.
3. `ls` for `docker-compose.override.yml` in the same directory.
4. `docker inspect <container>` — read `Config.Cmd` and `Config.Env` for the phantom args source.
5. Once source is found and removed, apply the compose in section 3.
6. Restructure NSSM per section 7.
7. Pin image to `v0.19.1`.

## Sources

- [vLLM Issue #2248 — "No available memory for cache blocks"](https://github.com/vllm-project/vllm/issues/2248)
- [vLLM Issue #14992 — recent regression on main](https://github.com/vllm-project/vllm/issues/14992)
- [vLLM Discussion #15842 — co-resident GPU instances](https://github.com/vllm-project/vllm/discussions/15842)
- [vLLM Issue #35743 — Qwen3 AWQ CUDA graph capture fails](https://github.com/vllm-project/vllm/issues/35743)
- [vLLM Issue #37242 — RTX 5090 sm_120 + WSL2 CUDA graphs](https://github.com/vllm-project/vllm/issues/37242)
- [vLLM Issue #39025 — CUDA illegal memory access regression in 0.19](https://github.com/vllm-project/vllm/issues/39025)
- [vLLM Issue #39010 — CUDA graph capture hang in 0.19](https://github.com/vllm-project/vllm/issues/39010)
- [vLLM Issue #40742 — CUDA graph profiling crash with FP8 + PDL](https://github.com/vllm-project/vllm/issues/40742)
- [vLLM Issue #28626 — Qwen3-VL-32B-AWQ memory limits](https://github.com/vllm-project/vllm/issues/28626)
- [Qwen3.5 vLLM Recipes (max-num-batched-tokens=2096 requirement)](https://docs.vllm.ai/projects/recipes/en/latest/Qwen/Qwen3.5.html)
- [Joshua8.AI — Qwen3.5-35B on RTX 5090 with vLLM](https://joshua8.ai/qwen35-35b-rtx-5090-vllm-practical-guide/)
- [vLLM Environment Variables docs](https://docs.vllm.ai/en/stable/configuration/env_vars/)
- [NSSM usage docs (AppThrottle / restart behavior)](https://nssm.cc/usage)
- [Docker Compose restart policies](https://www.baeldung.com/ops/docker-compose-restart-policies)
