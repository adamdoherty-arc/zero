# Port map (canonical)

Extracted from [docs/ARCHITECTURE.md](../../../../docs/ARCHITECTURE.md) and
[README.md](../../../../README.md). The audit skill probes these ports each
run and flags drift.

| Port | Service | Process / Container | Notes |
|---|---|---|---|
| 3001 / 3005 | Legion UI (React) | `legion-frontend` | Two ports for dev variants |
| 4444 | LiteLLM proxy | `shared-litellm` | Internal :4000 â†’ host :4444; budget $50/24h; pin `main-v1.83.7-stable` or newer in the 1.83 stable line |
| 5173 | Zero UI (Vite) | `zero-frontend` | Dev server |
| 5420 | Ada UI (Vite) | `ada-frontend` | Dev server |
| 5432 | **PostgreSQL 17 (native host)** | Windows-native install | Shared host PG; pgvector 0.8.0; per `Legion/docs/ARCHITECTURE.md` migration on 2026-04-25, Legion's main `legion` DB now lives here, not on the container |
| 5433 | Legion Postgres (container) | `legion-postgres` | Isolation from native; checkpoints + AsyncPostgresStore (post-2026-04-25 migration) |
| 5434 | Zero Postgres (container) | `zero-postgres` | **Added 2026-04-27** to canonical map after observed via `docker ps`; was not in original ARCHITECTURE.md table. Database `zero` |
| 5436 | FortressOS Postgres (container) | `fortress-postgres` (per legion_config) | Database `fortress_of_solitude` |
| 8000 | Reachy Mini daemon | `reachy-apps` daemon | **HARDCODED â€” DO NOT COLLIDE** |
| 8001 | vLLM embed | `vllm-embed` (Qwen3-Embedding-0.6B) | ~1.5 GB VRAM |
| 8003 | Ada backend (container internal) | `ada-backend` | Maps to host :8006 |
| 8005 | Legion backend | `legion-backend` (FastAPI) | |
| 8006 | Ada backend (host) | `ada-backend` (mapped) | |
| 8123 | Home Assistant | `homeassistant` | Eight Sleep, MQTT, voice |
| 18792 | Zero backend | `zero-backend` (FastAPI) | |
| 18800 | llama.cpp chat | `llama-cpp-chat` (Qwen3.6-35B-A3B GGUF Q4_K_M) | Container :8000 â†’ host :18800; ~22 GB VRAM; Reachy keeps host :8000 |

## Probe order each run

1. 4444 (LiteLLM) â€” gates everything LLM
2. 18800 (llama.cpp chat)
3. 8001 (vLLM embed)
4. 18792 / 8005 / 8006 (the three project backends)
5. 5432 (Postgres native)
6. 5433 (Legion Postgres container)
7. 8000 (Reachy â€” must be Reachy, not vLLM squatting)

## Critical collisions to detect

- **8000**: if vLLM, anything else, or nothing is here, Reachy daemon will not
  start. Critical.
- **5432 vs 5433 vs 5434**: native + Legion + Zero Postgres should all be up;
  only native (`:5432`) means Legion/Zero containers haven't started.
- **4444**: if down, Legion and Zero LLM calls fail. Ollama at 11434 is the
  documented fallback.

## Known runtime-config drift to catch in Phase F

- **Legion `legion_config.py` zero-postgres port** says `:5433` (line ~140);
  actual zero-postgres container is `:5434`. Likely a stale config from
  before zero got its own container. Audit should verify by reading the
  config file vs `docker ps` output.

