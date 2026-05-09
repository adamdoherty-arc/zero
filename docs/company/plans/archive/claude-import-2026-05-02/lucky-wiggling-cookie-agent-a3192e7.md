# Research Plan: Automatic Prompt Optimization Frameworks for Legion

## Objective
Identify OSS frameworks/repos for automatic, continuous prompt optimization that can integrate with Legion (Python / FastAPI / LangGraph / SQLAlchemy). The goal system behavior:

1. Every LLM prompt/response (already logged in `llm_call_details`) gets an automatic quality score + weakness list.
2. A "how this prompt could be better" suggestion is attached to each response.
3. Prompts improve iteratively over time by learning from past failures.

## Legion-Specific Constraints
- Python 3.11+ / FastAPI / SQLAlchemy 2.x async / PostgreSQL
- LangGraph is used for sprint execution, agent swarm, lifecycle — any optimizer must coexist, not replace
- MiniMax M2 is currently the sole provider (Ollama/Kimi gated off post Recovery-01)
- Every LLM call already records `_source=`, prompt, response, latency, cost, and (for swarm path) `qa_status`
- `llm_review_agent` already exists — it reviews past calls via Kimi K2.5 and writes scores to `llm_call_details` (columns `review_status/score/summary/flags`). Any new optimizer should complement, not duplicate this
- `episodic_memory_service` + `LearningAggregatorService` + `enrich_task_context()` already inject few-shot learnings from past episodes. This is the natural wiring point for an optimizer
- Sprint 2871 was the first to hit Learning Capture = 100; the pipeline is finally producing clean data to train on

## Ranking Criteria (in order)
1. **Continuous / online learning** (not one-shot batch) — Legion never stops running
2. **Human-readable suggestions** (not just score deltas) — matches the "how could this prompt be better?" requirement
3. **LangGraph compatibility** — documented or demonstrated integration
4. **Maintenance activity in 2025/2026** — stale paper repos are a risk
5. **Low ground-truth requirement** — Legion has outcomes (test_passed, sprint grade, qa_status) not labeled datasets
6. **Integration complexity** — drop-in library beats full framework rewrite

---

## Ranked Candidates (best fit first)

### Tier 1 — Strong fit for Legion

#### 1. DSPy + GEPA (Stanford / gepa-ai)
- **Repos**: [stanfordnlp/dspy](https://github.com/stanfordnlp/dspy) + [gepa-ai/gepa](https://github.com/gepa-ai/gepa)
- **Description**: DSPy = declarative "programming not prompting" framework; GEPA = reflective prompt optimizer that reads execution traces, identifies what went wrong, and evolves prompts. Available inside DSPy as `dspy.GEPA`.
- **License**: Apache 2.0 (DSPy), Apache 2.0 (GEPA)
- **Activity**: Very active. DSPy ~16k stars, 160k monthly downloads as of 2025. GEPA paper accepted ICLR 2026 (Oral).
- **Algorithm**: Reflective evolution — LLM reads trajectory ("what went well / what went wrong / what can be improved") and proposes new prompts, builds a tree of candidates. Uses textual feedback, not just scalar scores.
- **Requires**: LLM API (any provider DSPy supports), evaluation metric function, small seed dataset of task examples. Does NOT require labeled ground truth if you have any scoring function (Legion already has sprint grades + qa_status + test_passed).
- **Integration**: Medium. DSPy is a full framework, but GEPA can be used as a standalone optimizer. Multiple 2025 blog posts document **LangGraph + DSPy + GEPA** running in production agentic-researcher pipelines.
- **Online learning**: GEPA is iterative; reruns append to the candidate tree. Not inherently streaming but the "one sprint = one rollout" mapping is natural for Legion.
- **Human-readable output**: YES — GEPA's whole design is natural-language reflection ("this prompt failed because it did not specify the output format"). This matches Legion's requirement exactly.
- **Notable results**: GPT-4.1 Mini 46.6% → 56.6% on AIME 2025; DSPy ChainOfThought 67% → 93% on MATH benchmark via GEPA; outperforms RL (GRPO) by 6-20% with 35x fewer rollouts.
- **Legion fit**: ★★★★★ Best match. Already has known LangGraph integration patterns. Uses natural language feedback (Legion already has `last_error`, `review_summary`, `test_output`). Can run per-sprint as a background job.

#### 2. TextGrad (Stanford / Zou Lab)
- **Repo**: [zou-group/textgrad](https://github.com/zou-group/textgrad)
- **Description**: "PyTorch for text" — automatic differentiation via text, backpropagates textual gradients through LLM workflows. Published in *Nature*.
- **License**: MIT
- **Activity**: Very active, published in Nature (peer-reviewed), actively maintained 2024-2025.
- **Algorithm**: LLM-produced textual gradients flow backwards through a computation graph. `.backward()` on an LLM output produces a natural-language critique; `.step()` updates the prompt variable. Identical API to PyTorch.
- **Requires**: LLM API access, a loss/evaluation LLM (can be the same model), a differentiable-in-text computation graph (you wrap prompts as `tg.Variable`).
- **Integration**: Medium-high. The PyTorch analogy is powerful but requires wrapping each prompt as a `Variable` and each LLM call as a "forward pass" — easier on greenfield than retrofit. Works inside LangGraph nodes if you treat each node as a TextGrad op.
- **Online learning**: YES — designed for per-example optimization. Can optimize live.
- **Human-readable output**: YES — the entire gradient IS a natural-language critique ("The system prompt should add an explicit format constraint because the model returned markdown instead of JSON.")
- **Notable results**: GPT-4o zero-shot 51% → 55% on GPQA; 20% relative gain on LeetCode-Hard; applied to molecule optimization and radiotherapy planning.
- **Legion fit**: ★★★★★ Second best. "Gradient as critique" is exactly the "how could this prompt be better?" feature Legion wants. `.backward()` on a failed sprint task yields immediately usable human-readable improvement suggestions.

#### 3. AdalFlow (SylphAI)
- **Repo**: [SylphAI-Inc/AdalFlow](https://github.com/SylphAI-Inc/AdalFlow)
- **Description**: "PyTorch-like" library for LLM app construction AND auto-optimization in a single training loop. Combines textual gradient descent + few-shot bootstrap.
- **License**: MIT
- **Activity**: Active — Jan 2025 paper "Auto-Differentiating Any LLM Workflow", Sep 2025 LAD-VF paper. Community-driven.
- **Algorithm**: LLM-AutoDiff + Learn-to-Reason — unified textual gradient + few-shot bootstrap in one training loop. Claims highest accuracy among automatic prompt optimization libraries.
- **Requires**: LLM API access, a trainable task pipeline, evaluation metric. Works zero-shot or few-shot.
- **Integration**: Medium. Competes with DSPy for the "declarative framework" slot. Less mature LangGraph integration than DSPy but same architectural mental model.
- **Online learning**: Training-loop based; can be invoked continuously.
- **Human-readable output**: YES — uses textual gradients like TextGrad.
- **Notable results**: Claims SOTA accuracy vs other auto-optimizers in the LLM-AutoDiff paper.
- **Legion fit**: ★★★★☆ Strong, but DSPy+GEPA has a larger ecosystem and known LangGraph integration patterns. Worth prototyping side-by-side.

---

### Tier 2 — Usable but requires more work

#### 4. Microsoft PromptWizard
- **Repo**: [microsoft/PromptWizard](https://github.com/microsoft/PromptWizard)
- **Description**: Task-aware, agent-driven, feedback-driven self-evolving prompt optimizer. Research published in ACL 2025 Findings.
- **License**: MIT
- **Activity**: Active (Microsoft-maintained, ACL 2025 Findings paper).
- **Algorithm**: Self-evolving feedback loop — LLM generates, critiques, and refines both the instruction and in-context examples in tandem. Uses positive AND negative examples; negative examples drive refinement.
- **Requires**: LLM API access, a small training set, evaluation metric. No ground truth labels strictly required if you have any outcome signal.
- **Integration**: Medium. Framework-style, not a drop-in library. No documented LangGraph integration.
- **Online learning**: Iterative batch refinement — not truly online but rerunnable.
- **Human-readable output**: YES — critique-based, explicitly identifies prompt weaknesses.
- **Notable**: Optimizes BOTH the instruction and the few-shot examples, which Legion's episodic memory system needs.
- **Legion fit**: ★★★★☆ Great fit conceptually (feedback-driven, critique-based). Lower rank only because DSPy+GEPA has better ecosystem + LangGraph integration + more recent activity.

#### 5. Microsoft SAMMO
- **Repo**: [microsoft/sammo](https://github.com/microsoft/sammo)
- **Description**: Structure-Aware Multi-Objective Metaprompt Optimization. Treats prompts as structured programs that can be transformed by mutation operators.
- **License**: MIT
- **Activity**: Maintained (EMNLP 2024 paper). Regular releases.
- **Algorithm**: Compile-time symbolic program search over prompt structure via mutation operators (rephrase, reorder sections, add/remove components). Multi-objective — can optimize cost, accuracy, latency simultaneously.
- **Requires**: Prompts expressed as SAMMO "prompt programs" (Markdown components), eval function, small dataset.
- **Integration**: Medium-high — requires rewriting prompts in SAMMO's structured format.
- **Online learning**: Batch compile-time optimization; rerunnable.
- **Human-readable output**: Partial — shows which mutation improved the score, but less narrative than GEPA/TextGrad.
- **Notable results**: 10-100% gains on instruction tuning, 26-133% on RAG, 40%+ on prompt compression.
- **Legion fit**: ★★★☆☆ Strong algorithm but the "rewrite prompts in our DSL" cost is high. Multi-objective is attractive (Legion cares about cost + quality + latency).

#### 6. LangSmith + Promptim (LangChain)
- **Repos**: [hinthornw/promptimizer](https://github.com/hinthornw/promptimizer) + LangSmith platform
- **Description**: LangChain's experimental prompt optimization library. Given initial prompt + dataset + evaluators, runs a metaprompt loop to propose and test improvements.
- **License**: MIT (promptimizer)
- **Activity**: Experimental (LangChain labels it so), active. Paired with LangSmith (commercial SaaS).
- **Algorithm**: Metaprompt loop — run over train, score, pass (inputs, outputs, expected, scores) to a meta-LLM that proposes a new prompt, validate on dev, keep if better.
- **Requires**: LangSmith account (free tier exists), dataset in LangSmith, local evaluators, LLM API.
- **Integration**: EASIEST — Legion already uses LangGraph and could adopt LangSmith for tracing + datasets with minimal code changes. `pip install promptim`.
- **Online learning**: Batch-oriented but supports offline + online evaluation modes.
- **Human-readable output**: Meta-LLM produces improvement suggestions in natural language.
- **Legion fit**: ★★★☆☆ Lowest friction integration BUT ties Legion to LangSmith SaaS for best experience. Acceptable if you're already in the LangChain ecosystem. The library is explicitly labeled "experimental".

---

### Tier 3 — Academic / paper-first, use as reference

#### 7. EvoPrompt (Microsoft / beeevita)
- **Repos**: [microsoft/EvoPrompt](https://github.com/microsoft/EvoPrompt) + [beeevita/EvoPrompt](https://github.com/beeevita/EvoPrompt)
- **Description**: ICLR 2024 paper implementation. Connects LLMs with evolutionary algorithms (GA + differential evolution) for discrete prompt optimization.
- **License**: MIT
- **Activity**: Paper repo — maintained but not rapidly evolving. Microsoft fork as well.
- **Algorithm**: Evolutionary — GA crossover/mutation via LLM prompts. Population of prompts, fitness = task metric, LLM performs the mutation operation.
- **Requires**: Initial prompt population, scoring function, dataset for fitness evaluation.
- **Integration**: Research code — you'll need to fork + adapt, not drop-in.
- **Online learning**: Batch evolutionary. Each generation is one eval pass.
- **Human-readable output**: Partial — outputs final prompt but less natural-language critique.
- **Notable**: Up to 25% on BBH over human prompts. Simpler concept than GEPA but less feedback-rich.
- **Legion fit**: ★★☆☆☆ Solid algorithm but superseded by GEPA for reflective evolution. Use as reference implementation only.

#### 8. OPRO (Google DeepMind)
- **Repo**: [google-deepmind/opro](https://github.com/google-deepmind/opro)
- **Description**: "Large Language Models as Optimizers" — LLM reads previous solutions + scores, proposes new solutions.
- **License**: Apache 2.0
- **Activity**: Paper repo, not a maintained library. Last significant activity around publication.
- **Algorithm**: Meta-optimization — LLM prompt contains trajectory of (solution, score) pairs and asks model to propose a higher-scoring solution. Iterative.
- **Requires**: LLM API, evaluation function, seed solutions.
- **Integration**: Research code — Python 3.10, Google AI APIs baked in.
- **Online learning**: Iterative but batch per step.
- **Human-readable output**: Partial — returns optimized prompts, limited natural-language diagnostics.
- **Notable results**: +8% on GSM8K, +50% on BBH over human prompts.
- **Legion fit**: ★★☆☆☆ Foundational reference. Re-implement the idea inside DSPy/GEPA rather than using the raw code.

#### 9. APE — Automatic Prompt Engineer (keirp)
- **Repo**: [keirp/automatic_prompt_engineer](https://github.com/keirp/automatic_prompt_engineer)
- **Description**: 2022 paper — LLM generates candidate prompts, evaluator LLM scores them, best candidate is selected.
- **License**: MIT
- **Activity**: Historical / minimal maintenance.
- **Algorithm**: LLM-based prompt search via score-then-select. The "generate-and-rank" baseline that most modern optimizers are compared against.
- **Requires**: Input/output dataset, LLM API, scoring function.
- **Integration**: Research code, old dependencies.
- **Online learning**: One-shot batch.
- **Human-readable output**: No — returns selected prompts, no per-prompt critique.
- **Legion fit**: ★☆☆☆☆ Historical interest only. Pattern is subsumed by DSPy/GEPA.

#### 10. Promptbreeder (DeepMind — community implementations)
- **Repos**: [vaughanlove/PromptBreeder](https://github.com/vaughanlove/PromptBreeder), [suvalaki/prompt_breeder](https://github.com/suvalaki/prompt_breeder), [ambroser53/Prompt-Day-Care](https://github.com/ambroser53/Prompt-Day-Care)
- **Description**: Self-referential — evolves task prompts AND the mutation prompts that mutate them.
- **License**: Varies by implementation (DeepMind did not release official code). Community versions typically MIT/Apache.
- **Activity**: Community implementations only. DeepMind never released official code. Most impls not production-ready.
- **Algorithm**: Two-population evolution — task prompts + mutation prompts co-evolve.
- **Requires**: Dataset, scoring function, LLM API.
- **Integration**: Community implementations are prototype-quality.
- **Online learning**: Batch generational.
- **Human-readable output**: No.
- **Legion fit**: ★☆☆☆☆ Interesting idea, not production-ready anywhere. Skip unless researching.

#### 11. AutoPrompt (Eladlev)
- **Repo**: [Eladlev/AutoPrompt](https://github.com/Eladlev/AutoPrompt)
- **Description**: Despite name, this is NOT the gradient-based AutoPrompt from the 2020 paper. This is an Intent-based Prompt Calibration framework — iteratively builds edge-case datasets and calibrates prompts.
- **License**: Apache 2.0
- **Activity**: Active.
- **Algorithm**: Dataset-Estimator-Evaluator-Optimizer loop. Generates challenging edge cases, refines prompts against them.
- **Requires**: Initial prompt, task definition, LLM API. Can run without user-provided dataset (generates its own).
- **Integration**: Medium — self-contained framework.
- **Online learning**: Iterative calibration.
- **Human-readable output**: Partial — shows edge cases + rewritten prompts.
- **Legion fit**: ★★★☆☆ Interesting because it auto-generates edge cases (useful for Legion's sparse ground truth). Worth a prototype.

#### 12. Microsoft Trace / OptoPrime
- **Repo**: [microsoft/Trace](https://github.com/microsoft/Trace)
- **Description**: NeurIPS 2024 — "generative optimization" via execution traces + LLM-as-optimizer. Treats computational workflows as graphs and optimizes heterogeneous parameters.
- **License**: MIT
- **Activity**: Active (Microsoft Research + Stanford).
- **Algorithm**: OPTO (Optimization with Trace Oracle). Graph-of-operations is recorded, OptoPrime LLM reads the trace as a code debugging report, modifies trainable=True parameters.
- **Requires**: Operations wrapped as traceable Python objects, feedback function (score or natural language).
- **Integration**: High — requires rewriting agent steps as `trace.node`-decorated Python functions.
- **Online learning**: Per-execution iterative optimization. Closest to "live" of all the frameworks.
- **Human-readable output**: YES — the optimizer reads and reasons over a debugging report.
- **Notable**: 1000x speedup over RL on robot control tasks. Not all workflows are prompts; can also tune code/hyperparameters.
- **Legion fit**: ★★★☆☆ Most ambitious option — ALSO optimizes non-prompt parameters (hyperparameters, code). High integration cost but the payoff is a unified optimizer for the whole Legion graph. Worth investigating after DSPy+GEPA prototype lands.

---

## Recommendation for Legion

### Proposed implementation plan (two-phase)

**Phase 1 — Shadow-mode quality scoring (2-3 sprints)**

Use **TextGrad** as a per-call review optimizer, running in parallel to the existing `llm_review_agent`:
- For each `llm_call_details` row, wrap the prompt + response in a TextGrad variable
- Call `.backward()` using the existing signals as the loss: `test_passed`, `qa_status`, `sprint_grade`, `last_error`
- Store the resulting natural-language "gradient" in a new `suggested_improvement` TEXT column on `llm_call_details`
- Frontend: render the suggestion in `LLMCallDetailDialog` as a "How this prompt could improve" section
- No prompts are automatically updated yet — humans-in-the-loop review

This is the lowest-risk way to validate the idea: no existing code changes, one new table column, one background worker.

**Phase 2 — Reflective evolution for recurring prompts (4-6 sprints)**

Use **DSPy + GEPA** to actually evolve the highest-volume prompts (task decomposition, agent planner, sprint generator):
- Wrap the prompt templates as `dspy.Signature` modules
- Create a metric function from sprint outcomes: `lambda pred, gold: sprint.grade.overall_score / 100.0`
- Run `dspy.GEPA(metric=..., auto="medium").compile(program, trainset=recent_sprints)`
- Store evolved prompt versions in a new `prompt_versions` table with lineage, grade delta, rollback switch
- Gate rollouts behind a feature flag (`ENABLE_PROMPT_EVOLUTION=false` by default); canary on low-stakes sprints first

### Why this combo?
- **TextGrad** gives Legion the per-call human-readable suggestion that the user asked for, without changing any existing behavior
- **DSPy+GEPA** gives Legion the continuous improvement loop, targeted at the prompts that matter most
- Both work with LangGraph (documented patterns exist)
- Both produce natural-language output that can populate UI tooltips
- Both are Apache/MIT licensed and actively maintained in 2025-2026

### What NOT to use
- **LangSmith-only path**: too much LangChain ecosystem coupling for a system that's mostly LangGraph + custom services
- **Promptbreeder community forks**: not production-ready
- **APE / OPRO**: superseded by GEPA, which was built on their lessons
- **SAMMO**: requires rewriting Legion's prompts into a new DSL (too expensive for the marginal gain)

### Data readiness check
Before either phase can run, Legion needs:
- [x] Per-call prompt + response logging (done: `llm_call_details`)
- [x] Outcome signal (done: sprint grades, qa_status, test_passed)
- [x] `_source=` tagging so we know WHICH prompt was used (done: Dev-02)
- [ ] Prompt template registry (not yet — many prompts are inline f-strings). THIS IS THE BIGGEST BLOCKER. Without a registry, neither TextGrad nor GEPA knows which "variable" to optimize.
- [ ] Train/eval split policy — which past sprints to use for training vs validation
- [ ] Rollback safety — if an evolved prompt regresses, revert automatically on grade drop

Creating a `prompt_registry.py` that surfaces every prompt template as a named, versioned string is a prerequisite sprint (`Learn-14: Prompt registry` or similar).

## Appendix — Full URL list

- [stanfordnlp/dspy](https://github.com/stanfordnlp/dspy)
- [DSPy homepage](https://dspy.ai/)
- [gepa-ai/gepa](https://github.com/gepa-ai/gepa)
- [dspy.GEPA optimizer docs](https://dspy.ai/api/optimizers/GEPA/overview/)
- [GEPA paper (arXiv 2507.19457)](https://arxiv.org/abs/2507.19457)
- [microsoft/PromptWizard](https://github.com/microsoft/PromptWizard)
- [PromptWizard Microsoft Research blog](https://www.microsoft.com/en-us/research/blog/promptwizard-the-future-of-prompt-optimization-through-feedback-driven-self-evolving-prompts/)
- [zou-group/textgrad](https://github.com/zou-group/textgrad)
- [TextGrad paper (arXiv 2406.07496)](https://arxiv.org/abs/2406.07496)
- [TextGrad homepage](https://textgrad.com/)
- [SylphAI-Inc/AdalFlow](https://github.com/SylphAI-Inc/AdalFlow)
- [AdalFlow docs](https://adalflow.sylph.ai/)
- [microsoft/sammo](https://github.com/microsoft/sammo)
- [SAMMO paper (arXiv 2404.02319)](https://arxiv.org/html/2404.02319v1)
- [microsoft/EvoPrompt](https://github.com/microsoft/EvoPrompt)
- [beeevita/EvoPrompt](https://github.com/beeevita/EvoPrompt)
- [EvoPrompt paper (arXiv 2309.08532)](https://arxiv.org/abs/2309.08532)
- [google-deepmind/opro](https://github.com/google-deepmind/opro)
- [OPRO paper (arXiv 2309.03409)](https://arxiv.org/abs/2309.03409)
- [keirp/automatic_prompt_engineer](https://github.com/keirp/automatic_prompt_engineer)
- [Promptbreeder paper (arXiv 2309.16797)](https://arxiv.org/abs/2309.16797)
- [vaughanlove/PromptBreeder](https://github.com/vaughanlove/PromptBreeder)
- [suvalaki/prompt_breeder](https://github.com/suvalaki/prompt_breeder)
- [Eladlev/AutoPrompt](https://github.com/Eladlev/AutoPrompt)
- [microsoft/Trace](https://github.com/microsoft/Trace)
- [Trace homepage](https://microsoft.github.io/Trace/)
- [hinthornw/promptimizer](https://github.com/hinthornw/promptimizer)
- [Promptim LangChain blog](https://blog.langchain.com/promptim/)
- [LangSmith Evaluation docs](https://docs.langchain.com/langsmith/evaluation)
- [joelgrus/dspy-langgraph](https://github.com/joelgrus/dspy-langgraph) — combining DSPy with LangGraph
- [LangGraph + DSPy + GEPA production example](https://www.rajapatnaik.com/blog/2025/10/23/langgraph-dspy-gepa-researcher)
