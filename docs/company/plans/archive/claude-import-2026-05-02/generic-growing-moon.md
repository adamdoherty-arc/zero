# Unified Single-Model Strategy Across ALL Projects
## 2026-04-11

---

## Context

Each managed project has its **own independent LLM router** that calls Ollama directly — they do NOT go through Legion's `unified_llm_service`. The current state is inconsistent and causing failures.

**Additionally**: Legion uses MiniMax M2 for planning, while ADA uses MiniMax M2.7. User decision: standardize on **M2.7** everywhere.

| Project | Router | Current Execution Model | Problem |
|---------|--------|------------------------|---------|
| **Legion** | `unified_llm_service.py` | qwen3-coder-next | OK (just updated) |
| **ADA** | `backend/infrastructure/llm_router.py` | **qwen3.5:35b-a3b** | Evicts qwen3-coder-next from VRAM |
| **FortressOS** | `backend/app/infrastructure/llm_router.py` | **gemma4:e4b** | Model was REMOVED — broken |
| **AIContentTools** | `backend/llm_service.py` | **5 removed models** | Completely broken |

**Root cause of VRAM eviction**: ADA uses `qwen3.5:35b-a3b` (28GB). When ADA makes a call, Ollama loads that model, evicting Legion's `qwen3-coder-next` (51GB). Next Legion call → 30-180s reload → timeouts → 48% error spike.

**Solution**: Force ALL projects to use `qwen3-coder-next` for execution. One model in VRAM at all times. Zero evictions.

---

## Unified Routing Strategy (All Projects)

| Task Category | Model | Provider |
|---------------|-------|----------|
| All execution (code, analysis, docs, general) | `qwen3-coder-next` | Ollama (local) |
| Planning / Architecture / Research | **MiniMax M2.7** | Cloud |
| Planning fallback | Kimi K2.5 | Cloud |
| Embeddings | `nomic-embed-text-v2-moe` | Ollama (local) |

---

## Change 0: Upgrade Legion from MiniMax M2 → M2.7

**File:** `C:/code/Legion/backend/app/core/legion_config.py`

Two changes:
1. Line ~616: Update `display_name` and pricing in MODEL_REGISTRY
2. Line ~830: Update `MINIMAX_MODEL_MAP` to send `"MiniMax-M2.7"` to the API

```python
# Before (line ~612-620):
ModelType.MINIMAX_M2: ModelConfig(
    ...
    display_name="MiniMax M2 (200K ctx, agent-optimized)",
    cost_per_1m_input=0.255,
    cost_per_1m_output=1.00,
    ...
)

# After:
ModelType.MINIMAX_M2: ModelConfig(
    ...
    display_name="MiniMax M2.7 (200K ctx, multimodal, agent-optimized)",
    cost_per_1m_input=0.30,
    cost_per_1m_output=1.20,
    ...
)

# Before (line ~830):
MINIMAX_MODEL_MAP: Dict[str, str] = {
    ModelType.MINIMAX_M2.value: "MiniMax-M2",
}

# After:
MINIMAX_MODEL_MAP: Dict[str, str] = {
    ModelType.MINIMAX_M2.value: "MiniMax-M2.7",
}
```

**Effect:** Legion sends `"MiniMax-M2.7"` to the MiniMax API. No enum changes needed — the internal `ModelType.MINIMAX_M2` enum stays the same (it's just an internal key), only the API-facing model name changes. Cost tracking updates automatically via the pricing fields.

---

## Change 1: ADA Router

**File:** `C:/code/ADA/backend/infrastructure/llm_router.py` lines 131-176

Update `MODELS` registry and `ROUTING_TABLE`:

```python
# Before:
MODELS = {
    "qwen3-coder-next": ModelConfig("qwen3-coder-next", 32768, ...),
    "qwen3.5:35b-a3b": ModelConfig("qwen3.5:35b-a3b", 262144, ...),
    "gemma4:31b": ...,  # removed
    "gemma4:26b": ...,  # removed
    "gemma4:e4b": ...,  # removed
    "gemma4:e2b": ...,  # removed
}

ROUTING_TABLE = {
    TaskType.PLANNING: ["minimax-m2.7", "qwen3.5:35b-a3b"],
    TaskType.CODE_GEN: ["qwen3.5:35b-a3b"],
    ... all others: ["qwen3.5:35b-a3b"]
}

# After:
MODELS = {
    "qwen3-coder-next": ModelConfig("qwen3-coder-next", 65536, supports_tools=True),
}

ROUTING_TABLE = {
    TaskType.PLANNING:           ["minimax-m2.7", "qwen3-coder-next"],
    TaskType.CODE_GEN:           ["qwen3-coder-next"],
    TaskType.CODE_REVIEW:        ["qwen3-coder-next"],
    TaskType.CODE_ANALYSIS:      ["qwen3-coder-next"],
    TaskType.FINANCIAL_ANALYSIS: ["qwen3-coder-next"],
    TaskType.TECHNICAL_ANALYSIS: ["qwen3-coder-next"],
    TaskType.RESEARCH:           ["minimax-m2.7", "qwen3-coder-next"],
    TaskType.REASONING:          ["qwen3-coder-next"],
    TaskType.GENERAL:            ["qwen3-coder-next"],
    TaskType.DOCUMENTATION:      ["qwen3-coder-next"],
}
```

**Effect:** ADA stops loading qwen3.5:35b-a3b, eliminating VRAM eviction. All ADA execution routes to the same model Legion uses. ADA already uses M2.7 for planning — no change needed there.

---

## Change 2: FortressOS Router

**File:** `C:/code/fortressOS/backend/app/infrastructure/llm_router.py` lines 94-121

Update `MODELS` and `ROUTING_TABLE`:

```python
# Before:
MODELS = {
    "gemma4:e4b": ModelConfig("gemma4:e4b", 131072, ...),  # REMOVED
    "gemma4:26b": ModelConfig("gemma4:26b", 262144, ...),  # REMOVED
}

ROUTING_TABLE = {
    TaskType.JOB_ANALYSIS: ["gemma4:e4b", "kimi-k2.5", ...],
    ... all tasks: ["gemma4:e4b" or cloud fallbacks]
}

# After:
MODELS = {
    "qwen3-coder-next": ModelConfig("qwen3-coder-next", 65536, supports_tools=True),
}

ROUTING_TABLE = {
    TaskType.JOB_ANALYSIS:        ["qwen3-coder-next", "minimax-m2.7"],
    TaskType.RESUME_MATCHING:     ["qwen3-coder-next", "minimax-m2.7"],
    TaskType.EMAIL_CLASSIFICATION:["qwen3-coder-next", "minimax-m2.7"],
    TaskType.GENERAL:             ["qwen3-coder-next", "minimax-m2.7"],
    TaskType.COVER_LETTER:        ["qwen3-coder-next", "minimax-m2.7"],
    TaskType.INTERVIEW_PREP:      ["qwen3-coder-next", "minimax-m2.7"],
    TaskType.RESUME_ENHANCEMENT:  ["qwen3-coder-next", "minimax-m2.7"],
    TaskType.PLANNING:            ["minimax-m2.7", "kimi-k2.5", "qwen3-coder-next"],
    TaskType.RESEARCH:            ["minimax-m2.7", "kimi-k2.5", "qwen3-coder-next"],
    TaskType.REASONING:           ["qwen3-coder-next", "minimax-m2.7"],
    TaskType.COMPANY_RESEARCH:    ["minimax-m2.7", "kimi-k2.5", "qwen3-coder-next"],
    TaskType.EMBEDDINGS:          ["nomic-embed-text-v2-moe"],
}
```

**Effect:** FortressOS stops trying to use removed gemma4:e4b. All execution routes to qwen3-coder-next. Planning uses MiniMax M2.7 (consistent with ADA + Legion). Remove Claude/Gemini from fallback chains (no keys configured, add noise).

---

## Change 3: AIContentTools

**File:** `C:/code/AIContentTools/backend/llm_service.py` lines 35-48

```python
# Before (ALL models removed from system):
DEFAULT_MODELS = {
    "planner":   "qwen2.5:14b",        # REMOVED
    "generator": "qwen2.5-coder:32b",  # REMOVED
    "reviewer":  "llama3.2-vision:11b", # REMOVED
    "fast":      "llama3.1:8b",         # REMOVED
    "reasoning": "deepseek-r1:32b",     # REMOVED
    "embedding": "nomic-embed-text",
}

# After (single model for all roles):
DEFAULT_MODELS = {
    "planner":   "qwen3-coder-next",
    "generator": "qwen3-coder-next",
    "reviewer":  "qwen3-coder-next",
    "fast":      "qwen3-coder-next",
    "reasoning": "qwen3-coder-next",
    "embedding": "nomic-embed-text-v2-moe",
}
```

**Effect:** AIContentTools becomes functional again. Note: loses vision capability (qwen3-coder-next has no vision). If vision is needed, would need to pull a vision model — but that risks VRAM eviction. For now, text-only is the tradeoff.

---

## Change 4: AIContentTools Ollama URL

**File:** `C:/code/AIContentTools/backend/llm_service.py` line 32

```python
# Before (Docker internal):
OLLAMA_URL = os.getenv("OLLAMA_URL", os.getenv("OLLAMA_BASE_URL", "http://ollama:11434"))

# After (host machine where Ollama runs):
OLLAMA_URL = os.getenv("OLLAMA_URL", os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"))
```

Verify this is correct for AIContentTools' deployment — if it runs in Docker, keep `host.docker.internal:11434`.

---

## NOT Changed: Moltbot/Zero

Moltbot uses OpenAI API directly (no local Ollama). Separate concern — not part of the unified local model strategy. Would require OpenAI API key to function.

---

## Files Modified

| File | Project | Change |
|------|---------|--------|
| `C:/code/Legion/backend/app/core/legion_config.py` | Legion | Upgrade M2 → M2.7 (model name + pricing) |
| `C:/code/ADA/backend/infrastructure/llm_router.py` | ADA | MODELS + ROUTING_TABLE → qwen3-coder-next |
| `C:/code/fortressOS/backend/app/infrastructure/llm_router.py` | FortressOS | MODELS + ROUTING_TABLE → qwen3-coder-next + M2.7 |
| `C:/code/AIContentTools/backend/llm_service.py` | AIContentTools | DEFAULT_MODELS → qwen3-coder-next |

---

## Verification

1. `ollama ps` → only qwen3-coder-next loaded (no qwen3.5:35b-a3b)
2. ADA backend logs: model selection shows qwen3-coder-next (not qwen3.5:35b-a3b)
3. FortressOS: no "model not found" errors for gemma4:e4b
4. AIContentTools: basic LLM call succeeds with qwen3-coder-next
5. After 1 hour: `ollama ps` still shows only qwen3-coder-next (no VRAM eviction)
6. Legion error rate drops from 14.3% toward 0% (no more model swap timeouts)

---

## Execution Order

1. Edit Legion legion_config.py (M2 → M2.7 upgrade: model name + pricing)
2. Rebuild + restart Legion backend
3. Edit ADA llm_router.py (MODELS + ROUTING_TABLE → qwen3-coder-next)
4. Edit FortressOS llm_router.py (MODELS + ROUTING_TABLE → qwen3-coder-next + M2.7)
5. Edit AIContentTools llm_service.py (DEFAULT_MODELS → qwen3-coder-next)
6. Restart any running project backends that use these routers
7. Verify with `ollama ps` — only qwen3-coder-next should be loaded
