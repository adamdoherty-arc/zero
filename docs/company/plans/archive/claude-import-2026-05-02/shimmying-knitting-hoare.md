# LLM Model Review: Kimi, Moonshot V1, MiniMax - Where Zero Needs to Be

## Context

Zero uses 6 LLM providers across 29 task types with a $5/day budget. This review audits the current model landscape, identifies pricing errors, and recommends an optimized routing strategy that takes advantage of thinking models, batch API, and context caching.

---

## 1. Current Model Landscape (Official Pricing, USD/1M tokens)

### Kimi K2.5 (Zero's primary paid brain)
| Metric | Value |
|--------|-------|
| Input (cache miss) | $0.60 |
| Input (cache hit) | $0.10 |
| Output | $3.00 |
| Context | 256K |
| Thinking | **Enabled by default** (output tokens) |
| Batch | 40% off ($0.36 input, $1.80 output) |
| Temperature | Fixed at 1.0 |

### Kimi K2 Family (NOT currently used by Zero)
| Model | Input (miss) | Input (hit) | Output | Context | Speed | Notes |
|-------|-------------|-------------|--------|---------|-------|-------|
| kimi-k2-0905-preview | $0.60 | $0.15 | $2.50 | 256K | Standard | Cheaper output than K2.5 |
| kimi-k2-0711-preview | $0.60 | $0.15 | $2.50 | 131K | Standard | Smaller context |
| kimi-k2-turbo-preview | $1.15 | $0.15 | $8.00 | 256K | 60-100 tok/s | Fast, expensive |
| kimi-k2-thinking | $0.60 | $0.15 | $2.50 | 256K | Standard | Explicit thinking model |
| kimi-k2-thinking-turbo | $1.15 | $0.15 | $8.00 | 256K | 60-100 tok/s | Fast thinking |

### Moonshot V1 (Zero's "cheap" models)
| Model | Input (official) | Output (official) | Input (codebase) | Output (codebase) |
|-------|-----------------|-------------------|-------------------|-------------------|
| v1-8k | **$0.20** | **$2.00** | $0.012 | $0.012 |
| v1-32k | **$1.00** | **$3.00** | $0.024 | $0.024 |
| v1-128k | **$2.00** | **$5.00** | $0.06 | $0.06 |

### MiniMax (Zero's content polish model)
| Model | Input | Output | Context | Notes |
|-------|-------|--------|---------|-------|
| MiniMax-M2.7 | $0.30 | $1.20 | 200K | Current, reasoning capable |
| MiniMax-M2.5 | $0.30 | $1.20 | - | Same price as M2.7 |
| M2.7-highspeed | $0.60 | $2.40 | - | 2x cost, faster |
| M2.5-highspeed | $0.60 | $2.40 | - | 2x cost, faster |

---

## 2. CRITICAL FINDINGS

### Finding 1: V1 Pricing is Catastrophically Wrong in the Codebase

The hardcoded prices in [kimi_provider.py:23-28](backend/app/infrastructure/llm_providers/kimi_provider.py#L23-L28) are **41-83x lower** than official rates:

| Model | Codebase says | Kimi docs say | Ratio |
|-------|-------------|---------------|-------|
| v1-8k input | $0.012 | $0.20 | **17x off** |
| v1-8k output | $0.012 | $2.00 | **167x off** |
| v1-32k input | $0.024 | $1.00 | **42x off** |
| v1-32k output | $0.024 | $3.00 | **125x off** |

**Impact**: The router thinks V1 models are cheap, so it routes high-volume tasks there (2,880 prompt grading calls/day on v1-32k, 288 email classifications/day on v1-8k). But if official pricing is correct, V1-32k ($1.00 input, $3.00 output) is **more expensive** than K2.5 ($0.60 input, $3.00 output). The budget tracker is reporting ~$0.50/day when actual spend could be $15-30+/day.

**Note**: This may be a CNY vs USD issue, or the V1 prices may have changed since the codebase was written. Either way, this needs immediate verification by checking the actual API billing dashboard.

### Finding 2: K2.5 Thinking is Silently Enabled

The Kimi API **enables thinking by default** on K2.5. Zero's kimi_provider.py only sends `"thinking": {"type": "enabled"}` when `thinking_mode=True`, but it **never sends `{"type": "disabled"}`** when thinking_mode is False. Since the API default is enabled, every K2.5 call generates (and bills) thinking tokens as output tokens.

This means Zero is paying for extended reasoning on every K2.5 call - prompt grading, extraction, classification - even when thinking adds no value. These thinking tokens inflate the output token count and cost.

**Location**: [kimi_provider.py:85-87](backend/app/infrastructure/llm_providers/kimi_provider.py#L85-L87)

### Finding 3: K2 Models are Cheaper Than K2.5 for Output

K2 models ($2.50/1M output) are 17% cheaper than K2.5 ($3.00/1M output) with the same input pricing. K2-thinking is a dedicated reasoning model at the K2 output price. Zero doesn't use any K2 models.

### Finding 4: MiniMax M2.7 is the Best Value for Non-Reasoning Tasks

At $0.30 input / $1.20 output, MiniMax M2.7 is:
- 2x cheaper than K2.5 on input
- 2.5x cheaper than K2.5 on output
- Cheaper than K2 on output ($1.20 vs $2.50)
- Has reasoning capability (reasoning_content support already in the provider)
- 200K context window

Zero only uses it for character content escalation. It should be used much more broadly.

---

## 3. Recommended Model Strategy

### Tier 1: Free (Ollama) - Keep as-is
**qwen3.6:35b-a3b-q8_0** for coding, workflow, simple tasks. No changes needed.

### Tier 2: Cheap Paid ($0.30-1.20/1M) - Switch V1 to MiniMax
**Replace all moonshot-v1 usage with MiniMax M2.7.** V1 models are either overpriced (official rates) or deprecated. MiniMax M2.7 at $0.30/$1.20 is genuinely cheap and capable.

| Task Type | Current | Proposed | Savings |
|-----------|---------|----------|---------|
| classification | v1-8k ($0.20/$2.00?) | MiniMax-M2.7 ($0.30/$1.20) | 40% on output |
| summarization | v1-32k ($1.00/$3.00?) | MiniMax-M2.7 ($0.30/$1.20) | 70% input, 60% output |
| analysis | v1-32k ($1.00/$3.00?) | MiniMax-M2.7 ($0.30/$1.20) | 70% input, 60% output |
| chat | v1-32k ($1.00/$3.00?) | MiniMax-M2.7 ($0.30/$1.20) | 70% input, 60% output |
| prompt_grading | v1-32k ($1.00/$3.00?) | MiniMax-M2.7 ($0.30/$1.20) | 70% input, 60% output |

### Tier 3: Reasoning ($0.60-2.50/1M) - Use K2-thinking
**Replace K2.5 with kimi-k2-0905-preview or kimi-k2-thinking** for tasks that need reasoning. 17% cheaper output ($2.50 vs $3.00) with the same input cost.

| Task Type | Current | Proposed | Why |
|-----------|---------|----------|-----|
| planning | K2.5 ($0.60/$3.00) | K2-thinking ($0.60/$2.50) | Explicit thinking, cheaper |
| extraction | K2.5 ($0.60/$3.00) | K2-0905 ($0.60/$2.50) | No thinking needed, cheaper |
| structured_output | K2.5 ($0.60/$3.00) | K2-0905 ($0.60/$2.50) | No thinking needed |
| research | K2.5 ($0.60/$3.00) | K2-thinking ($0.60/$2.50) | Thinking useful here |
| agent_ceo | K2.5 ($0.60/$3.00) | K2-thinking ($0.60/$2.50) | Agent planning benefits from thinking |
| council_ceo | K2.5 ($0.60/$3.00) | K2-thinking ($0.60/$2.50) | Debate needs reasoning |

### Tier 4: Batch (async, 40% off) - K2.5 batch for content gen
**Use K2.5 batch API** for latency-tolerant K2.5 workloads (character content, idea validation, TikTok research). Only worthwhile for tasks that currently use K2.5 and don't need real-time results.

---

## 4. Thinking Model Strategy

### When to use thinking
- **Planning and research** - model should reason about approach
- **Council debates** - agents need to weigh arguments
- **Complex extraction** - multi-step reasoning over long documents
- **Agent CEO decisions** - strategic planning

### When to DISABLE thinking
- **Classification** - binary/categorical, no reasoning needed
- **Summarization** - straightforward compression
- **Prompt grading** - scoring rubric is mechanical
- **Structured output** - format conversion, not reasoning
- **Chat** - conversational, no deep reasoning

### Implementation
Add `"thinking": {"type": "disabled"}` explicitly to the K2.5 payload when thinking_mode is False. This stops the API from generating (and billing) unwanted thinking tokens.

---

## 5. Implementation Plan

### Phase 1: Fix Critical Issues (immediate)
1. **Verify actual V1 pricing** - Check Moonshot billing dashboard to confirm what you're actually being charged
2. **Disable K2.5 thinking by default** - Add `"thinking": {"type": "disabled"}` to kimi_provider.py when thinking_mode is False
3. **Update hardcoded pricing** in kimi_provider.py to match official rates

### Phase 2: Model Rotation (replace V1 with MiniMax)
4. **Add K2 models to kimi_provider.py** - Add pricing for kimi-k2-0905-preview and kimi-k2-thinking
5. **Route cheap tasks to MiniMax** - Update router config for classification, summarization, analysis, chat, prompt_grading to use MiniMax-M2.7
6. **Route reasoning tasks to K2-thinking** - Update planning, research, agent_ceo, council roles to K2-thinking
7. **Route non-reasoning paid tasks to K2-0905** - Update extraction, structured_output to K2-0905
8. **Keep K2.5 only for batch** - Reserve K2.5 for batch API workloads where 40% discount applies
9. **Increase MiniMax daily cap** - Raise from $2.00 to $3.50 to accommodate broader usage

### Phase 3: Batch API (for K2.5 tasks that remain)
10. **Implement batch provider** for character content generation and idea validation
11. **Add batch polling scheduler job**

### Phase 4: Context Caching Optimization
12. **Verify cache hit rates** - Add cache hit/miss logging to track automatic caching
13. **Restructure prompts** for cache friendliness - put static system prompts first, variable content last

### Files to Modify
- [kimi_provider.py](backend/app/infrastructure/llm_providers/kimi_provider.py) - Fix pricing, add thinking disable, add K2 models
- [llm.py](backend/app/models/llm.py) - Update task type routing (V1 -> MiniMax, K2.5 -> K2)
- [minimax_provider.py](backend/app/infrastructure/llm_providers/minimax_provider.py) - Add M2.5 model if needed
- [config.py](backend/app/infrastructure/config.py) - Increase MiniMax daily cap
- [unified_llm_client.py](backend/app/infrastructure/unified_llm_client.py) - Pass thinking disable through

### Estimated Impact
| Change | Daily Savings | Effort |
|--------|-------------|--------|
| Disable K2.5 thinking | $0.50-1.50 (output tokens) | 5 min |
| Fix V1 pricing tracking | $0 (visibility only) | 10 min |
| V1 -> MiniMax rotation | $1-3/day (if V1 is really expensive) | 30 min |
| K2.5 -> K2 for reasoning | $0.20-0.40/day | 15 min |
| Batch for content gen | $0.40-0.75/day | 2-3 hours |

---

## 6. Verification Plan
1. Check Moonshot billing dashboard for actual V1 charges
2. Query `llm_usage` table: `SELECT provider, model, SUM(cost_usd), COUNT(*) FROM llm_usage WHERE created_at > now() - interval '7 days' GROUP BY provider, model ORDER BY SUM(cost_usd) DESC`
3. After changes: compare daily spend for 3 days before/after
4. Monitor MiniMax quality on prompt grading (compare grade distributions)
5. Check K2-thinking output quality on planning tasks vs K2.5
