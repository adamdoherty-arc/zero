# LLM Routing Layer — Research & Recommendation (April 2026)

**Context:** Self-hosted control plane, LiteLLM proxy already in place (aliasing, fallbacks, budget). Need a smarter router for: local (vLLM, Ollama) vs cloud (Anthropic, Gemini, Moonshot Kimi, MiniMax, OpenRouter), with privacy gating, latency/cost ceilings, and eval-trained decisions over time.

---

## 1. Not Diamond
- **One-line:** Hosted "meta-model" that learns per-query which of N LLMs answers best; you call their SDK and it returns the chosen model + (optionally) the completion.
- **Status (Apr 2026):** Active but small (24 employees, $2.3M seed, no acquisition). Recent product is "Prompt Adaptation" (May 2025). **`notdiamond.toolkit.litellm` integration module is deprecated** — you'd run the SDKs side-by-side rather than as a clean LiteLLM plugin.
- **Real value-add:** Pre-trained pairwise preference router across frontier models, plus a custom-router training endpoint where you upload a labelled eval set and they fit a small classifier. The training story is the moat — without your own preference data it's just a generic OpenAI-vs-Claude-vs-Gemini picker.
- **Fit for this stack:** Mediocre. Doesn't natively know about local vLLM/Ollama models or Moonshot/MiniMax (custom routers can be trained on arbitrary endpoints, but you have to build the eval harness). Hosted call adds a network hop on every request — bad for sub-second budgets.
- **Recommendation:** Skip for now. Revisit only if you build a labelled preference dataset large enough (~5–10k pairs) to train a custom router that beats heuristics.

## 2. RouteLLM (LMSYS)
- **One-line:** Open-source, classifier-based router that picks "strong model vs weak model" per query, optimising cost at fixed quality.
- **Status:** Last meaningful update Aug 2024. **Effectively unmaintained** — LMSYS focus shifted to Chatbot Arena. Pre-trained routers (mf, bert, causal-llm, sw-ranking) still work and generalise to arbitrary model pairs.
- **Real value-add:** Solid binary "escalate or not" decision. Up to ~85% cost reduction at ~95% GPT-4 quality on MT-Bench in their paper.
- **Fit:** Inherently 2-model. You have a constellation (local cheap, local big, Claude, Gemini, Kimi, MiniMax). Wrapping it as a cascade (Qwen-local → Sonnet → Opus) is feasible but you're stacking decisions a more modern semantic router does in one pass.
- **Recommendation:** Use as a *local-vs-cloud* binary gate only if vLLM Semantic Router proves too heavy. Don't build a multi-tier system on it.

## 3. LiteLLM built-in router
- **One-line:** The router you already have can do load-balancing, latency-based, cost-based, usage-based routing, custom callbacks, and (since v1.74.9) semantic auto-routing via embeddings.
- **Status:** Very active (April 2026 releases, credential overrides per team, adaptive router in beta).
- **Capabilities relevant here:**
  - `router_settings.routing_strategy`: `latency-based-routing`, `cost-based-routing`, `usage-based-routing-v2`.
  - **Auto Router** (v1.74.9+): YAML-defined utterances → embed input → cosine-match → pick model. Runs in-process, ~one extra embedding call.
  - **Adaptive Router** (beta): tracks per-task-class win rate and re-weights routing decisions over time — closest native equivalent to Not Diamond's value prop, no second vendor.
  - **Presidio guardrail** built in for PII masking/blocking.
  - Custom `pre_call_hook` callbacks let you inject arbitrary Python (regex, classifier call, vault tags) before model selection.
- **Fit:** Excellent. You already operate it. Most of what people reach for a separate router for is now first-class.
- **Recommendation:** **Use this as the primary routing layer.** Combine Auto Router for task-class routing + Adaptive Router for online learning + a custom pre_call_hook for privacy gating.

## 4. LangChain / LangGraph routing
- **One-line:** General agent-orchestration framework; routing is one node in a graph.
- **Status:** Active, dominant in the agent-orchestration space.
- **Trade-off:** Reported overhead is real — 15–18s vs 7–9s direct on equivalent workloads in user reports. Graph supervisor adds an extra LLM call per hop. Fine for multi-step agent workflows; **wrong tool for "decide model in <50ms then forward request."**
- **Fit:** Use *upstream* of LiteLLM if you're already running an agent graph (LangGraph supervisor decides which sub-agent runs, sub-agent calls LiteLLM proxy). Do **not** put a LangGraph node inline as a per-token router.
- **Recommendation:** Don't introduce LangGraph for the routing decision itself. If/when you add multi-step agents, LangGraph belongs above the gateway, not inside it.

## 5. Semantic classifier (small local LLM as router)
- **One-line:** Small model (BERT-class, or Qwen3-4B) classifies intent/sensitivity → routing layer maps class → model.
- **Best-in-class implementation:** **vLLM Semantic Router** (`vllm-project/semantic-router`), reached Athena v0.2 release in March 2026 (Red Hat-backed). Uses ModernBERT + LoRA classifiers on 14 MMLU domains, plus jailbreak/PII/fact-check classifiers. Ships intent-aware routing, prompt compression, "98× faster routing without a dedicated GPU" with flash-attention/near-streaming optimisations (recent arxiv).
- **Latency:** ModernBERT classifier ~5–20ms on CPU; Qwen3-4B classifier 50–150ms on a small GPU. Acceptable for chat, marginal for streaming-first workloads.
- **Accuracy:** With a handful of labelled examples per intent, BERT-class hits 90%+. Qwen3-4B with few-shot is more flexible but slower.
- **Fit:** Excellent — it's purpose-built for exactly your topology (multiple local backends + cloud), and its classifier set already includes PII detection, which feeds your privacy gate.
- **Recommendation:** **Run vLLM Semantic Router in front of LiteLLM proxy.** Router picks the *model class* (local-small / local-big / cloud-frontier / cloud-cheap); LiteLLM does the actual call, fallback, budget tracking. Clean separation.

## 6. OpenRouter as fallback
- **One-line:** Unified marketplace for ~290 models behind one key, with auto-fallback across providers.
- **Status:** Active, scaling. **Pricing nuance:** they don't mark up *inference*, but charge 5.5% on credit purchases and 5% BYOK fee. Specific models (notably Claude variants) have shown effective markup vs direct Anthropic — if Claude > 20% of spend, go direct.
- **Fit:** Useful as a *spillover* lane in LiteLLM — define openrouter as a fallback for cloud models you don't want a direct contract with (Kimi, MiniMax already work direct; OpenRouter shines for niche/long-tail).
- **Recommendation:** Keep direct keys for Anthropic/Gemini/Moonshot/MiniMax. Wire OpenRouter as the *third fallback* in LiteLLM `fallbacks:` for breadth, not as primary.

## 7. Newer 2026 entrants
- **Portkey** — Edge-worker AI gateway, 250+ models, 20–40ms overhead, strong governance/PII/guardrails story. Direct competitor to LiteLLM Proxy + Presidio combo. **Fit:** alternative to LiteLLM, not a complement. Skip if LiteLLM is meeting needs.
- **Helicone** — Rust proxy with caching, routing, observability bundled. Lighter than Portkey. Can pair with a dedicated router. **Fit:** consider for observability slot (see §9), not as router.
- **Martian** — YC-backed; classifies prompts with small local models then routes. Closed-source, hosted. Pitches itself as Not-Diamond-but-cheaper-config. **Fit:** redundant with vLLM Semantic Router if you're willing to self-host.
- **Bifrost** (maximhq) — Go-written gateway, ~11µs overhead at 5k RPS, supports vLLM + Ollama natively, claims 50× faster than LiteLLM. **Fit:** if LiteLLM proxy ever becomes your latency bottleneck, swap *it* for Bifrost; routing layer above stays the same.
- **NVIDIA NIM router** — primarily about routing across NIM-containerised inference endpoints in NVIDIA's stack; not a general-purpose router. Skip unless you're standardising on NIM.
- **Cloudflare AI Gateway** — basic load balancing only, no semantic routing. Skip.

## 8. Privacy gating (vault/PII/trading-data MUST stay local)
**Best pattern: defence in depth, enforced at the proxy layer, never trust the caller.**

1. **Tag at source.** Caller sets a header/metadata field `data_class: vault|pii|trading|public`. Used as a fast-path hint, not a security boundary.
2. **Detect at gateway.** Run Presidio (built into LiteLLM as `presidio` guardrail) and the vLLM Semantic Router PII classifier in parallel on request body. Either firing → mark as sensitive.
3. **Enforce at router.** Custom LiteLLM `pre_call_hook` (or vLLM Semantic Router policy): if `sensitive==true`, restrict candidate model set to `local_only` (vLLM + Ollama models). Hard fail on cloud selection — don't fall back, return an error.
4. **Audit every decision.** Log `{request_hash, classification, candidate_models, chosen_model, sensitivity_reason}` to Langfuse. Enables post-hoc detection of bypass.
5. **Egress firewall as backstop.** Network policy on the proxy host that blocks outbound calls to api.anthropic.com / generativelanguage.googleapis.com / openrouter.ai when the request originates from a "vault" workload namespace. Belt-and-braces — caught one bug too many in production to skip.

## 9. Observability for routed traffic
- **Langfuse** — Best general fit. Self-hostable (free for core), session/trace replay, eval templates, integrates with LiteLLM via single `success_callback: ["langfuse"]` line. Captures routing decisions if you log them as span attributes.
- **Phoenix (Arize)** — Strongest for eval/drift over time and RAG quality plots. Free self-host (ELv2). Heavier setup; built for ML teams that already have Arize. Use *alongside* Langfuse for periodic eval, not as the always-on tracer.
- **Helicone** — Proxy-based, simplest setup, but it's an HTTP-level view — no span/agent tracing. Less useful once you have multi-step agents.

**Recommendation:** Langfuse self-hosted as the spine; add Phoenix later for offline drift analysis. Helicone only if you abandon LiteLLM.

---

## Final Recommendation

Given LiteLLM is already the backbone, the cleanest 2026 stack is:

```
client → [vLLM Semantic Router]  → [LiteLLM Proxy]  → {vLLM, Ollama, Anthropic, Gemini, Kimi, MiniMax, OpenRouter}
              (intent + PII)          (alias, fallback,
                                       budget, guardrails,
                                       presidio, adaptive)
                                                     ↓
                                            [Langfuse self-hosted]
```

**Concretely:**

1. **Routing brain:** vLLM Semantic Router (Athena release) in front. Classifies intent (code / chat / analysis / vision / agent-tool-call) AND sensitivity (PII/jailbreak/fact). Outputs a **model-class label**, not a specific model.
2. **Execution layer:** Keep LiteLLM proxy. Map model-class → concrete model via LiteLLM `model_group` aliases. Use `latency-based-routing` within a class. Enable the **Adaptive Router (beta)** to learn per-class winners over time — this is your built-in "Not Diamond replacement."
3. **Privacy gate:** Two-stage. Semantic Router PII classifier + LiteLLM Presidio guardrail. Sensitive → forced `model_group: local_only`. Network egress firewall as backstop.
4. **Eval-trained decisions over time:** Log every routing decision + downstream user feedback (thumbs/regen/edit) to Langfuse. Quarterly: export, label preference pairs, retrain Semantic Router classifier head (LoRA fine-tune of ModernBERT — cheap on a single GPU). This gives you the "trained on our data" property without the Not Diamond dependency.
5. **Skip:** Not Diamond, RouteLLM (as primary), LangGraph-for-routing, Martian, Portkey, NIM router. Treat OpenRouter as a fallback lane, not a primary path.
6. **Watch list:** Bifrost — if LiteLLM proxy ever hits a latency wall, it's a drop-in replacement that keeps the rest of the architecture intact.

This combination is fully self-hosted, gives you a single trained-on-your-data brain, enforces privacy at two layers + network, and adds exactly one new component to what you already operate.

---

## Sources
- [LiteLLM Auto Routing docs](https://docs.litellm.ai/docs/proxy/auto_routing)
- [LiteLLM Adaptive Router (beta)](https://docs.litellm.ai/docs/adaptive_router)
- [LiteLLM v1.74.9 release notes (Auto-Router)](https://docs.litellm.ai/release_notes/v1-74-9)
- [LiteLLM Router / Load Balancing](https://docs.litellm.ai/docs/routing)
- [LiteLLM Presidio PII guardrail](https://docs.litellm.ai/docs/proxy/guardrails/pii_masking_v2)
- [vLLM Semantic Router GitHub](https://github.com/vllm-project/semantic-router)
- [vLLM Semantic Router blog (Sept 2025)](https://blog.vllm.ai/2025/09/11/semantic-router.html)
- [Athena v0.2 release — Red Hat Developer (Mar 2026)](https://developers.redhat.com/articles/2026/03/25/getting-started-vllm-semantic-router-athena-release)
- [98× Faster LLM Routing arxiv](https://arxiv.org/html/2603.12646)
- [Not Diamond — about](https://www.notdiamond.ai/about)
- [Not Diamond PyPI (`notdiamond` 0.3.43)](https://pypi.org/project/notdiamond/0.3.43/)
- [Not Diamond — PitchBook profile (2026)](https://pitchbook.com/profiles/company/541423-36)
- [RouteLLM GitHub](https://github.com/lm-sys/RouteLLM)
- [RouteLLM original blog (LMSYS)](https://www.lmsys.org/blog/2024-07-01-routellm/)
- [LangGraph latency overhead issue #3515](https://github.com/langchain-ai/langgraph/issues/3515)
- [LangGraph supervisor vs swarm tradeoffs](https://dev.to/focused_dot_io/multi-agent-orchestration-in-langgraph-supervisor-vs-swarm-tradeoffs-and-architecture-1b7e)
- [OpenRouter pricing breakdown 2026 (Brainroad)](https://brainroad.com/openrouter-pricing-explained-the-complete-2026-breakdown/)
- [OpenRouter pricing — CostGoat (Apr 2026)](https://costgoat.com/pricing/openrouter)
- [Portkey vs LiteLLM vs OpenRouter (PkgPulse 2026)](https://www.pkgpulse.com/guides/portkey-vs-litellm-vs-openrouter-llm-gateway-2026)
- [Top 5 LLM Gateways 2026 (DEV)](https://dev.to/varshithvhegde/top-5-llm-gateways-in-2026-a-deep-dive-comparison-for-production-teams-34d2)
- [Best AI Model Routers 2026 (Artifilog)](https://www.artifilog.com/posts/best-ai-model-routers)
- [Bifrost AI Gateway GitHub](https://github.com/maximhq/bifrost)
- [Microsoft Presidio GitHub](https://github.com/microsoft/presidio)
- [MLflow gateway guardrails post](https://mlflow.org/blog/gateway-guardrails)
- [LLM observability comparison 2026 (Firecrawl)](https://www.firecrawl.dev/blog/best-llm-observability-tools)
- [Langfuse vs alternatives 2026 (Braintrust)](https://www.braintrust.dev/articles/langfuse-alternatives-2026)
- [Phoenix/Langfuse/Helicone hands-on review (DEV)](https://dev.to/soufian_azzaoui_85ea1c030/i-tried-langsmith-langfuse-helicone-and-phoenix-heres-what-each-gets-wrong-2cjk)
