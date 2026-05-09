# Legion redeploy + confirm direct-vLLM routing

## Context

Uncommitted work on this branch adds a `VLLMClient` ([backend/app/services/llm_clients/vllm_client.py](backend/app/services/llm_clients/vllm_client.py)) and a `LOCAL_LLM_BACKEND` toggle in [backend/app/core/config.py](backend/app/core/config.py) + [backend/app/services/unified_llm_service.py](backend/app/services/unified_llm_service.py) that swaps the local-tier client between Ollama and vLLM. The `.env.example` now sets `LOCAL_LLM_BACKEND=vllm`, and `backend/app/services/llm_clients/base.py` adds `LLMProvider.VLLM`.

Goal: redeploy the Docker stack so the backend routes local-tier calls **directly** to the shared vLLM container (`vllm-chat` on host port 8000), bypassing LiteLLM for local inference, and prove it with live verification.

## Chosen topology (user decision): Direct vLLM from backend

- `LOCAL_LLM_BACKEND=vllm` → `UnifiedLLMService._local_llm_client_class()` returns `VLLMClient`.
- Backend hits `http://host.docker.internal:8000/v1/chat/completions` directly. LiteLLM is no longer in the local-tier path.
- LiteLLM container **stays up** for cloud tier (Kimi/MiniMax) — only the local leg is rewired.
- Trade-off accepted: loss of LiteLLM's `qwen3-coder-next → minimax-m2` fallback for local-tier calls. When vLLM is down, calls raise `ServiceUnavailableError`; the circuit breaker handles it. MiniMax fallback is still available via Legion's own escalation path (`FULL_MODEL_ESCALATION` in `legion_config.py`).

## Blockers found in pre-flight

1. **Docker Desktop is not running.** `docker ps` fails with `npipe:////./pipe/dockerDesktopLinuxEngine`. Start Docker Desktop first.
2. **`.env` port typo.** `.env` has `VLLM_BASE_URL=http://host.docker.internal:18800/v1`. The shared-infra vLLM container at [c:/code/shared-infra/docker-compose.vllm.yml](c:/code/shared-infra/docker-compose.vllm.yml) exposes **:8000** (chat) and **:8001** (embed). The :18800 port is nothing.
3. **docker-compose.yml does not pass vLLM envs to `legion-backend`.** The block at [docker-compose.yml:103-234](docker-compose.yml) is missing `LOCAL_LLM_BACKEND`, `VLLM_CHAT_BASE_URL`, `VLLM_CHAT_MODEL`, `VLLM_API_KEY`, `VLLM_TIMEOUT`. Without these, `_local_llm_client_class()` defaults to `ollama` and the whole new code path is dead.
4. **Model name mismatch.** `.env.example` says `VLLM_CHAT_MODEL=Qwen/Qwen3.6-35B-A3B-FP8`. Shared-infra actually serves `qwen3-chat` (via `--served-model-name qwen3-chat`). Shared-infra README also warns the FP8 35B causes GPU OOM on a 32GB card. We must pass `VLLM_CHAT_MODEL=qwen3-chat` to the backend.
5. **LiteLLM fallback chain still references the local tier.** [docker/litellm/config.yaml:59-62](docker/litellm/config.yaml#L59-L62) has `qwen3-coder-next → minimax-m2` and `minimax-m2 → qwen3.6`. That second entry is a cross-tier fallback that no longer makes sense once the backend stops routing local traffic through LiteLLM — but it's cosmetic; cloud-tier calls (Kimi/MiniMax) go through LiteLLM and will still work. Leave it alone for this redeploy.

## Plan

### 1. Start Docker Desktop and verify

```
docker ps
```

Wait until it returns a container list (not an error).

### 2. Start shared-infra vLLM

```
docker compose -f c:/code/shared-infra/docker-compose.vllm.yml up -d vllm-chat
```

Then block until healthy:

```
docker ps --filter "name=vllm-chat" --format "{{.Status}}"
# Wait for "(healthy)"; first boot can take 3-5 min while the model loads
curl -sS http://localhost:8000/v1/models
# Expect JSON with data[].id == "qwen3-chat"
```

### 3. Fix `.env` and wire compose envs

Edit `c:/code/Legion/.env`:

- Change `VLLM_BASE_URL=http://host.docker.internal:18800/v1` → `http://host.docker.internal:8000/v1`
- Add (or confirm) `VLLM_CHAT_BASE_URL=http://host.docker.internal:8000/v1`
- Add `VLLM_CHAT_MODEL=qwen3-chat` (override the `.env.example` FP8 default)
- Add `LOCAL_LLM_BACKEND=vllm`

Edit `c:/code/Legion/docker-compose.yml` `legion-backend.environment` block (insert near the existing `OLLAMA_BASE_URL` / `LOCAL_LLM_URL` lines around [docker-compose.yml:153-161](docker-compose.yml#L153-L161)):

```yaml
      # Local LLM backend toggle — "ollama" (LiteLLM transport) or "vllm" (direct)
      LOCAL_LLM_BACKEND: ${LOCAL_LLM_BACKEND:-vllm}
      VLLM_CHAT_BASE_URL: ${VLLM_CHAT_BASE_URL:-http://host.docker.internal:8000/v1}
      VLLM_CHAT_MODEL: ${VLLM_CHAT_MODEL:-qwen3-chat}
      VLLM_API_KEY: ${VLLM_API_KEY:-EMPTY}
      VLLM_TIMEOUT: ${VLLM_TIMEOUT:-180}
```

Do NOT remove `LITELLM_URL`, `LOCAL_LLM_URL`, or `OLLAMA_NATIVE_URL` — LiteLLM stays up for cloud routing and the Ollama envs are read defensively by other code paths even when the client class flips to vLLM.

### 4. Rebuild + restart

```
cd c:/code/Legion
docker-compose build legion-backend
docker-compose up -d legion-backend legion-frontend legion-litellm legion-db legion-redis legion-qdrant
docker logs legion-backend --tail 80
```

Wait for the backend healthcheck (`curl http://localhost:8005/health` returns 200).

### 5. Verify direct-to-vLLM routing (all five signals must pass)

- **(a) Backend health:** `curl http://localhost:8005/health` → 200, `agentic.status` present.
- **(b) Trigger a local-tier call:**
  ```
  curl -X POST http://localhost:8005/llm/execute \
    -H "Content-Type: application/json" \
    -d '{"prompt":"Say hello","task_type":"general","_source":"vllm_verification"}'
  ```
  Expect a non-empty response within ~10s.
- **(c) Backend logs show VLLMClient instantiation:** `docker logs legion-backend --tail 200 | grep -iE "vllm|VLLMClient"` — the client init log line should mention vLLM at `host.docker.internal:8000/v1`, not Ollama.
- **(d) vLLM access log:** `docker logs vllm-chat --tail 50 | grep "POST /v1/chat/completions"` — should show a hit dated within seconds of step (b).
- **(e) DB audit row:** `docker exec legion-db psql -U legion -d legion -c "SELECT provider, model, source, created_at FROM llm_call_details ORDER BY id DESC LIMIT 3;"` — newest row has `source='vllm_verification'`, `provider='ollama'` (routing identity stays OLLAMA per the comment in `_local_llm_client_class` — that's intentional, not a bug), `model` resolving to `qwen3-chat`.

If (c)+(d) both pass, the redeploy is confirmed. If (c) still shows Ollama, the compose envs didn't take — re-check `docker inspect legion-backend --format '{{.Config.Env}}' | tr ' ' '\n' | grep -iE "VLLM|LOCAL_LLM_BACKEND"`.

### 6. Sprint-tracking (CLAUDE.md rule)

Per CLAUDE.md, this work needs a sprint in Legion's DB (`project_id=3`). Create after verification passes, not before:

```
INSERT INTO sprints (name, description, project_id, status, priority, total_tasks, created_at, updated_at)
VALUES (
  'Infra-04: Direct vLLM routing + compose env wiring',
  'Flip local-tier LLM client from Ollama-via-LiteLLM to VLLMClient direct to host vllm-chat:8000. Wires LOCAL_LLM_BACKEND/VLLM_* into legion-backend compose env.',
  3, 'COMPLETED', 1, 3, NOW(), NOW()
);
```

(Use next free `Infra-NN` — verify with `SELECT name FROM sprints WHERE project_id=3 AND name LIKE 'Infra-%' ORDER BY id DESC LIMIT 5`.)

## Files touched

- `c:/code/Legion/.env` — port fix + 3 new envs (`VLLM_CHAT_BASE_URL`, `VLLM_CHAT_MODEL`, `LOCAL_LLM_BACKEND`).
- `c:/code/Legion/docker-compose.yml` — ~6 lines added to `legion-backend.environment`.

No source code changes. The uncommitted `vllm_client.py` + `_local_llm_client_class()` + `LLMProvider.VLLM` changes stay as-is; this redeploy is what activates them.

## Rollback

If verification fails and we need Legion back on the known-good LiteLLM path:

1. In `.env`, set `LOCAL_LLM_BACKEND=ollama`.
2. `docker-compose up -d legion-backend` (no rebuild needed — env var change only).
3. Backend goes back to `OllamaClient → LiteLLM:4000 → vLLM or MiniMax-fallback`.

No data migration, no image rollback needed.
