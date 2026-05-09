---
owner: company
status: strategy-reference
source_of_truth: strategy
last_verified: 2026-05-02
verified_against:
  - C:\code\company\docs\10-constitution\MASTER_PLAN.md
  - C:\code\company\docs\40-operations\LIVING_STATE.md
drift_policy: preserve as research context; do not treat runtime facts as current without LIVING_STATE
---

# The Agentic OS Playbook for Adam: Building a Hybrid Local/Cloud Personal AI Orchestrator on Windows 11 + RTX 5090 (April 2026)

> Operational note: this is a strategy reference. Current runtime facts live in
> [`LIVING_STATE.md`](LIVING_STATE.md), and policy lives in
> [`MANDATE.md`](MANDATE.md).

## Executive Summary

You're trying to do something that the field has only recently made possible: stitch together a **personal agentic operating system** that bridges your work (Eightfold AI / Workday-Oracle-SuccessFactors deliverables), your software development life (Magnus, AVA, Fortress of Solitude, Legion), and your personal life (Obsidian, Reachy Mini, Sought Supply, errands). As of April 2026, the pieces to do this exist — but no single vendor sells a complete kit. You will have to compose one.

The good news: the standards you need have stabilized. **MCP (Model Context Protocol)** is now the de facto "USB-C for AI" with thousands of servers and managed offerings from Google, Anthropic, OpenAI, and Microsoft ([modelcontextprotocol.io](https://modelcontextprotocol.io/docs/getting-started/intro), [The New Stack](https://thenewstack.io/google-launches-managed-remote-mcp-servers-for-its-cloud-services/)). **LangGraph 1.0**, **Microsoft Agent Framework 1.0** (which absorbed AutoGen + Semantic Kernel), **Pydantic AI**, and **Microsoft UFO³** all hit production-grade releases between Feb–Apr 2026 ([Microsoft DevBlogs](https://devblogs.microsoft.com/foundry/microsoft-agent-framework-reaches-release-candidate/), [Visual Studio Magazine](https://visualstudiomagazine.com/articles/2026/04/06/microsoft-ships-production-ready-agent-framework-1-0-for-net-and-python.aspx), [microsoft.github.io/UFO](https://microsoft.github.io/UFO/)). **Claude Computer Use** is now in research preview on Windows desktops via the CLI and Cowork app, and **OpenAI's ChatGPT Agent** has consolidated Operator + Deep Research into a single agentic mode ([Claude Code Docs](https://code.claude.com/docs/en/whats-new), [OpenAI](https://openai.com/index/introducing-chatgpt-agent/)). Your RTX 5090 is finally well-supported by vLLM, llama.cpp, and TensorRT-LLM with FP4/FP8 native kernels ([Spheron](https://www.spheron.network/blog/fp4-quantization-blackwell-gpu-cost/), [vLLM Forums](https://discuss.vllm.ai/t/vllm-on-rtx5090-working-gpu-setup-with-torch-2-9-0-cu128/1492)).

The bad news: this is also when **prompt injection moved from theoretical to operational** — the OpenClaw incident, ServiceNow second-order injection, and ~1,000 publicly exposed unauthenticated MCP servers all hit in early 2026 ([Capitol Tech](https://www.captechu.edu/blog/how-ai-gaining-easy-access-unsecured-servers-through-model-context-protocol-ecosystem), [Sombra](https://sombrainc.com/blog/llm-security-risks-2026), [Data Science Dojo](https://datasciencedojo.com/blog/prompt-injection-explained/)). Anything you build that has computer-use access to your trading account, brokerage, or credentials needs serious sandboxing.

**Bottom line recommendation:** Do not try to fix Legion first. Adopt **LangGraph 1.0 + Pydantic AI + MCP** as your core orchestration layer; use **Microsoft UFO³ / Claude Computer Use / ChatGPT Agent** for desktop control rather than building it; route LLM calls through **LiteLLM** with **Not Diamond** (or a simple semantic classifier) deciding local vs cloud; expose Magnus, Obsidian, and Legion as MCP servers; and use **Letta or Mem0 + pgvector** for long-term memory. Then port Legion's logic into LangGraph as your second project once the architecture is validated.

---

## 1. The State of Agentic Operating Systems in April 2026

### What "Agentic OS" Actually Means Now

Three distinct meanings of "agentic OS" coexist in 2026, and they are often conflated:

1. **AIOS-style kernels** that treat LLMs as schedulable processes — exemplified by the open-source [AIOS project from agiresearch](https://github.com/agiresearch/AIOS), which has been accepted at COLM 2025 and provides a kernel with LLM Core, Context Manager, Memory Manager, Tool Manager (with VM Controller and MCP Server), plus an SDK called Cerebrum ([AIOS GitHub](https://github.com/agiresearch/AIOS)).
2. **Desktop AgentOS** — Microsoft's UFO² (April 2025) and UFO³ Galaxy (Nov 2025) frame the OS itself as a multi-agent runtime, with a HostAgent for orchestration and per-application AppAgents using Windows UI Automation, Win32, and WinCOM APIs combined with vision-based parsing via OmniParser ([UFO³ docs](https://microsoft.github.io/UFO/), [arXiv 2504.14603](https://arxiv.org/html/2504.14603v1)). UFO² achieved >10% better success rate than prior CUAs on Windows tasks across 20+ applications.
3. **Enterprise/vertical agentic OS** — VAST AgentEngine (data infrastructure), PubMatic AgenticOS (advertising), Amdocs aOS (telco), and [Markovate's framing](https://markovate.com/agentic-operating-system/) of agentic OS as the cross-system orchestration layer for enterprise. Gartner predicts 40% of enterprise apps will feature task-specific AI agents by 2026 ([Markovate](https://markovate.com/agentic-operating-system/)).

For your purposes, you are building **Definition #2 + Definition #3 at the personal scale**: a desktop-rooted, Windows-native, multi-agent runtime that also orchestrates your projects (which are themselves systems, not just apps).

The recurring architectural pattern is the **Hierarchical Supervisor Pattern**: one capable planner model decomposes intent into a DAG, then dispatches work to specialized executors, with MCP as the universal tool adapter ([Medium / Dobhal](https://medium.com/@abhinav.dobhal/the-rise-of-agentic-operating-systems-0de233dbc1e9), [Towards Data Science](https://towardsdatascience.com/the-multi-agent-trap/)). Klarna's production deployment is the canonical example: a frontier model plans, cheaper models execute, cutting costs by ~90% versus running the frontier model end-to-end ([Towards Data Science](https://towardsdatascience.com/the-multi-agent-trap/)).

### Personal AI Assistant Lessons (What Failed and Why)

The 2024–2025 hardware-led personal AI experiments all over-promised:

- **Rabbit R1 / Humane AI Pin**: Both shipped before the agentic substrate (computer use, MCP, durable agent runtimes) existed. They tried to invent their own tool ecosystems on locked-down hardware and failed. Lesson: **don't build your own hardware-bound agentic surface; ride the open standards (MCP, A2A) on hardware you already trust**.
- **Pi by Inflection**: Strong personality, weak agency. Microsoft acquihired the team in 2024 and Pi was effectively decommissioned. Lesson: conversational warmth without action is a chatbot, not an agent.
- **Anthropic Claude Computer Use** (Mac-first, March 2026 preview; Windows in CLI April 2026): Permission-first model that asks before touching new apps; works well with native API integrations (Calendar, Slack) and falls back to GUI control ([SiliconANGLE](https://siliconangle.com/2026/03/23/anthropics-claude-gets-computer-use-capabilities-preview/), [CNBC](https://www.cnbc.com/2026/03/24/anthropic-claude-ai-agent-use-computer-finish-tasks.html)).
- **OpenAI Operator → ChatGPT Agent** (July 2025 consolidation): Now a unified "agent mode" with virtual browser, terminal access, and connectors to Google Drive, etc. Set 68.9% on BrowseComp ([OpenAI](https://openai.com/index/introducing-chatgpt-agent/)).
- **Anthropic MCP Apps ecosystem**: Anthropic donated MCP to a Linux Foundation fund in late 2025 and the Cowork Marketplace centralizes plugins for legal, financial, engineering, HR ([Wikipedia: Claude](https://en.wikipedia.org/wiki/Claude_(language_model)), [TechCrunch](https://techcrunch.com/2025/12/10/google-is-going-all-in-on-mcp-servers-agent-ready-by-design/)).

### MCP: The "USB-C for AI" Now Has Real Production Stress

MCP went from novelty (Nov 2024) to default (April 2026):

- The official intro positions it explicitly as a USB-C analog — one protocol, many tools and clients ([modelcontextprotocol.io](https://modelcontextprotocol.io/docs/getting-started/intro)).
- **Ecosystem scale (April 2026)**: TypeScript SDK has 34,700+ dependent npm projects; thousands of servers; OpenAI Agents SDK v0.12.x, Microsoft Agent Framework 1.0, Pydantic AI, LangGraph, CrewAI, and Google ADK 2.0 all support MCP natively ([Context Studios](https://www.contextstudios.ai/blog/mcp-ecosystem-in-2026-what-the-v127-release-actually-tells-us), [Microsoft Learn](https://learn.microsoft.com/en-us/agent-framework/overview/)).
- **Google launched managed remote MCP servers** for BigQuery, Maps, Compute Engine, and GKE in December 2025 — the same servers work with Claude, ChatGPT, and Gemini CLI as clients ([TechCrunch](https://techcrunch.com/2025/12/10/google-is-going-all-in-on-mcp-servers-agent-ready-by-design/), [The New Stack](https://thenewstack.io/google-launches-managed-remote-mcp-servers-for-its-cloud-services/)).
- **The 2026 MCP roadmap** focuses on enterprise readiness — audit trails, OAuth/identity binding, signed manifests, and SEP working-group governance because the bottleneck shifted from feature velocity to production trust ([The New Stack](https://thenewstack.io/model-context-protocol-roadmap-2026/), [Red Hat Developer](https://developers.redhat.com/articles/2026/01/08/building-effective-ai-agents-mcp)).
- **Security warning**: ~1,000 publicly exposed MCP servers were found with no authorization controls in early 2026 — a Bitsight report flagged that MCP adoption is outpacing security practices ([Capitol Tech](https://www.captechu.edu/blog/how-ai-gaining-easy-access-unsecured-servers-through-model-context-protocol-ecosystem)).

### Framework Comparison (Multi-Agent Orchestration)

| Framework | Model | Strengths | Weaknesses | When to pick |
|---|---|---|---|---|
| **LangGraph 1.0** | Directed graph, shared state, durable execution | Production-grade checkpointing, time-travel debug, deepest MCP integration as graph nodes, native streaming ([LangChain](https://blog.langchain.com/how-and-when-to-build-multi-agent-systems/)) | Steepest learning curve | Mission-critical, stateful workflows, anything with retries/HITL |
| **Microsoft Agent Framework 1.0** (Apr 7 2026) | Graph workflows, ChatAgent, MCP+A2A native | Successor to AutoGen+Semantic Kernel; .NET + Python; OpenTelemetry observability built-in; Foundry integration ([VS Magazine](https://visualstudiomagazine.com/articles/2026/04/06/microsoft-ships-production-ready-agent-framework-1-0-for-net-and-python.aspx)) | Newer; Azure-leaning ecosystem | If you're already in MS shop or want Foundry observability |
| **CrewAI** | Role-based crews, sequential/hierarchical | Lowest barrier, readable agent definitions, A2A support added | No built-in checkpointing, coarse error handling; teams routinely migrate to LangGraph ([gurusup](https://gurusup.com/blog/best-multi-agent-frameworks-2026)) | Quick prototypes, 3–5 agent role pipelines |
| **AutoGen 0.4** | Conversational GroupChat | Now in **maintenance mode** — bug fixes only, MS recommends migration to Agent Framework ([microsoft/autogen](https://github.com/microsoft/autogen)) | Token-heavy: 4 agents × 5 rounds = 20+ LLM calls | Don't start new projects here in 2026 |
| **Pydantic AI** (v1.85.x, Apr 2026) | Type-safe agent functions, model-agnostic | "FastAPI feeling" for agents; structured outputs, durable execution, MCP+A2A+AG-UI; excellent Logfire observability ([pydantic.dev](https://pydantic.dev/pydantic-ai), [GitHub](https://github.com/pydantic/pydantic-ai)) | Less mature multi-agent orchestration than LangGraph | Teams that already love Pydantic; structured-output workflows; pair with LangGraph for complex state |
| **smolagents** | Code Agents (LLM writes Python actions) | ~1,000 LOC core; sandboxed via E2B/Modal/Docker; 30% fewer steps than JSON tool-calling on agentic benchmarks ([HF blog](https://huggingface.co/blog/smolagents)) | Single-process; less production tooling | Your Reachy Mini, exploratory data work, anywhere code-as-action is natural |
| **OpenAgents** | Network paradigm, MCP+A2A native | Only framework with native MCP **and** A2A; persistent multi-agent networks ([openagents.org](https://openagents.org/blog/posts/2026-02-23-open-source-ai-agent-frameworks-compared)) | Smaller community | Long-lived heterogeneous agent ecosystems |
| **Pippin** (Yohei Nakajima) | "Digital being" loop with self-generating activities | Memory-evolving, BabyAGI lineage; great for autonomous personas | Less production observability; tied to the Pippin token cultural project ([GitHub](https://github.com/pippinlovesyou/pippin)) | Background "digital being" experiments only |

**Verdict for Adam**: **LangGraph 1.0 as the orchestration spine, Pydantic AI for individual typed agents, MCP for tools, smolagents for the Reachy Mini.** This is the stack that minimizes future migrations.

---

## 2. Smart LLM Routers and Cost Optimization

### The Router Landscape

The router space exploded in 2025–2026 because GPT-5 itself shipped routing as a built-in feature ([RouterArena paper, arXiv 2510.00202](https://arxiv.org/pdf/2510.00202)). The taxonomy that matters:

| Tool | Type | Notes |
|---|---|---|
| **LiteLLM** | Open-source Python SDK + proxy, 100+ providers | The de facto OSS unified API; Python-native, used in 13+ agent framework integrations ([Mem0](https://mem0.ai/blog/state-of-ai-agent-memory-2026)). Some Python GIL overhead at extreme concurrency. |
| **OpenRouter** | Hosted unified API, 300+ models from 60+ providers | Lowest setup; per-token markup; cache-aware stickiness ([Pinggy](https://pinggy.io/blog/best_ai_llm_routers_openrouter_alternatives/)). |
| **Bifrost (Maxim AI)** | Open-source Go gateway | 11μs gateway overhead at 5,000 RPS — orders of magnitude better than Python gateways ([getmaxim.ai](https://www.getmaxim.ai/articles/top-5-llm-router-solutions-in-2026/)). |
| **Portkey** | Hosted gateway, 250+ models | Strong policy/observability, semantic caching. |
| **Helicone** | Proxy-only observability layer | One-line integration; logs only, doesn't route ([inworld.ai](https://inworld.ai/resources/best-llm-router-ai-gateway)). |
| **Not Diamond** | Client-side AI router | Client-side, sub-token-time decisions; trains custom routers from your eval data ([sourceforge](https://sourceforge.net/software/llm-routers/)). |
| **RouteLLM** (LMSYS) | OSS framework with trained matrix-factorization, BERT, LLM-judge routers | Up to 85% cost reduction with 95% of GPT-4 quality on MT-Bench ([LMSYS blog](https://www.lmsys.org/blog/2024-07-01-routellm/)). |
| **Martian** | Commercial router | Live benchmark-driven selection. |
| **vLLM Semantic Router** | OSS in-process semantic classifier | Free; integrates directly into vLLM. |
| **GPT-5 native router** | OpenAI built-in | Reasoning effort + model selection rolled into the model call itself ([RouterArena](https://arxiv.org/pdf/2510.00202)). |

### What to Route On

A 2026 production routing strategy uses **layered decision-making**:

1. **Task-class classification** (cheap classifier or rule): code generation → Claude/Qwen-Coder; reasoning-heavy → DeepSeek-R1 / Opus 4.7 / GPT-5.4 xhigh; chit-chat → small local model; vision/screenshot parsing → OmniParser-V2 first, then GPT-4o or Claude.
2. **Sensitivity gating**: anything touching brokerage credentials, client PII, or NDA material → forced local route.
3. **Latency budget**: <500ms first-token requirement → local Qwen-3 or Llama-3.3 on the 5090; >5s OK → cloud reasoning model.
4. **Cost ceilings per agent/session**: enforce at gateway level (LiteLLM/Portkey both support).

### Recommended Adam-Stack Routing Architecture

```
[Agent / IDE / MCP Client]
          ↓
[LiteLLM Proxy + Not Diamond client-side fuzzy hash]
          ↓
   ┌──────────────┬─────────────────────────────────┐
   ↓              ↓                                  ↓
[Local: Ollama  [Cloud cheap:                    [Cloud frontier:
 + vLLM on 5090] Haiku $1/$5, GPT-5-mini,         Opus 4.7 $5/$25,
                 Gemini Flash]                     GPT-5.4 xhigh,
                                                   Sonnet 5 1M ctx]
```

Per [Anthropic's 2026 pricing](https://www.nxcode.io/resources/news/claude-ai-complete-guide-models-pricing-features-2026), Claude Sonnet 4.6 is $3/$15 per MTok with 79.6% SWE-bench / 72.7% OSWorld; Opus 4.7 is $5/$25 with 70% CursorBench; Haiku is $1/$5 — workhorse routing target. GPT-5.4 (xhigh) ties Opus 4.7 at 57 on Artificial Analysis Intelligence Index, and Kimi K2.6 leads open-weight at 54 ([Artificial Analysis](https://artificialanalysis.ai/models/comparisons/qwen3-32b-instruct-reasoning-vs-deepseek-r1-distill-llama-70b)).

### What Your RTX 5090 (32 GB GDDR7) Can Actually Run

The 5090 is, as of Q1 2026, the strongest single-card consumer LLM platform. Verified numbers:

- **Memory bandwidth**: 1,792 GB/s (GDDR7) — 78% more than the 4090, which directly translates to inference throughput because autoregressive decoding is bandwidth-bound ([Spheron](https://www.spheron.network/blog/rent-nvidia-rtx-5090/)).
- **Native FP4 (NVFP4) support** — Blackwell tensor cores deliver ~1,677 TOPS at INT8 with sparsity; FP4 roughly doubles FP16 throughput ([Spheron FP4 deep dive](https://www.spheron.network/blog/fp4-quantization-blackwell-gpu-cost/)).
- **Confirmed throughput on Qwen2.5-Coder-7B-Instruct**: 5,841 tok/s at 1024 tokens / batch 8 — outperforming an A100 80GB by 2.6× ([Runpod benchmarks](https://www.runpod.io/blog/rtx-5090-llm-benchmarks)).
- **Real-world model fits** (verified via llama.cpp Q4_K_XL):
  - Qwen-3-8B Q4: 10,400+ tok/s prompt processing
  - Qwen-3-32B dense Q4 at 32k context: 1,450+ tok/s prompt processing, ~50 tok/s gen, 18.6 GB VRAM
  - Qwen-3-30B MoE Q4 with 147k tokens of context: 31 GB VRAM, ~52 tok/s sustained — entire context in VRAM ([hardware-corner](https://www.hardware-corner.net/rtx-5090-llm-benchmarks/))
  - GPT-OSS 120B at 131k context: 1,600 tok/s prompt processing, 112 tok/s generation
  - Llama 3.3 70B Q4: requires aggressive quant; runs but tight on context. The Llama-3.3-70B NVFP4 checkpoint from `nvidia/` namespace is the recommended path ([Spheron FP4](https://www.spheron.network/blog/fp4-quantization-blackwell-gpu-cost/))
- **vs RTX 4090** on actual chat: Llama 70B 32k context — 9.4 vs 16.8 tok/s (~80% faster); Qwen 14B coding at 8k — meaningfully smoother sessions ([Vipin PG](https://vipinpg.com/blog/benchmarking-rtx-5090-vs-4090-for-local-llm-inference-real-world-tokensecond-gains-with-ollama-and-lm-studio/)).

### Local Inference Stack on Windows + RTX 5090

| Tool | Status on 5090 (Apr 2026) | Recommendation |
|---|---|---|
| **Ollama** | Fully supported, easiest setup | **Start here.** Daily-driver for one-off chat, Open WebUI integration. |
| **LM Studio** | Fully supported, GUI-driven | Good for model browsing, not production. |
| **llama.cpp** | Fully supported, Q4_K_XL is sweet spot | Use for very long context (>100k) experiments. |
| **vLLM** | Now working with PyTorch 2.9.0 + CUDA 12.8 + sm_120 — needed weeks of community work but it's solid as of late 2025 ([vLLM Forums](https://discuss.vllm.ai/t/vllm-on-rtx5090-working-gpu-setup-with-torch-2-9-0-cu128/1492), [issue 14452](https://github.com/vllm-project/vllm/issues/14452)) | **Production serving**. Use the BoltzmannEntropy/vLLM-5090 Docker container ([GitHub](https://github.com/BoltzmannEntropy/vLLM-5090)) for a one-command setup. |
| **TensorRT-LLM** | NVFP4 supported as of v0.20.0+ on Blackwell ([issue 5018](https://github.com/NVIDIA/TensorRT-LLM/issues/5018)) | Use for max throughput when you have a stable model pipeline ([discussion 8334](https://github.com/NVIDIA/TensorRT-LLM/discussions/8334)). |
| **ExLlamaV2** | Works | Good for niche EXL2 quants. |
| **Text Generation WebUI** | Works | Less actively maintained relative to Open WebUI in 2026. |

**Concrete daily models for the 5090**: Qwen-3-32B (dense, Q4) for general agent reasoning, Qwen-3-Coder-Next MoE for code, DeepSeek-R1-Distill-Llama-70B for reasoning at FP4/NVFP4 (Llama-3.3-70B-Instruct-NVFP4 is the right HF artifact), Llama 3.3 70B NVFP4 for general chat, plus a small fast model (Qwen 0.8B / Phi-3-mini) for routing-level classification.

---

## 3. Windows-Native Desktop Control: What's Actually Working

For your Windows 11 box specifically, the field has split into three approaches:

### A. Microsoft UFO³ / UFO² (Use This for Native Windows Apps)

UFO² is purpose-built for Windows desktop automation and is the most production-ready option for **native Office/Win32 apps**:

- **HostAgent + AppAgent two-tier architecture**, with Picture-in-Picture (PiP) virtual desktop so the agent doesn't lock you out while it works ([Microsoft Research](https://www.microsoft.com/en-us/research/publication/ufo2-the-desktop-agentos/), [arXiv](https://arxiv.org/html/2504.14603v1)).
- **Hybrid GUI–API action layer**: uses Windows UI Automation (UIA) tree first, falls back to OmniParser-V2 vision parsing — explains why M365 Office apps hit 51.9% success on OSWorld-W and LibreOffice underperforms (worse UIA support).
- **MCP integration** via template-driven device agents.
- **UFO³ Galaxy** (Nov 2025, [arXiv 2511.11332](https://microsoft.github.io/UFO/)) extends this to multi-device orchestration via the Agent Interaction Protocol — relevant when you eventually pair your desktop with the Reachy Mini.

### B. Claude Cowork / Claude Code with Computer Use (Use This for IDE + Agentic Coding)

- **Claude Cowork** GA on Windows desktop and web (Jan 2026 → expanded Feb 2026 with connectors for Google Drive, Gmail, DocuSign, FactSet) — sandboxed shell + selected folder access, multi-step file ops ([Wikipedia](https://en.wikipedia.org/wiki/Claude_(language_model))).
- **Claude Code 2.x** added native PowerShell tool for Windows (Week 13, March 2026), `/loop` scheduled background tasks, voice mode, and **computer use in the CLI** in research preview (Week 14, late March 2026) ([Claude Code Docs](https://code.claude.com/docs/en/whats-new)). The leaked source (Mar 31 2026, 512K LoC) revealed swarms, daemons, and 44 feature flags — much of the agentic substrate is already in there ([TrueFoundry](https://www.truefoundry.com/blog/claude-code-prompt-injection)).
- Models: Sonnet 4.6 hits 79.6% SWE-bench Verified and 72.7% on OSWorld (computer use); Opus 4.7 leads at $5/$25/MTok ([NxCode](https://www.nxcode.io/resources/news/claude-ai-complete-guide-models-pricing-features-2026)).

### C. ChatGPT Agent (Use This for Web/SaaS Workflows)

- **ChatGPT Agent** consolidated Operator + Deep Research in July 2025; available on the ChatGPT macOS/Windows desktop apps. Virtual browser + terminal + connectors. Set 68.9% on BrowseComp (+17pp over Deep Research) ([OpenAI](https://openai.com/index/introducing-chatgpt-agent/)).
- Watch-mode and per-action confirmations for sensitive sites are the safety mechanism.

### D. Open-Source Alternatives

| Tool | What it is | When to use |
|---|---|---|
| **OpenInterpreter** | Local Python REPL agent | Fast scripting; lacks computer-use depth (community asking for OmniParser V2 support — issue [#1594](https://github.com/OpenInterpreter/open-interpreter/issues/1594)) |
| **OmniParser V2** | Microsoft vision-only screen parser, 39.6 avg accuracy on ScreenSpot Pro, 60% latency improvement over V1, ~0.6s/frame on A100 ([Microsoft Research](https://www.microsoft.com/en-us/research/articles/omniparser-v2-turning-any-llm-into-a-computer-use-agent/)) | Drop-in to make any LLM a computer-use agent; ships with OmniTool dockerized Win11 VM |
| **Browser Use** (Python) | 50,000+ stars; full-browser agent loop | Autonomous research, multi-tab tasks ([nxcode](https://www.nxcode.io/resources/news/stagehand-vs-browser-use-vs-playwright-ai-browser-automation-2026)) |
| **Stagehand v3** | Browserbase's TypeScript framework, CDP-native (March 2026 graduated from Playwright dep), `act()/extract()/observe()/agent()` primitives ([browserbase](https://www.browserbase.com/blog/stagehand-playwright-evolution-browser-automation), [scrapfly](https://scrapfly.io/blog/posts/stagehand-vs-browser-use)) | Hybrid deterministic-script-plus-AI workflows |
| **Skyvern / OS-Atlas / Cradle / ShowUI** | Vision-grounded GUI agents | Research / niche use cases |
| **c/ua** | Apple Silicon-only sandbox | Not relevant for your Windows box |

### IDE / Coding Agents (April 2026 ranking from real-world testing)

| Tool | Best for | Notes |
|---|---|---|
| **Claude Code** | Complex multi-file refactors, terminal-native | #1 in LogRocket Feb 2026 power rankings; 80.8% SWE-bench Verified ([nxcode](https://www.nxcode.io/resources/news/cursor-alternative-2026-best-ai-code-editors), [morphllm](https://www.morphllm.com/ai-coding-agent)) |
| **Cursor 2.0** | IDE-centric, Composer/agent mode, 8 parallel background agents on cloud VMs | Fastest tab completion; credit-pricing controversy persists |
| **Cline** | BYOK open-source, 5M VS Code installs, dual Plan+Act mode, native subagents (v3.58), CLI 2.0 | **Pair with Cursor or use solo with local 5090 models** |
| **Windsurf** | Cheapest paid IDE at $15/mo, Cascade agent | Cognition acquisition (Feb 2026) creates uncertainty |
| **Aider** | Terminal, surgical diffs, 4.2× fewer tokens than Claude Code on identical tasks ([morphllm](https://www.morphllm.com/comparisons/morph-vs-aider-diff)) | Best for git-disciplined refactors |
| **Continue.dev** | OSS VS Code/JetBrains | Mixed-IDE teams |
| **GitHub Copilot** | Default safe choice, $10/mo, Agent Mode + MCP | Pragmatic for Eightfold work where Copilot may already be sanctioned |

For Adam: **Cursor + Claude Code (CLI) + local Cline (BYOK with Qwen-3-Coder via Ollama)** covers all three brackets.

---

## 4. Architecture Recommendations for Adam's Specific Stack

### The Big Idea: Everything Becomes an MCP Server

Treat each of your existing projects as a **specialized MCP server** exposing its capabilities, so any agent (Claude Code, Cursor, your LangGraph orchestrator, ChatGPT Agent) can call into them uniformly. This is the **single most important architectural decision**, because it's the one thing that prevents lock-in to any framework or vendor — MCP works across Claude, ChatGPT, Gemini CLI, Cursor, every framework you saw above.

```
┌─────────────────── Adam's Personal Agentic OS ────────────────────────┐
│                                                                       │
│   ┌─ ORCHESTRATION ───────────────────────────────────────────┐       │
│   │  LangGraph 1.0 supervisor + Pydantic AI typed agents      │       │
│   │  (Logfire + Langfuse self-hosted for observability)       │       │
│   └────────────┬──────────────────────────────────────────────┘       │
│                │                                                      │
│   ┌─ ROUTING ──┴──────────────────────────────────────────────┐       │
│   │  LiteLLM proxy + Not Diamond + semantic classifier         │       │
│   └────┬─────────────────────────┬─────────────────────────────┘       │
│        │                         │                                    │
│   ┌────┴── LOCAL ──────────┐ ┌───┴── CLOUD ─────────────────┐         │
│   │ Ollama / vLLM on 5090  │ │ Anthropic, OpenAI, Google     │         │
│   │ Qwen-3-32B, R1-70B-FP4 │ │ via OpenRouter/direct         │         │
│   └────────────────────────┘ └───────────────────────────────┘         │
│                                                                       │
│   ┌─ MCP TOOL LAYER (your projects exposed as servers) ─────┐         │
│   │  • magnus-mcp (trading: Tradier/Polygon/FRED tools)      │         │
│   │  • obsidian-mcp (Markus Pfundstein OSS or Smart Conn.)   │         │
│   │  • legion-mcp (your reworked supervisor)                 │         │
│   │  • fortress-mcp (job hunt tools)                         │         │
│   │  • ava-mcp (content gen)                                 │         │
│   │  • fs-mcp / browser-mcp / postgres-mcp (built-in)        │         │
│   │  • google-drive-mcp / gmail-mcp / calendar-mcp           │         │
│   └──────────────────────────────────────────────────────────┘         │
│                                                                       │
│   ┌─ MEMORY ────────────────────────────────────────────────┐         │
│   │  Letta (agent memory) + pgvector (RAG) + Mem0 (prefs)    │         │
│   └──────────────────────────────────────────────────────────┘         │
│                                                                       │
│   ┌─ COMPUTER USE (don't build, integrate) ────────────────┐          │
│   │  UFO² for Windows apps  |  Claude Cowork for shell      │          │
│   │  ChatGPT Agent for web  |  Browser Use for custom flows │          │
│   └──────────────────────────────────────────────────────────┘         │
└───────────────────────────────────────────────────────────────────────┘
```

### Why You Should NOT Try to Save Legion First

Be honest about why Legion "doesn't work very well." This is the most-documented failure pattern in the field. The MAST study (Berkeley, March 2025) cataloged 14 failure modes across 200+ multi-agent traces, with **Coordination Tax accounting for 36.9% of failures** ([arXiv 2503.13657](https://arxiv.org/html/2503.13657v1), [Towards Data Science](https://towardsdatascience.com/the-multi-agent-trap/)). Anthropic's own multi-agent research blog and LangChain's "How and when to build multi-agent systems" both converge on the same conclusion: **most agent systems fail because the LLM can't reason well enough on the task and because the system has too many sub-agents writing into shared state without context engineering** ([LangChain blog](https://blog.langchain.com/how-and-when-to-build-multi-agent-systems/)).

Common LangChain pitfalls that likely apply to Legion:
- **Context engineering neglect** — agents getting subtask descriptions without the why ([LangChain](https://blog.langchain.com/how-and-when-to-build-multi-agent-systems/))
- **No durable execution** — when one tool fails, the whole graph restarts
- **Compound reliability decay** — chain >5 agents and end-to-end success drops below 80% ([Towards Data Science](https://towardsdatascience.com/the-multi-agent-trap/))
- **Infinite retry loops** — Agent A fails, triggers Agent B, which calls Agent A
- **No checkpointing or HITL** — base LangChain (not LangGraph) has weak state durability ([Medium / Ram Milan](https://medium.com/codetodeploy/production-pitfalls-of-langchain-nobody-warns-you-about-44a86e2df29e))

**Recommended path for Legion**: Adopt LangGraph as your orchestration layer, then **port Legion's individual agent logic into LangGraph nodes**. LangGraph's checkpointing, time-travel debugging, and native MCP integration are exactly the missing pieces. Don't multi-agent until a single well-prompted LangGraph agent with the right tools fails on the actual task — Anthropic's effective-agents post and LangChain's are explicit about this ([LangChain](https://docs.langchain.com/oss/python/langchain/multi-agent)).

### Magnus → MCP Server (Concrete Pattern)

Your trading system is the highest-value candidate to MCP-ify because it then becomes accessible from ChatGPT Agent, Claude Cowork, your phone, anywhere:

```python
# magnus_mcp.py (sketch)
from mcp.server import FastMCP
from magnus.tradier import TradierClient
from magnus.polygon import PolygonClient
from magnus.fred import FREDClient

mcp = FastMCP("magnus")

@mcp.tool()
def get_positions() -> list[Position]: ...

@mcp.tool()
def evaluate_signal(symbol: str, strategy: str) -> SignalEval: ...

@mcp.tool()
def fred_series(series_id: str, start: str, end: str) -> Series: ...

@mcp.tool()
def discord_xtrades_recent(channel: str, hours: int) -> list[Alert]: ...

# Read-only tools by default; require explicit human approval for any
# tool that hits Tradier order endpoints. Use FastMCP's auth + 
# elicitation/sampling streaming added in v1.27 (Feb 2026)
```

For trading specifically, point at the **TradingAgents** framework architecture from UCLA/MIT ([arXiv 2412.20138](https://tradingagents-ai.github.io/), [GitHub](https://github.com/TauricResearch/TradingAgents)) — it's built on LangGraph and uses specialized roles (fundamental analyst, sentiment analyst, technical analyst, Bull/Bear researchers, risk management team, fund manager) communicating in a debate pattern. It's the canonical reference architecture for agentic trading research/monitoring on top of an existing execution engine like Magnus. **Critically: keep Magnus's order-execution layer deterministic; use agents for research, monitoring, and signal generation only** ([Wundertrading](https://wundertrading.com/journal/en/learn/article/agentic-trading)).

### Obsidian as the Second Brain Layer

Obsidian crossed 1.5M users with 22% YoY growth and is the right substrate because it's plain-Markdown local-first ([NxCode](https://www.nxcode.io/resources/news/obsidian-ai-second-brain-complete-guide-2026)). Your options, in order of recommendation:

1. **Markus Pfundstein's `mcp-obsidian`** + Local REST API plugin + Templater + Smart Connections — gives you semantic search, Templater execution, full read/write. This is the most popular setup; mature integration with Claude Desktop ([Skywork analysis](https://skywork.ai/skypage/en/obsidian-tools-ai-engineer-guide/1978646309651128320)).
2. **Smart Connections** plugin (133K+ users, brianpetro/obsidian-smart-connections) — local embeddings, semantic Connections view, no setup ([GitHub](https://github.com/brianpetro/obsidian-smart-connections)).
3. **Smart Second Brain (papa)** — open-source Obsidian-native RAG; Ollama-friendly so it can run fully on your 5090 ([GitHub](https://github.com/your-papa/obsidian-Smart2Brain)).
4. **Kanishkez's `obsidian-mcp-sb`** — read-only, intelligent variant for safer agent access.

Pair the chosen Obsidian MCP with a **memory MCP** (`@modelcontextprotocol/server-memory`) and have Claude Code/Cursor remember your PARA folder structure across sessions.

### Memory Architecture

The 2026 consensus from the LongMemEval and LOCOMO benchmarks ([Mem0 State of Memory 2026](https://mem0.ai/blog/state-of-ai-agent-memory-2026), [omegamax](https://omegamax.co/compare)):

| System | Strength | Pick when |
|---|---|---|
| **Mem0** | Three-tier (user/session/agent), 21+ framework integrations, ECAI 2025 published benchmark, hybrid vector+graph store | Personalization, preferences across all your agents |
| **Letta (formerly MemGPT)** | OS-style core/recall/archival memory; agent self-edits via tool calls; full agent runtime | Long-running agents that need unlimited memory |
| **Zep / Graphiti** | Temporal knowledge graph (Neo4j); excellent for entity relationships over time, 71.2% LongMemEval | Trading research where facts evolve |
| **LangMem (LangGraph)** | Episodic + semantic + procedural; agents can rewrite their own instructions | If you commit to LangGraph |
| **Cognee** | Local-first, knowledge-graph RAG | Privacy-sensitive single-user setups |
| **Supermemory** | Optimized for Claude Code / OpenCode / Cursor | Coding agents specifically |

**Recommended for Adam**: **Letta as the agent memory runtime + pgvector (you already have it from Fortress) for RAG + Mem0 for cross-agent user prefs.** Letta and Mem0 can coexist; they answer different questions ([vectorize.io](https://vectorize.io/articles/mem0-vs-letta)).

### Observability

| Tool | Best for | Notes |
|---|---|---|
| **LangSmith** | LangChain/LangGraph users; ~30 min setup, native streaming | $39/seat/mo, 14-day default retention; vendor lock-in to Lang* ([dev.to](https://dev.to/soufian_azzaoui_85ea1c030/i-tried-langsmith-langfuse-helicone-and-phoenix-heres-what-each-gets-wrong-2cjk)) |
| **Langfuse** (MIT) | Self-host, framework-agnostic, OpenTelemetry-native, 50K events/mo free | **Recommended starting point** ([langfuse.com FAQ](https://langfuse.com/faq/all/langsmith-alternative)) |
| **Arize Phoenix** | One-line auto-instrumentation, RAG-specific visualizations | Better for ML teams ([ZenML](https://www.zenml.io/blog/langfuse-vs-phoenix)) |
| **Pydantic Logfire** | Native Pydantic AI integration, OpenTelemetry | Pair with Pydantic AI agents |
| **AgentOps** | Agent-specific metrics, session replays | 12% benchmark overhead ([aimultiple](https://research.aimultiple.com/agentic-monitoring/)) |
| **Helicone** | Proxy-only, dead-simple, 100K req/mo free | Cost tracking, not agent tracing |

**Adam recommendation**: **Self-host Langfuse on Docker + Pydantic Logfire for any Pydantic AI agents.** Both speak OTel, so you can later add Datadog without rework.

---

## 5. Implementation Roadmap (RTX 5090 + Windows 11)

### OS / Container Strategy

The pragmatic answer in 2026: **Native Windows 11 + WSL2 (Ubuntu 24.04) + Docker Desktop**, in that order of where things actually run.

- **Native Windows**: Cursor, Claude Code/Cowork, ChatGPT Desktop, Obsidian, your IDEs, anything with native Windows UI Automation needs (UFO²/UFO³ require Windows-native).
- **WSL2 Ubuntu**: vLLM, TensorRT-LLM serving, Postgres+pgvector, Letta, Langfuse, your MCP servers — all benefit from native Linux. WSL2 has direct GPU passthrough to the 5090 via NVIDIA's CUDA-on-WSL drivers, and Docker Desktop's vLLM runner now works on WSL2+5090 ([Docker blog](https://www.docker.com/blog/docker-model-runner-vllm-windows/)).
- **Docker Desktop in WSL2 backend mode** — proven path, simpler than maintaining native Linux Docker. Mind the licensing (commercial use needs paid sub at Eightfold's scale; for personal use the free tier is fine) ([rsw.io](https://rsw.io/wsl-2-vs-docker-desktop-which-one-should-you-use/)).
- **Avoid dual-boot Linux** — you lose access to UFO², Claude Cowork on Windows, and Cursor's Windows-specific paths. WSL2 closes the gap ~95%.

### Recommended Concrete Stack (April 2026)

```
WINDOWS 11 native:
  - Cursor (latest)            # primary IDE
  - Claude Cowork (research preview)  # GUI computer-use 
  - Claude Code 2.1.85+        # terminal coding agent
  - ChatGPT Desktop            # browser-mode agent fallback
  - Obsidian + Smart Connections + Local REST API + Templater
  - LM Studio                  # GUI model browser
  - Microsoft UFO² (latest)    # Windows app automation
  - Ollama for Windows         # quick local serving

WSL2 Ubuntu 24.04:
  - Python 3.13 (NOT 3.14 - pydantic-core build issues)
  - uv as package manager (fastest, deterministic)
  - PyTorch 2.9.0 cu128 nightly  # for Blackwell sm_120
  - vLLM (built from source per BoltzmannEntropy/vLLM-5090)
  - TensorRT-LLM 0.20.0+ (for NVFP4)
  - Postgres 17 + pgvector + pgvectorscale
  - Qdrant (alternative if you outgrow pgvector)
  - Redis (rate limiting, session state)
  - Letta server
  - Langfuse self-hosted
  - LiteLLM proxy
  - n8n or Temporal (for durable workflow scheduling)

DOCKER:
  - Open WebUI (chat front-end for any backend)
  - AnythingLLM (for document-heavy workspaces)
  - Browserbase Stagehand workers (for browser jobs)
  - OmniTool dockerized Win11 VM (for sandboxed computer-use experiments)
```

### Phase Plan

**Week 1–2: Validate the foundation (don't build yet)**
1. Install Ollama on Windows; pull `qwen3:32b-q4_K_M`, `qwen3-coder-next:latest`, `deepseek-r1:32b`, `llama3.3:70b-instruct-q4_K_M`. Confirm 5090 throughput matches benchmark expectations.
2. Set up WSL2, vLLM with PyTorch 2.9.0 cu128, serve Qwen-3-32B with `--enable-auto-tool-choice --tool-call-parser hermes` per the BoltzmannEntropy reference container.
3. Stand up LiteLLM proxy in WSL2 with three providers: Ollama (local), Anthropic, OpenAI. Unified `/v1/chat/completions` endpoint.
4. Self-host Langfuse Docker, point all LiteLLM traffic to it. You now have local + cloud usage visible in one dashboard.
5. Install Claude Code, Cursor, Claude Cowork. Verify computer use actually works on your machine.

**Concrete first project (the one that proves the architecture)**: **Obsidian Daily Brief Agent**. Every morning at 7:00, a LangGraph agent:
- Pulls overnight Magnus signals (via Magnus MCP server you'll write)
- Checks FRED for new releases
- Reads your Calendar via Google Calendar MCP
- Pulls overnight Discord/XTrades alerts
- Reads your "Today" Obsidian note for stated goals (via Obsidian MCP)
- Writes a structured brief into a new Obsidian note with citations and links

Why this project: it touches **all three life domains** (work calendar, trading, personal knowledge), exercises both local (summarization, embeddings) and cloud (Opus/GPT-5 for synthesis) routes, requires MCP, requires memory, and produces a tangible daily output you'll actually use. If this works for two weeks reliably, your architecture is sound.

**Month 1: Build the spine**
1. Stand up Postgres + pgvector + Letta in WSL2.
2. Write `magnus-mcp` server exposing read-only Magnus tools (Tradier positions, Polygon quotes, FRED, Discord/XTrades parser). Add write tools later, behind explicit human approval.
3. Write `obsidian-mcp` (start with Pfundstein's, add custom tools for your PARA structure).
4. Build the Daily Brief agent in LangGraph 1.0 with checkpointing, observability into Langfuse, memory in Letta.
5. Set up smart routing: simple semantic classifier (a fine-tuned MiniLM) deciding `local | cheap_cloud | frontier_cloud` with explicit overrides for sensitive tasks.

**Month 2: Port and expand**
1. Re-architect Legion: define the three agents that matter most (whatever Legion was supposed to do — distill it). Re-implement as LangGraph nodes with explicit state, durable checkpoints, structured Pydantic outputs.
2. Wrap AVA/AIContentTools and Fortress of Solitude as MCP servers — both already have FastAPI, so this is mostly thin tool wrappers.
3. Add ChatGPT Agent / Claude Cowork as alternative front-ends for the same MCP servers — a key win, because now Adam-on-phone can hit the same agent surface as Adam-at-desk.
4. Add Reachy Mini integration via smolagents (NVIDIA's [DGX Spark + Reachy Mini reference](https://huggingface.co/blog/nvidia-reachy-mini) shows the pattern: route conversation/vision/web-search to different sub-agents; use NeMo Agent Toolkit's LLM Router).

**Month 3: Production-harden + extend**
1. Permissioning model (next section): per-tool, per-time-window approval rules.
2. Cost guards: Portkey or LiteLLM budget caps per agent and per project.
3. Sought Supply: build a content/inventory MCP, agentic price/competitor monitoring.
4. Eightfold work: add Workday/Oracle/SuccessFactors MCP servers (build wrappers on top of their REST APIs); use these for client deliverable acceleration.

---

## 6. Specific Use Cases / Concrete Wins

**Personal life**:
- Calendar/email triage agent — ChatGPT Agent or Claude Cowork with Gmail/Calendar connectors handles 80% of routine scheduling. Use the agent's "watch mode" for any email with $$ amounts.
- Errand/shopping — ChatGPT Agent's BrowseComp 68.9% performance on hard-to-find info ([OpenAI](https://openai.com/index/introducing-chatgpt-agent/)) makes price-comparison and research-and-buy workflows real.
- Obsidian daily/weekly review — auto-generated from completed tasks, calendar events, and meeting transcripts.

**Work (Eightfold AI Lead Solutions Architect)**:
- **Workday/Oracle/SuccessFactors integration acceleration**: Eightfold connects natively to Workday, SAP SuccessFactors, Oracle HCM, Greenhouse, Lever ([PeerSpot](https://www.peerspot.com/products/eightfold-talent-intelligence-platform-reviews), [TheNonTechAI](https://thenontechai.com/best-ai-for-talent-matching-2026-eightfold-hirevue-paradox/)). Build internal MCP servers that wrap your client integrations' typical patterns; have agents draft integration specs, generate field mappings, and lint configurations.
- Technical documentation polish: Claude Sonnet 4.6 1M-context for ingesting full client architecture docs, generating polished deliverables.
- Demo-environment automation: UFO² scripts to set up Workday/SF demo tenants for client meetings.

**Software dev**:
- Code review agent: LangGraph multi-agent with one Reviewer (Opus 4.7), one Test-runner (local Qwen-3-Coder via Cline), one Doc-checker. Run on every PR via GitHub Actions or Cursor background agents.
- Multi-repo coordination: Claude Code's `/loop` scheduled tasks for cross-repo dependency updates.
- Documentation: generate from code + Obsidian architecture notes.

**Trading (Magnus extension)**:
- Replicate the [TradingAgents pattern](https://tradingagents-ai.github.io/) on top of Magnus: Bull researcher / Bear researcher / Risk manager debate before any signal is committed. Cumulative-return and Sharpe improvements were shown vs single-agent baselines.
- 24/7 monitoring agent on local hardware (no cloud egress for sensitive position data).
- News/sentiment ingestion via FRED + Discord MCP, with mem0 storing per-strategy preferences.

**Knowledge management**:
- Smart Connections handles semantic suggestions in Obsidian; your memory MCP makes Claude/Cursor aware of your PARA folder structure across sessions ([Medium / Artur Koter](https://medium.com/@koter.artur/i-gave-my-obsidian-second-brain-a-brain-claudes-brain-heres-how-e62d9ac0be80)).
- Auto-vault hygiene agent — runs nightly, detects orphaned notes, suggests links, surfaces cross-references.

**Cross-domain bridge**: The Obsidian-rooted memory layer is the bridge. Every agent writes its outputs into a structured Obsidian note (or the Letta archival store). Personal goals influence work prioritization; trading P&L feeds personal budget; client deliverables surface as Obsidian project notes. **The agentic OS is real when you can ask "what should I focus on right now?" and get a single answer that crosses all three lives.**

---

## 7. Risks, Pitfalls, Trust & Safety

### Failure Modes (and Specific Mitigations)

The five failures from MAST that account for most production breakage and the OWASP Top 10 for Agentic Applications (Dec 2025) ([Swarm Signal](https://swarmsignal.net/ai-agent-security-2026/), [Towards Data Science](https://towardsdatascience.com/the-multi-agent-trap/)):

1. **Compound reliability decay**: per-step success rates multiply. **Cap chains at 5 sequential steps; insert verification at step 3 and 5.**
2. **Coordination tax (36.9% of failures)**: ambiguous instructions to two agents → divergent interpretations. **Use explicit Pydantic-typed contracts between every node.**
3. **Infinite retry loops**: max 3 retries, exponential backoff, dead-letter queues, cycle detection in the orchestrator.
4. **Prompt injection (73% of production deployments tested)**: see security section below.
5. **Memory poisoning**: agents writing wrong facts to Letta/Mem0 corrupt future reasoning. Use Mem0's conflict-detection or write-quarantine pattern.

### The Lethal Trifecta and What to Do About It

Simon Willison's framing, validated by the OpenClaw, ServiceNow, and Claudy Day incidents ([airia](https://airia.com/ai-security-in-2026-prompt-injection-the-lethal-trifecta-and-how-to-defend/), [TrueFoundry](https://www.truefoundry.com/blog/claude-code-prompt-injection)): an agent is exploitable when it has all three of (1) access to private data, (2) exposure to untrusted tokens, (3) an exfiltration vector. Your computer-use agents will have all three.

**Concrete sandboxing rules** (from NVIDIA AI Red Team and the practical sandbox-for-coding-agents writeup at [Penligent](https://www.penligent.ai/hackinglabs/sandboxes-for-coding-agents/) and [NVIDIA Developer](https://developer.nvidia.com/blog/practical-security-guidance-for-sandboxing-agentic-workflows-and-managing-execution-risk/)):

1. **Network egress allowlist** — by default, only allow traffic to known LLM APIs and your specific MCP endpoints. Block arbitrary outbound.
2. **No file writes outside the workspace** — UFO²'s PiP virtual desktop, Docker Sandboxes, or microVMs for risky agents.
3. **No writes to config files anywhere** — agents that can write `.cursorrules`, `CLAUDE.md`, hooks, or local MCP configs can persistently inject prompts. Read-only on those.
4. **Credential proxy** — agents never see raw API keys / Tradier tokens. Route via a proxy that injects auth at egress.
5. **Approval thresholds** — irreversible/financial actions always require human approval, even in "auto mode." Anthropic's data shows 93% of approval prompts get approved, so design the prompts to highlight the *novel* fields ([Penligent](https://www.penligent.ai/hackinglabs/sandboxes-for-coding-agents/)).
6. **Canary tokens** in your Obsidian vault and any sensitive MCP responses — if they hit your network monitor outbound, an agent has been injected.
7. **Specifically for Magnus**: the agent layer should have *only read* access to brokerage/positions; **order placement stays in Magnus's deterministic path with a human-keyed second factor.**

### Trading-Account Specifics

Run any agent that touches Tradier or Polygon credentials in a dedicated Docker container with:
- Network policy: only outbound to api.tradier.com, api.polygon.io, your Postgres, your LiteLLM proxy.
- Mounted only `/app/magnus_readonly`, no host home directory.
- Tradier credentials injected via Docker secrets, not env vars in the prompt context.
- No MCP servers that touch the same network namespace as your browser-using agents.

### Cost Runaway Prevention

- **Per-key budget caps** in LiteLLM (`max_budget` per virtual key per month).
- **Daily spend alarms** to email/Discord at 50%, 80%, 100% of budget.
- **Per-task cost ceilings** in your LangGraph state — abort runs that exceed threshold.
- **Routing default = cheapest viable**: aggressive use of Haiku ($1/$5), Sonnet 4.6 ($3/$15), Gemini Flash before you ever hit Opus 4.7 or GPT-5.4 xhigh.
- **Watch out for AutoGen/conversational patterns**: 4 agents × 5 rounds × Opus = $20+ per task ([Lushbinary](https://lushbinary.com/blog/langgraph-vs-crewai-vs-autogen-ai-agent-framework-comparison/)).

### Why Legion May Not Be Working

Without seeing the code, the highest-probability causes (from documented LangChain pitfalls — [Medium / PrajnaAI](https://prajnaaiwisdom.medium.com/why-most-ai-agents-fail-lessons-from-langchains-agentic-ai-guide-b019d378b4dc)):

- **Vague scope** — "orchestrate everything" rather than one specific testable workflow
- **Reasoning ceiling** — LangChain agents hit a wall when the underlying single-step prompt doesn't reliably solve the task
- **Context starvation** — sub-agents getting prompts but not enough surrounding context (Cognition / LangChain "context engineering" critique)
- **No checkpointing** — vanilla LangChain ≠ LangGraph; restart-from-scratch on every failure
- **Silent tool failures** — tools returning malformed JSON without structured error handling
- **State drift** — multi-agent shared state corrupts and there's no validation pass
- **Library upgrade churn** — LangChain has shipped breaking changes regularly

The fix is the LangGraph rewrite, not better prompts.

---

## 8. Future Outlook (Late 2026 → 2027)

**High-confidence bets**:
- **MCP wins as the universal tool protocol** — Anthropic donated it to the Linux Foundation; Google, OpenAI, Microsoft, and AWS all ship it. Build everything as an MCP server.
- **A2A (Agent-to-Agent) protocol** matures alongside MCP for cross-framework agent comms — Google ADK 2.0 and Microsoft Agent Framework 1.0 already support it.
- **Local FP4/NVFP4 inference becomes the default** on consumer Blackwell — TensorRT-LLM and vLLM both support it; HuggingFace `nvidia/` namespace pre-quantized checkpoints accelerate adoption ([Spheron](https://www.spheron.network/blog/fp4-quantization-blackwell-gpu-cost/)).
- **Terminal-native + IDE-native dual stack** for coding agents settles in — Claude Code (terminal) + Cursor/Cline (IDE) is the working combination.
- **Computer use becomes commodity** — by late 2026, "an agent that can use your desktop" is no longer a feature, it's an expectation. UFO²/UFO³ for native, Claude/OpenAI for managed.

**Bets to avoid / wait on**:
- **Don't build your own desktop control layer** from scratch. UFO² and Claude Computer Use are too far ahead.
- **Don't bet on AutoGen 0.x** — it's in maintenance mode ([microsoft/autogen](https://github.com/microsoft/autogen)).
- **Don't lock into proprietary "agent OS" platforms** that wrap vendor models; they'll get squeezed between MCP-native open-source and the foundation-model providers' own products (Claude Cowork, ChatGPT Agent).
- **Be skeptical of the agentic-trading hype** — most fully-autonomous trading agents underperform; the disciplined pattern is **research/monitoring agents that surface signals to a deterministic execution engine** like Magnus, with humans approving live trades ([Wundertrading](https://wundertrading.com/journal/en/learn/article/agentic-trading)).
- **Watch but don't adopt yet**: Pippin (cultural project, framework still maturing); pure code-agent frameworks like smolagents alone for production (great as a component, not as a spine).

**Build vs. wait**:
- **Build now**: Your domain-specific MCP servers (magnus, obsidian, fortress, ava). Nobody else will build them.
- **Wait/integrate**: Computer use, browser agents, IDE agents — adopt the leaders, don't reinvent.
- **Build the bridges, not the bricks**: The orchestration logic that makes *your* personal/work/dev life cohere is unique to you. The model layer, GUI control layer, and tool protocols are commodities.

---

## "Do This First" — Prioritized Action List

1. **(This week)** Install Ollama, pull Qwen-3-32B Q4 + Qwen-3-Coder-Next + DeepSeek-R1-Distill-Llama-70B-NVFP4. Confirm 5090 throughput. Stand up LiteLLM proxy + self-hosted Langfuse in WSL2.
2. **(Week 2)** Install Claude Code 2.1.85+, Cursor 2.0+, Claude Cowork. Configure each with the Markus Pfundstein Obsidian MCP + `@modelcontextprotocol/server-memory`. Confirm computer-use works.
3. **(Week 3)** Write `magnus-mcp` (read-only first) and `obsidian-mcp` if you need a custom one. Wrap them with FastMCP, register with Claude Desktop.
4. **(Week 4)** Build the Obsidian Daily Brief agent in LangGraph 1.0 with Letta memory + Pydantic-typed state + Langfuse tracing. **Validate the architecture before scaling.**
5. **(Month 2)** Port Legion's logic into LangGraph nodes. Don't keep the old name if it's holding bad assumptions — rename and start fresh.
6. **(Month 2)** Add ChatGPT Agent / Claude Cowork as alternative front-ends for the same MCP servers — phone access to Adam's agentic OS.
7. **(Month 3)** Sandbox + permission model + cost caps before you hand any agent meaningful authority over your trading or work accounts.
8. **(Ongoing)** Treat MCP as your portability insurance. If LangGraph or Pydantic AI or Anthropic ever burns you, the MCP layer keeps you free to move.

The single biggest mindset shift: **you are not building "an AI" — you are building a personal infrastructure that composes AI providers, your projects, and standardized protocols**. The model providers will keep getting better. The protocols (MCP, A2A) will keep stabilizing. Your job is to build the connective tissue — your MCP servers, your routing rules, your memory layer, your sandboxing — so that improvements anywhere in the stack become improvements to your daily life with zero rework. That's what an agentic OS actually is in 2026.
