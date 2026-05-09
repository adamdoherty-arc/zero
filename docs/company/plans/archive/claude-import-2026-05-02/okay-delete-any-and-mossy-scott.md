# Plan: Retire Ollama, optimize vLLM, full rename

## Context

The personal-AI ecosystem (Zero, Legion, Ada + shared-infra) historically supported Ollama as a "swap-on-demand" local backend alongside vLLM. The user has decided Ollama is **fully retired** — vLLM is the only local inference path. Three motivators:

1. **It's not actually used.** Every project's `.env` already sets `LOCAL_LLM_BACKEND=vllm`; Ollama traffic is zero in production. Legion's `LLMProvider.OLLAMA` enum and `ModelType.OLLAMA_QWEN_CODER_NEXT` are *routing identities that already resolve to vLLM at runtime* — the name lies.
2. **Drift surface.** The audit on 2026-04-27 caught 404s in vLLM logs caused by Ollama-style model tags (`qwen3.6:35b-a3b-q4_K_M`) leaking into vLLM callers. Two naming schemes for the same model is a permanent footgun.
3. **Maintenance tax.** ~57 files, ~180 references, a 925-line `ollama_experiment_agent.py` daemon, a 590-line `ollama_client.py`, two database tables, ~7.5k stale `llm_call_details` rows. All maintenance for a path the user doesn't use.

Outcome: the ecosystem ships with **vLLM only** for local inference, with cloud fallback through LiteLLM (Kimi → MiniMax → Anthropic → Gemini → OpenRouter). vLLM serving config is tuned for the current Qwen3-32B-AWQ baseline on the 32 GB RTX 5090. All Ollama refs are removed; identifiers are renamed; database is archived.

## Decisions (locked from user input)

- **Full rename** — `LLMProvider.OLLAMA` → `LLMProvider.LOCAL_VLLM`, `ModelType.OLLAMA_QWEN_CODER_NEXT` → `ModelType.VLLM_QWEN_CHAT`, metric labels `legion_ollama_*` → `legion_local_llm_*`. Touches ~30 files; Grafana/Prometheus dashboard labels become a separate follow-up.
- **Archive-then-drop** — Alembic migration renames `ollama_model`/`ollama_report` tables to `_archived_*`; rewrites `llm_call_details.provider='ollama'` → `'legacy_local'`; deletes 9 `prompt_templates` rows with `provider_override='ollama'`.
- **vLLM batch tokens bumped to 4096** with `--enable-chunked-prefill` (chunked-prefill makes the bump safe).

## Scope

**In:** zero/, Legion/, ADA/, shared-infra/, ArchitectureMaster/ (canonical docs + audit skill state), vault references, top-level start scripts.

**Out:**
- `c:\code\reachy-apps\` — Reachy SDK is unrelated; only Reachy's own `:8000` reservation needs to stay correct (already is)
- Legion's `useGpuManager.ts` frontend hook — manages GPU mode (CPU/GPU), not LLM provider; keep as-is
- The `:11434` references in archive-only files (`Legion/backend/docs/_archive/`) — historical artifacts; leave
- Ollama as a host-installed binary at `~/AppData/Local/Programs/Ollama/` — not touching the user's installed software
- Anthropic SDK 0.86 CVE rebuild (separate queue item)

## Phase A — Code deletes (no live callers, safe to remove first)

These can be deleted without breaking anything because nothing imports them after Phase B.

| File | Action | Lines | Why safe |
|------|--------|-------|----------|
| [c:\code\zero\backend\app\infrastructure\ollama_client.py](c:/code/zero/backend/app/infrastructure/ollama_client.py) | Delete | 590 | After Phase B, `unified_llm_client.py` no longer imports it |
| [c:\code\zero\backend\app\infrastructure\llm_providers\ollama_provider.py](c:/code/zero/backend/app/infrastructure/llm_providers/ollama_provider.py) | Delete | 74 | After provider registry update |
| [c:\code\Legion\backend\app\services\llm_clients\ollama_client.py](c:/code/Legion/backend/app/services/llm_clients/ollama_client.py) | Delete | 50+ | `_local_llm_client_class()` collapses to vLLM-only in Phase B |
| [c:\code\Legion\backend\app\agents\llm_ops\provider_adapters\ollama.py](c:/code/Legion/backend/app/agents/llm_ops/provider_adapters/ollama.py) | Delete | 50+ | No callers after MODEL_REGISTRY rename |
| [c:\code\Legion\backend\app\agents\ollama_experiment_agent.py](c:/code/Legion/backend/app/agents/ollama_experiment_agent.py) | Delete | 925 | Daemon registration removed in Phase D |
| [c:\code\Legion\backend\app\services\ollama_manager_service.py](c:/code/Legion/backend/app/services/ollama_manager_service.py) | Delete | ~600 | Per F12 (Fix-47) the daily daemon is already retired; only `format_size()` helper called from `project_grader_service.py` — inline that helper into `project_grader_service.py` first, then delete the file |
| [c:\code\Legion\.claude\skills\legion-ollama-experimenter\](c:/code/Legion/.claude/skills/legion-ollama-experimenter/) | Delete dir | — | Skill for retired daemon |
| [c:\code\Legion\.agents\skills\legion-ollama-experimenter\](c:/code/Legion/.agents/skills/legion-ollama-experimenter/) | Delete dir | — | Mirror of above |
| [c:\code\ArchitectureMaster\start-ollama.ps1](c:/code/ArchitectureMaster/start-ollama.ps1) | Delete | 46 | Standalone Ollama startup; nothing else calls it |
| [c:\code\Legion\backend\tests\services\test_ollama_manager.py](c:/code/Legion/backend/tests/services/test_ollama_manager.py) | Delete | 1291 | Service is gone; tests have no target |

**Order matters within Phase A:** inline `OllamaManagerService.format_size()` into `project_grader_service.py` *before* deleting `ollama_manager_service.py`.

## Phase B — Legion identifier rename (LLMProvider.OLLAMA → LLMProvider.LOCAL_VLLM)

Single sweep across Legion to rename the routing identity. Can use targeted replace_all in each file.

**Renames:**
| From | To | File scope |
|------|----|-----|
| `LLMProvider.OLLAMA` | `LLMProvider.LOCAL_VLLM` | All Legion code |
| `ModelType.OLLAMA_QWEN_CODER_NEXT` | `ModelType.VLLM_QWEN_CHAT` | All Legion code |
| `_ollama_semaphore` | `_local_llm_semaphore` | [unified_llm_service.py](c:/code/Legion/backend/app/services/unified_llm_service.py#L92) |
| `_ollama_queue_depth` | `_local_llm_queue_depth` | [unified_llm_service.py:93](c:/code/Legion/backend/app/services/unified_llm_service.py#L93) + dashboard endpoint |
| `_ollama_circuit` / `ollama_breaker` | `_local_llm_circuit` / `local_llm_breaker` | [circuit_breaker.py](c:/code/Legion/backend/app/services/circuit_breaker.py) + import sites |
| `_ollama_disabled()` | Delete (replace callers with `False` literal — backend is always vLLM now) | [unified_llm_service.py:315-318, 355, 863](c:/code/Legion/backend/app/services/unified_llm_service.py) |
| `OLLAMA_AVAILABLE_TAGS` / `OLLAMA_THINKING_TAGS` / `OLLAMA_CONTEXT_WINDOWS` / `OLLAMA_DEFAULT_TAG` | `VLLM_AVAILABLE_MODELS` / `VLLM_THINKING_MODELS` / `VLLM_CONTEXT_WINDOWS` / `VLLM_DEFAULT_MODEL` | [legion_config.py:801-804](c:/code/Legion/backend/app/core/legion_config.py) |
| `OLLAMA_ESCALATION` / `OLLAMA_FALLBACK` | `LOCAL_LLM_ESCALATION` / `LOCAL_LLM_FALLBACK` | [legion_config.py:675-688](c:/code/Legion/backend/app/core/legion_config.py) |
| `get_ollama_tag()` | `get_vllm_model()` (returns canonical alias `qwen3-chat`) | [legion_config.py:762-775](c:/code/Legion/backend/app/core/legion_config.py) |
| `ollama_tag` field in MODEL_REGISTRY | `vllm_model` (still resolves to `qwen3-chat`) | [legion_config.py:162+](c:/code/Legion/backend/app/core/legion_config.py) |

**Prometheus metric renames** (in `metrics_service.py` or wherever `Counter`/`Gauge` are defined):
| From | To |
|------|----|
| `legion_ollama_tier2_gate_passed` | `legion_local_llm_tier2_gate_passed` |
| `legion_llm_provider_override_total{provider="ollama"}` | `legion_llm_provider_override_total{provider="local_vllm"}` |
| `legion_provider_override_rolled_back_total` | unchanged (label change only) |
| `legion_llm_cost_savings_usd_total` | unchanged |

**TIER_ALIASES** at [legion_config.py:655-660](c:/code/Legion/backend/app/core/legion_config.py#L655):
```python
TIER_ALIASES: Dict[str, ModelType] = {
    "primary": ModelType.VLLM_QWEN_CHAT,
    "sonnet":  ModelType.VLLM_QWEN_CHAT,
    "opus":    ModelType.VLLM_QWEN_CHAT,
    "haiku":   ModelType.VLLM_QWEN_CHAT,
}
```
Replace the misleading comment block at lines 651-654 with one explaining the local-only-vLLM strategy.

## Phase C — Refactor `unified_llm_service.py` local-client resolution

[unified_llm_service.py:47-62](c:/code/Legion/backend/app/services/unified_llm_service.py#L47-L62) currently:
```python
def _local_llm_client_class():
    backend = os.getenv("LOCAL_LLM_BACKEND", "ollama").strip().lower()
    if backend == "vllm":
        from .llm_clients.vllm_client import VLLMClient
        return VLLMClient
    from .llm_clients.ollama_client import OllamaClient
    return OllamaClient
```

Becomes:
```python
def _local_llm_client_class():
    """Local LLM is always vLLM via shared-infra. Cloud paths use LiteLLM router."""
    from .llm_clients.vllm_client import VLLMClient
    return VLLMClient
```

Drop the `LOCAL_LLM_BACKEND` env var read; document in comment that the env var is deprecated.

Also remove these helpers/state in the same file:
- `_ollama_disabled()` classmethod (lines 315-318) — no longer meaningful
- `_LEARN19_MINIMAX_COST_PER_CALL_USD` constant (line 71) and any reference to "MiniMax cost savings via Ollama override" — that whole framing is dead
- The Learn-18/Learn-19 cost-savings logic that credits "savings" when an "Ollama override" routes a call. With vLLM as the only local backend, there's no override; rip it out.

## Phase D — Remove Ollama daemons

[c:\code\Legion\backend\main.py:585-605](c:/code/Legion/backend/main.py#L585-L605) — delete the entire `try: ollama_exp_enabled = ...` block (lines 588-605) including the import of `start_ollama_experiment_daemon`. Leave the F12/Fix-47 historical-note comment (line 607-610) but update it to say "Ollama subsystems retired 2026-04-27 per ecosystem-audit run." Then delete the comment block in a follow-up cleanup.

Also search Legion `main.py` for any `task_registry.register("ollama_*", ...)` and remove.

## Phase E — Database migration

New Alembic migration: `c:\code\Legion\backend\alembic\versions\025_retire_ollama.py`.

```python
"""retire_ollama_tables_and_relabel_call_history

Revision ID: 025_retire_ollama
Revises: <previous head>
Create Date: 2026-04-27
"""
from alembic import op

def upgrade():
    # 1. Archive tables (rename, not drop — reversible)
    op.rename_table("ollama_model",  "_archived_ollama_model")
    op.rename_table("ollama_report", "_archived_ollama_report")

    # 2. Relabel ~7.5k llm_call_details rows
    op.execute(
        "UPDATE llm_call_details SET provider = 'legacy_local' "
        "WHERE provider = 'ollama'"
    )

    # 3. Delete the 9 active prompt_templates with provider_override='ollama'
    op.execute("DELETE FROM prompt_templates WHERE provider_override = 'ollama'")

def downgrade():
    op.rename_table("_archived_ollama_model",  "ollama_model")
    op.rename_table("_archived_ollama_report", "ollama_report")
    op.execute(
        "UPDATE llm_call_details SET provider = 'ollama' "
        "WHERE provider = 'legacy_local'"
    )
    # prompt_templates rows can't be restored from this migration
```

Apply on `legion-postgres` with the audit's bypass-permissions mode active. After:
- Run `SELECT COUNT(*) FROM _archived_ollama_model;` to confirm row count preserved.
- Run `SELECT COUNT(*) FROM llm_call_details WHERE provider='ollama';` → should be 0.
- Run `SELECT COUNT(*) FROM prompt_templates WHERE provider_override='ollama';` → should be 0.

## Phase F — Config cleanup

### F.1 — `.env` files (all three projects)

Remove every `OLLAMA_*` variable. **Do NOT delete** `LOCAL_LLM_BACKEND` from `.env` files yet — leave as `=vllm` for one cycle as a defensive default in case any code path missed the rename.

| File | Lines to remove |
|------|------|
| [c:\code\zero\.env](c:/code/zero/.env) | All `OLLAMA_*` definitions |
| [c:\code\Legion\backend\.env](c:/code/Legion/backend/.env) | All `OLLAMA_*` definitions including `OLLAMA_DISABLED=true` |
| [c:\code\ADA\.env](c:/code/ADA/.env) | All `OLLAMA_*` definitions if present |
| [c:\code\zero\.env.example](c:/code/zero/.env.example) | Same |
| [c:\code\Legion\.env.example](c:/code/Legion/.env.example) | Same |
| [c:\code\Legion\env.template](c:/code/Legion/env.template) | Same |

### F.2 — Zero infrastructure config

[c:\code\zero\backend\app\infrastructure\config.py:29-33](c:/code/zero/backend/app/infrastructure/config.py#L29-L33) — delete the four `ollama_*` Settings fields (`ollama_base_url`, `ollama_model`, `ollama_chat_model`, `ollama_timeout`). Remove `local_llm_backend` field too OR keep with `default="vllm"` and a deprecation comment.

[c:\code\zero\backend\app\infrastructure\llm_router.py](c:/code/zero/backend/app/infrastructure/llm_router.py) — remove any `if backend == "ollama"` branches. Search for `ollama` in all files under `c:\code\zero\backend\app\infrastructure\` and `c:\code\zero\backend\app\services\` and remove.

### F.3 — Legion core config

[c:\code\Legion\backend\app\core\config.py:47](c:/code/Legion/backend/app/core/config.py#L47) — delete `LOCAL_LLM_URL: str = "http://localhost:11434"` field. Default `LOCAL_LLM_BACKEND` field can stay with `="vllm"`.

[c:\code\Legion\backend\app\core\legion_config.py:162-171](c:/code/Legion/backend/app/core/legion_config.py#L162-L171) — delete the entire `"ollama_manager"` MANAGED_PROJECTS entry. Note: Zero project's `tech_stack: ["Ollama", "Python"]` at line 135 — change to `["vLLM", "Python"]`.

[c:\code\Legion\backend\app\core\free_models.py](c:/code/Legion/backend/app/core/free_models.py) — search and remove Ollama listings.

### F.4 — LiteLLM config

[c:\code\shared-infra\litellm\config.yaml](c:/code/shared-infra/litellm/config.yaml):

1. **Header comment** (lines 5-23) — remove the `ollama/<tag>` line and the Ollama section. Update line 12 stale comment claiming `qwen3-chat` is served by `QuantTrio/Qwen3.6-35B-A3B-AWQ` to say `Qwen/Qwen3-32B-AWQ`.
2. **Delete legacy Ollama-style alias shims** (lines 54-70) — three entries: `qwen3.6:35b-a3b-q4_K_M`, `qwen3.6:35b-a3b-q8_0`, `QuantTrio/Qwen3.6-35B-A3B-AWQ`.
3. **Keep** the `Qwen/Qwen3.6-35B-A3B-FP8` and `Qwen/Qwen3-32B-AWQ` HF-style aliases (lines 42-52) as legacy callers' insurance — they're not Ollama-flavored.
4. **Delete the `ollama-qwen3-chat` model entry** (lines 206-211).

After: 5 model_list entries removed, 1 comment block trimmed.

### F.5 — Docker compose files

[c:\code\Legion\docker-compose.yml](c:/code/Legion/docker-compose.yml) — remove `OLLAMA_NATIVE_URL` and `OLLAMA_API_KEY` env passes (lines 93-94 per Agent 1 finding).

[c:\code\zero\docker-compose.sprint.yml](c:/code/zero/docker-compose.sprint.yml) — remove any `:11434` port mapping or env passes.

[c:\code\shared-infra\docker-compose.vllm.yml](c:/code/shared-infra/docker-compose.vllm.yml):
- Header comment (lines 5-17) — already corrected in this session, but double-check Ollama refs in the swap-history comments.
- LiteLLM proxy `extra_hosts: host.docker.internal:host-gateway` (line 174) — keep (still useful for any host-side service LiteLLM might call); the comment "Lets LiteLLM reach Ollama on the Windows host..." needs to be rewritten to drop the Ollama reference.

### F.6 — Startup script

[c:\code\ArchitectureMaster\start-ecosystem.bat](c:/code/ArchitectureMaster/start-ecosystem.bat):
- Lines 31-33 — drop `11434` from the port-conflict check loop.
- Lines 40-58 — delete the entire "[2/6] Checking Ollama" block.
- Renumber subsequent steps from `[2/6]` (Legion now becomes [2/5]).
- Lines 142-145 — delete the Ollama health summary block.
- Update the bumped step count throughout (`[1/5]` through `[5/5]`).
- Bug fix while we're here: line 84 `cd /d C:\code\moltbot` is a stale path; should be `c:\code\zero` (this is unrelated to Ollama but trivial to fix in same edit pass).

## Phase G — vLLM optimization

[c:\code\shared-infra\docker-compose.vllm.yml:56-66](c:/code/shared-infra/docker-compose.vllm.yml#L56-L66) — add three flags to the `command:` block:

```yaml
command: >
  --model Qwen/Qwen3-32B-AWQ
  --served-model-name qwen3-chat qwen3-coder
  --port 8000
  --host 0.0.0.0
  --max-model-len 12288
  --gpu-memory-utilization 0.90
  --kv-cache-dtype fp8
  --dtype auto
  --quantization awq_marlin           # NEW: explicit (was auto-detected)
  --enable-prefix-caching
  --enable-chunked-prefill            # NEW: improves TTFT, makes batched-tokens bump safe
  --max-num-batched-tokens 4096       # CHANGED: 2096 → 4096
```

Verify after restart:
- `docker logs vllm-chat 2>&1 | grep -iE "(awq.marlin|chunked.prefill)"` should show both kernels initialized.
- `nvidia-smi --query-gpu=memory.used --format=csv` — should be ≤ 95% of 32 GB (currently 95.7%).
- Smoke test: POST to `:18800/v1/chat/completions` with the standard "what is 2+2" request; expect 200 + token output ≥ 50.
- Latency check: time a 1024-token prompt completion before vs after; chunked-prefill should reduce TTFT by ~20-30%.

vllm-embed config is already optimal — no changes.

LiteLLM config — already on `1.83.7-stable` from this session's earlier work. No version change needed.

## Phase H — Tests

| File | Action |
|------|--------|
| [c:\code\zero\backend\tests\infrastructure\test_llm_router_live.py](c:/code/zero/backend/tests/infrastructure/test_llm_router_live.py) | Remove `elif backend == "ollama"` branch at line 22 |
| [c:\code\zero\backend\tests\conftest.py](c:/code/zero/backend/tests/conftest.py) | Remove Ollama fixtures/mocks |
| [c:\code\zero\backend\tests\infrastructure\test_llm_router_backend_toggle.py](c:/code/zero/backend/tests/infrastructure/test_llm_router_backend_toggle.py) | The toggle is dead — delete the file |
| [c:\code\Legion\backend\tests\services\test_llm_router_backend_toggle.py](c:/code/Legion/backend/tests/services/test_llm_router_backend_toggle.py) | Same — delete |
| [c:\code\Legion\backend\tests\services\test_unified_llm_service.py](c:/code/Legion/backend/tests/services/test_unified_llm_service.py) | Remove Ollama-specific test cases; keep tests for the renamed `LLMProvider.LOCAL_VLLM` paths |
| [c:\code\Legion\backend\tests\services\test_unified_llm.py](c:/code/Legion/backend/tests/services/test_unified_llm.py) | Same |
| [c:\code\ADA\backend\tests\test_llm_router_backend_toggle.py](c:/code/ADA/backend/tests/test_llm_router_backend_toggle.py) | Delete |

After: run `pytest c:/code/Legion/backend/tests/services/ -k "llm or unified"` and `pytest c:/code/zero/backend/tests/infrastructure/` to confirm green.

## Phase I — Documentation + audit lib

### I.1 — Canonical docs

| File | Edit |
|------|------|
| [c:\code\ArchitectureMaster\docs\ARCHITECTURE.md:41](c:/code/ArchitectureMaster/docs/ARCHITECTURE.md#L41) | Delete the "Ollama :11434 fallback" line |
| [c:\code\ArchitectureMaster\docs\ARCHITECTURE.md:105](c:/code/ArchitectureMaster/docs/ARCHITECTURE.md#L105) | Delete the `ollama-qwen3-chat` row from the model routing table |
| [c:\code\ArchitectureMaster\README.md:22](c:/code/ArchitectureMaster/README.md#L22) | Delete the `:11434 Ollama` row from port map |
| [c:\code\ArchitectureMaster\README.md:74](c:/code/ArchitectureMaster/README.md#L74) | Delete the `curl http://localhost:11434/api/tags` health check line |
| [c:\code\Legion\docs\ARCHITECTURE.md](c:/code/Legion/docs/ARCHITECTURE.md) | Search for Ollama refs in model routing table; delete |
| [c:\code\Legion\docs\LEGION_OVERVIEW.md](c:/code/Legion/docs/LEGION_OVERVIEW.md) | Search and delete Ollama refs |
| [c:\code\zero\docs\ARCHITECTURE.md](c:/code/zero/docs/ARCHITECTURE.md) | Search and delete Ollama refs |
| [c:\code\ADA\docs\AUDIT_REPORT.md](c:/code/ADA/docs/AUDIT_REPORT.md) | Search and delete (note: this is a historical audit; OK to leave with a "(retired)" note instead of deleting) |
| [c:\code\claude\docs\AgenticOs.md:41](c:/code/claude/docs/AgenticOs.md#L41) | Delete the Ollama fallback mention |
| [c:\code\zero\docs\SecondBrain.md](c:/code/zero/docs/SecondBrain.md) (and its 2 mirrored copies) | Search and delete Ollama refs |

### I.2 — Vault

[c:\code\vault\ObsidianZero\40_Resources\llm-models.md:32](c:/code/vault/ObsidianZero/40_Resources/llm-models.md#L32) — delete the "Local — fallback | `ollama-qwen3-chat`" row. Bump `last_reviewed: 2026-04-27` (keep current). Add an audit footer.

[c:\code\vault\ObsidianZero\10_Atlas\MOCs\SecondBrain_Strategy.md](c:/code/vault/ObsidianZero/10_Atlas/MOCs/SecondBrain_Strategy.md) — search for Ollama refs and delete (or mark "(retired)" if it's a historical strategy doc).

### I.3 — Audit skill state

| File | Edit |
|------|------|
| [.claude/skills/ecosystem-audit/lib/port-map.md:23](c:/code/ArchitectureMaster/.claude/skills/ecosystem-audit/lib/port-map.md#L23) | Delete `:11434 Ollama` row |
| [.claude/skills/ecosystem-audit/lib/port-map.md:35](c:/code/ArchitectureMaster/.claude/skills/ecosystem-audit/lib/port-map.md#L35) | Remove `:11434` from probe order |
| [.claude/skills/ecosystem-audit/lib/models-baseline.md:32](c:/code/ArchitectureMaster/.claude/skills/ecosystem-audit/lib/models-baseline.md#L32) | Delete `ollama-qwen3-chat` row |
| [.claude/skills/ecosystem-audit/lib/managed-projects.md:21](c:/code/ArchitectureMaster/.claude/skills/ecosystem-audit/lib/managed-projects.md#L21) | Delete `ollama_manager` virtual project row |
| [.claude/skills/ecosystem-audit/SKILL.md](c:/code/ArchitectureMaster/.claude/skills/ecosystem-audit/SKILL.md) Phase C step 3 PowerShell port loop | Remove `11434` from the port list |
| [.claude/skills/ecosystem-audit/SKILL.md](c:/code/ArchitectureMaster/.claude/skills/ecosystem-audit/SKILL.md) Phase C step 4 health endpoints | No Ollama line was there; verify |
| [.claude/state/ecosystem-audit/INSIGHTS.md](c:/code/ArchitectureMaster/.claude/state/ecosystem-audit/INSIGHTS.md) | Add a new INSIGHTS entry: "Ollama retired ecosystem-wide 2026-04-27. Future audits never probe :11434 or treat Ollama-named subsystems as live." |
| [.claude/state/ecosystem-audit/EVOLUTION.md](c:/code/ArchitectureMaster/.claude/state/ecosystem-audit/EVOLUTION.md) | Add an EVOLUTION entry: "Phase C port probe loop drops :11434. Phase F project freshness no longer checks for Ollama containers. Phase E LiteLLM config audit no longer expects `ollama/*` model_list entries." |
| [.claude/state/ecosystem-audit/ACTION_QUEUE.md](c:/code/ArchitectureMaster/.claude/state/ecosystem-audit/ACTION_QUEUE.md) | Mark `ollama-references-stale-in-canonical-docs` ✅ RESOLVED. Add a follow-up item: `grafana-prometheus-label-rename` (HIGH, write_external) for updating dashboard panels with new metric labels. |

The [feedback memory](C:/Users/hadam/.claude/projects/c--code-ArchitectureMaster/memory/feedback_no_ollama.md) saved earlier this session stays as-is — still valid guidance.

## Verification

After all phases applied:

1. **Grep should be clean**:
   ```bash
   for d in zero Legion ADA shared-infra ArchitectureMaster; do
     grep -rEni "ollama|11434" c:/code/$d \
       --exclude-dir={__pycache__,node_modules,.venv,.next,dist,build,_archive} \
       --exclude="*.pyc" \
       | grep -vE "(\.archive|_archive|/archive|memory/feedback_no_ollama|ACTION_QUEUE|INSIGHTS|EVOLUTION|runs/2026-)"
   done
   ```
   Expected: empty (the audit skill state files are allowed to keep refs because they're the cleanup record; the feedback memory keeps refs intentionally).

2. **Containers all healthy**:
   ```bash
   docker ps --format '{{.Names}}|{{.Status}}'
   ```
   Expect: all 28 containers running, no portainer on `:8000`, no ollama or legion-litellm.

3. **vLLM serving correctly**:
   ```bash
   curl -m 5 http://localhost:18800/v1/models
   ```
   Expect: `qwen3-chat` + `qwen3-coder` aliases, `root: Qwen/Qwen3-32B-AWQ`.

4. **vLLM optimization landed**:
   ```bash
   docker logs vllm-chat 2>&1 | grep -iE "(awq.marlin|chunked.prefill|max.num.batched.tokens)"
   ```
   Expect: AWQ-Marlin kernel selected, chunked-prefill enabled, batched-tokens=4096.

5. **LiteLLM routing**:
   ```bash
   curl -m 5 -H "Authorization: Bearer $LITELLM_MASTER_KEY" http://localhost:4444/v1/models | jq '.data[].id'
   ```
   Expect: no entries containing "ollama" or "qwen3.6:35b-a3b" GGUF tags.

6. **Smoke test through full stack**:
   ```bash
   curl -X POST http://localhost:4444/v1/chat/completions \
        -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
        -H "Content-Type: application/json" \
        -d '{"model":"qwen3-chat","messages":[{"role":"user","content":"In one sentence: what is 2+2?"}]}'
   ```
   Expect: 200 + reasoning content.

7. **Legion health post-rename**:
   ```bash
   curl -m 5 http://localhost:8005/health | jq '.llm'
   ```
   Expect: `active_provider: "vllm"` (string may rename to `local_vllm`); no `ollama_disabled`/`ollama_queue_depth` fields; new `local_llm_queue_depth` instead.

8. **Database migration applied**:
   ```sql
   -- legion-postgres :5433
   SELECT table_name FROM information_schema.tables WHERE table_name LIKE '%ollama%';
   -- expect: _archived_ollama_model, _archived_ollama_report only
   SELECT COUNT(*) FROM llm_call_details WHERE provider='ollama';  -- 0
   SELECT COUNT(*) FROM prompt_templates WHERE provider_override='ollama';  -- 0
   ```

9. **Tests green**:
   ```bash
   pytest c:/code/Legion/backend/tests/services/ -k "llm or unified" -v
   pytest c:/code/zero/backend/tests/infrastructure/ -v
   ```

10. **Re-run ecosystem audit** (`/ecosystem-audit`) — expect 0 Ollama-related findings.

## Risks & rollback

| Risk | Mitigation | Rollback |
|------|-----------|----------|
| Renaming `LLMProvider.OLLAMA` breaks a code path the agents missed | Phase B uses `replace_all` per file; after each file, run `python -c "from app.services.unified_llm_service import UnifiedLLMService"` smoke import | `git revert` Phase B commits |
| Database migration loses data | `_archived_*` tables preserve all rows; `provider='ollama'`→`'legacy_local'` is reversible | `alembic downgrade -1` |
| vLLM optimization OOMs on first batch | Phase G changes are well-known safe additions; chunked-prefill makes batched-tokens=4096 safe | `git revert` compose change + `docker compose up -d vllm-chat` |
| Grafana dashboards break (label rename) | Filed as separate ACTION_QUEUE item `grafana-prometheus-label-rename`. Old metric values will simply stop incrementing; new metric values appear under new labels. Operators see flat lines on old panels until dashboards updated | Rename one metric back via Prometheus relabeling rule if a dashboard is critical; otherwise update dashboard JSON |
| LangFuse traces tagged with old `_source` strings still query-able | Trace tags by source name not provider; no impact | None needed |
| A daemon I missed still imports `OllamaClient` and crashes | Search `c:\code\Legion\backend\` for `from .ollama_client import` and `import ollama_client` before deleting | If crash at runtime, container restart loop until import is removed; harmless because Legion's supervisor restarts it |

## Sequencing

Wave 1 (parallel, no inter-dependencies): Phase A code deletes, Phase F.1/.2/.3/.4/.5/.6 config edits, Phase G vLLM optimization, Phase I docs.

Wave 2 (after Wave 1): Phase B identifier rename across Legion. Run smoke imports after each file group.

Wave 3 (after Wave 2): Phase C `unified_llm_service` simplification, Phase D daemon removal in `main.py`, Phase H test updates.

Wave 4: Phase E database migration (Alembic upgrade).

Wave 5: Verification + restart `legion-backend` + restart `vllm-chat` + smoke tests + re-run `/ecosystem-audit`.

Estimated work: ~3-4 hours focused, with vLLM restart adding 12-15 min cold-start (warmup of cudagraph cache). One PR-equivalent atomic change set.
