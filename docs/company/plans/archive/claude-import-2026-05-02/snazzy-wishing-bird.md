# Zero AI Company: Research, Experiments & Idea Generation

## Context

Zero currently has strong single-agent orchestration (17 LangGraph routes, multi-provider LLM routing, research/money-maker services) but lacks **multi-agent collaboration** where specialized roles (CEO, Researcher, Analyst, Engineer, Validator) work together on complex tasks. The AI landscape in 2026 has matured significantly:

- **CrewAI** (45.9k stars, 12M+ daily executions) proves role-based agent collaboration works at scale
- **MetaGPT** (64.1k stars) shows SOP-encoded multi-agent workflows produce better outputs
- **OrgAgent** (April 2026, Nature-adjacent) demonstrates 3-layer governance/execution/compliance hierarchies outperform flat structures
- **GPT-Researcher** provides a proven recursive deep research architecture
- **Council of Agents** patterns show +13.2% reasoning improvement with multi-model debate

**Goal**: Add an "AI Company" layer to Zero with role-based agents that collaborate on deep research, run experiments, generate/validate ideas, and make consensus decisions — all built on Zero's existing LangGraph + multi-provider LLM stack.

**Decision: Build custom on LangGraph** (not import CrewAI/MetaGPT) because:
- Zero already has production LangGraph orchestration + PostgreSQL checkpointing
- Zero's multi-provider LLM router is more cost-efficient than any framework's defaults
- Tighter integration with existing services (research, money_maker, SearXNG, task execution)
- No external framework churn risk

**Cost strategy: Kimi plans, Gemma 4 executes.** Gemma 4 is now available locally on Ollama (free) in 4 variants: `gemma4:31b` (19GB), `gemma4:26b` (17GB), `gemma4:e4b` (9.6GB), `gemma4:e2b` (7.2GB). The core pattern:
1. **Kimi K2.5** ($0.60/$2.50/1M) handles planning, decomposition, and structured prompt generation
2. **Gemma 4** (FREE on Ollama) handles execution of those structured prompts
3. This mirrors Zero's existing `plan_then_execute` pattern but formalizes it at the agent role level

Gemma 4 works well for execution because Kimi's structured outputs include explicit instructions, expected output format, and evaluation criteria — removing ambiguity that would hurt a local model. For tasks requiring genuine reasoning (strategic decisions, novel synthesis), Kimi stays in the loop.

---

## Phase 1: Agent Role Framework (Foundation)

### New files
- `backend/app/models/agent_company.py` — Pydantic models for roles, tasks, experiments, council
- `backend/app/services/agent_company_service.py` — Core agent execution engine
- `backend/app/routers/agent_company.py` — REST API
- `backend/app/migrations/versions/015_ai_company.py` — DB tables

### Database tables (migration 015)

**`agent_roles`** — Role definitions with LLM config
| Column | Type | Notes |
|--------|------|-------|
| id | String(64) PK | "ceo", "researcher", "analyst", "engineer", "validator" |
| name | String(200) | "Chief Executive Agent" |
| description | Text | Role responsibilities |
| capabilities | ARRAY(Text) | ["planning", "delegation", "decision_making"] |
| system_prompt | Text | Role-specific LLM prompt |
| llm_provider | String(64) | "kimi", "ollama", "gemini" |
| llm_model | String(128) | "kimi-k2.5", "qwen3.5:9b" |
| delegation_rules | JSONB | When/what to delegate |
| is_active | Boolean | |
| created_at | DateTime(tz) | |

**`agent_tasks`** — Tasks executed by agent roles
| Column | Type | Notes |
|--------|------|-------|
| id | String(64) PK | UUID |
| project_id | String(64) | Links to projects if applicable |
| title | String(500) | |
| description | Text | |
| task_type | String(32) | research, analysis, validation, implementation, ideation |
| assigned_role | String(64) FK | → agent_roles.id |
| status | String(20) | pending, in_progress, completed, failed, delegated |
| priority | Integer | 1-5 |
| dependencies | ARRAY(String) | Other agent_task IDs |
| context | JSONB | Input data |
| result | JSONB | Output data |
| parent_task_id | String(64) | For delegation chains |
| cost_usd | Float | LLM cost tracking |
| created_at, started_at, completed_at | DateTime(tz) | |

### Default 5 roles (seeded in migration)

| Role | Primary LLM | Execution LLM | Cost | Purpose |
|------|------------|---------------|------|---------|
| **CEO** | kimi/kimi-k2.5 | — (always Kimi) | $0.60/$2.50/1M | Strategic planning, delegation, final synthesis |
| **Researcher** | kimi/kimi-k2.5 (plan) | ollama/gemma4:26b (execute) | Mixed | Plan research queries with Kimi, execute searches + summarize with Gemma |
| **Analyst** | ollama/gemma4:26b | — | FREE | Data analysis, scoring, market sizing (structured prompts from CEO) |
| **Engineer** | ollama/gemma4:e4b | — | FREE | Implementation, code generation (lighter model, faster) |
| **Validator** | ollama/gemma4:26b | — | FREE | Assumption testing using structured rubrics from CEO |

**Why this works**: The CEO (Kimi K2.5) generates highly structured task descriptions with explicit:
- Input data (pre-gathered context)
- Expected output JSON schema
- Evaluation criteria / rubric
- Step-by-step instructions

This "structured handoff" pattern means Gemma 4 doesn't need to reason about *what* to do — it just executes well-defined instructions. Quality stays high because the *planning* intelligence comes from Kimi.

**When Gemma isn't enough**: For council debates (Phase 5), we intentionally use different providers per role (Kimi, Gemma, Gemini) to get genuine diversity of reasoning. The CEO always uses Kimi for final synthesis/decisions.

**Gemma 4 model selection**:
- `gemma4:26b` (17GB) — Default for Analyst, Researcher execution, Validator. Best quality-to-size ratio.
- `gemma4:e4b` (9.6GB) — Engineer tasks (code gen). Lighter/faster, good enough for structured code.
- `gemma4:31b` (19GB) — Available as upgrade if 26b quality insufficient for specific tasks.
- `gemma4:e2b` (7.2GB) — Fallback if VRAM pressure from other models.

### Agent execution pattern: Kimi-plans-Gemma-executes

Two-tier execution using Zero's existing `plan_then_execute` from `unified_llm_client.py`:

**Tier 1 — Planning (Kimi K2.5, paid)**:
1. CEO receives high-level task
2. Kimi decomposes into subtasks with structured prompts for each
3. Each subtask prompt includes: input context, output schema, rubric, max tokens

**Tier 2 — Execution (Gemma 4, free)**:
4. Subtasks dispatched to role agents running Gemma 4
5. Gemma executes structured prompt, returns JSON
6. Results collected back to CEO for synthesis (Kimi)

**Quality guard**: If a Gemma response fails JSON parsing or scores below confidence threshold, auto-retry once. If still bad, escalate that specific subtask to Kimi (fallback). This keeps costs low while maintaining quality floor.

Cost per typical workflow:
- CEO planning call (Kimi): ~$0.01-0.03
- 3-5 execution calls (Gemma): FREE
- CEO synthesis call (Kimi): ~$0.01-0.02
- **Total: ~$0.02-0.05** vs $0.15-0.30 if all-Kimi

### API endpoints (router: `/api/company`)
- `GET /api/company/roles` — List agent roles
- `GET /api/company/tasks` — List agent tasks (filter by status, role, type)
- `POST /api/company/tasks` — Create task (manual or from other services)
- `POST /api/company/tasks/{id}/execute` — Execute task with assigned role
- `GET /api/company/tasks/{id}` — Task detail with result
- `GET /api/company/stats` — Dashboard stats (tasks by status/role, cost totals)

### Orchestration integration
Add to [orchestration_graph.py](backend/app/services/orchestration_graph.py):
- New route `"ai_company"` in `VALID_ROUTES`
- Keywords: `["agent task", "company", "ai company", "agent status", "role"]`
- New `ai_company_node` that lists tasks, stats, or creates new tasks from natural language

---

## Phase 2: Deep Research System

### New files
- `backend/app/services/deep_research_service.py` — LangGraph research pipeline
- `backend/app/routers/deep_research.py` — REST API
- `mcp_servers/semantic_scholar_mcp.py` — Academic paper search (optional, free API)

### Architecture (STORM-inspired + GPT-Researcher pattern)

LangGraph StateGraph with 5 nodes:

```
START → generate_outline (CEO)
      → parallel_research (Researcher x3 perspectives)
      → synthesize_sections (Researcher)
      → validate_claims (Validator)
      → final_assembly (CEO) → END
```

**State**: query, perspectives[], outline{}, sources[], sections{}, report_markdown, cost_usd

**Node details**:
1. **generate_outline** — CEO breaks query into 3-5 research questions + identifies 3 perspectives (technical, business, competitive)
2. **parallel_research** — Researcher agent runs SearXNG queries for each perspective (reuses existing `searxng_service`), collects sources
3. **synthesize_sections** — Researcher combines findings per section, with inline citations
4. **validate_claims** — Validator agent spot-checks key claims, flags unsupported assertions
5. **final_assembly** — CEO writes executive summary, assembles full markdown report

**Storage**: Reports saved in `research_findings` table (existing) with `category="deep_research"`. Full markdown stored in JSONB `details` field.

**Cost budget**: Max $0.30 per deep research report (configurable). Kimi K2.5 for outline generation + final assembly (2 calls ~$0.04), Gemma 4:26b for all research execution + synthesis + validation (FREE). Only the CEO planning/synthesis touches Kimi.

### API endpoints (router: `/api/research/deep`)
- `POST /api/research/deep` — Start deep research (async, returns job ID)
- `GET /api/research/deep/{id}` — Get research status + report
- `GET /api/research/deep` — List past research reports
- `GET /api/research/deep/{id}/report` — Download markdown report

### Orchestration integration
Add route `"deep_research"` — Keywords: `["deep research", "comprehensive research", "research report", "investigate"]`

---

## Phase 3: Experiment Runner

### New files
- `backend/app/models/experiment.py` — Pydantic models
- `backend/app/services/experiment_service.py` — Experiment lifecycle
- `backend/app/routers/experiments.py` — REST API

### Database table (in migration 015)

**`experiments`**
| Column | Type | Notes |
|--------|------|-------|
| id | String(64) PK | UUID |
| title | String(500) | |
| hypothesis | Text | What we're testing |
| methodology | Text | How we test it |
| experiment_type | String(32) | benchmark, validation, ab_test, prototype |
| status | String(20) | designed, running, completed, failed |
| parameters | JSONB | Config/inputs |
| metrics | JSONB | What we measure |
| results | JSONB | Outcomes |
| conclusion | Text | AI-generated conclusion |
| linked_idea_id | String(64) | FK to money ideas |
| linked_research_id | String(64) | FK to research findings |
| created_by_role | String(64) | Which agent designed it |
| cost_usd | Float | |
| created_at, started_at, completed_at | DateTime(tz) | |

### Experiment types
1. **Benchmark** — Compare LLM models, prompt strategies, or approaches. Engineer runs trials, Analyst scores.
2. **Validation** — Test business assumptions (market size, demand, feasibility). Researcher gathers data, Validator checks.
3. **A/B Test** — Compare two content strategies, pricing models, etc. Analyst designs test, tracks metrics.
4. **Prototype** — Engineer builds minimal version, Validator reviews, Analyst measures.

### Experiment flow
```
Design (CEO) → Review (Validator) → Execute (Engineer/Researcher) → Analyze (Analyst) → Conclude (CEO)
```

Each step creates an `agent_task` — full audit trail.

### API endpoints (router: `/api/experiments`)
- `POST /api/experiments` — Design experiment from hypothesis
- `POST /api/experiments/{id}/run` — Start execution
- `GET /api/experiments` — List experiments (filter by status, type)
- `GET /api/experiments/{id}` — Detail with results

---

## Phase 4: Enhanced Idea Pipeline

### Modified files
- `backend/app/services/money_maker_service.py` — Add `deep_validate_idea()` method
- `backend/app/services/market_analysis_service.py` — NEW: TAM/SAM/SOM calculations

### Deep validation flow (extends existing money_maker)
When an idea scores > 60 in basic scoring, trigger deep validation:

1. **Researcher** — Deep market research via SearXNG (competitors, market size data, trends)
2. **Validator** — 5-assumption check (Desirability, Viability, Feasibility, Usability, Ethical)
3. **Analyst** — TAM/SAM/SOM calculation, SWOT analysis, financial projections
4. **CEO** — Final synthesis: Go/No-Go recommendation with confidence score

Results stored in existing `money_ideas` table's JSONB `research_data` field (already exists).

### New: Idea generation improvement
- Researcher agent feeds trending topics + research findings into idea generation prompt
- Cross-pollination: TikTok Shop trends + research findings + market data → novel ideas
- Analyst scores ideas with structured rubric (not just LLM vibes)

### Market analysis service
New `MarketAnalysisService` with methods:
- `calculate_tam_sam_som(idea, research_data)` — Uses Analyst role
- `generate_swot(idea, competitor_data)` — Uses Analyst role
- `financial_projection(idea, assumptions)` — Uses Analyst role

---

## Phase 5: Council of Agents

### New files
- `backend/app/services/council_service.py` — Multi-agent debate + voting
- `backend/app/routers/council.py` — REST API

### Database table (in migration 015)

**`council_decisions`**
| Column | Type | Notes |
|--------|------|-------|
| id | String(64) PK | UUID |
| topic | String(500) | Decision topic |
| context | JSONB | Relevant data |
| proposer_role | String(64) | Who proposed |
| rounds | JSONB | Array of debate rounds |
| votes | JSONB | {role: {position, reasoning, confidence}} |
| decision | String(20) | approved, rejected, needs_revision, null |
| confidence_score | Float | 0-100, average of voter confidences |
| created_at, decided_at | DateTime(tz) | |

### Council protocol (2-round debate, proven optimal)

**Round 1 — Independent positions**: Each voting role independently evaluates the topic. Intentionally uses different LLM providers for genuine reasoning diversity:
- CEO: kimi/kimi-k2.5 (strategic lens)
- Researcher: ollama/gemma4:26b (technical/data lens)
- Analyst: ollama/gemma4:26b (financial/market lens)
- Validator: gemini/gemini-3.1-pro-preview (risk/feasibility lens — different model family = different blind spots)

**Round 2 — Informed revision**: Each role sees Round 1 positions and can revise. This simulates debate without infinite loops.

**Final vote**: Each role casts approve/reject/revise with confidence score. Decision = majority vote. Confidence = weighted average.

**Cost**: ~$0.05 per decision (1 Kimi call ~$0.03, 1 Gemini call ~$0.02, 2 Gemma calls FREE). Much cheaper than all-paid approach while maintaining diversity.

### When council is triggered
- Idea validation score > 80 (high potential, worth investing time)
- Experiment results are ambiguous (need interpretation)
- Research findings suggest major strategic pivot
- Manual trigger via API or chat

### API endpoints (router: `/api/council`)
- `POST /api/council/decisions` — Propose topic for council
- `POST /api/council/decisions/{id}/vote` — Execute voting rounds
- `GET /api/council/decisions` — List decisions
- `GET /api/council/decisions/{id}` — Detail with full debate transcript

---

## Phase 6: Frontend UI

### New pages
- `frontend/src/pages/AiCompanyPage.tsx` — Dashboard: active tasks, experiments, decisions, cost tracker
- `frontend/src/pages/DeepResearchPage.tsx` — Start research, view reports (markdown rendered)
- `frontend/src/pages/ExperimentLabPage.tsx` — Design/run/view experiments
- `frontend/src/pages/CouncilRoomPage.tsx` — Proposals, debate transcripts, voting results

### New hooks
- `frontend/src/hooks/useAgentCompanyApi.ts` — CRUD for roles/tasks
- `frontend/src/hooks/useDeepResearchApi.ts` — Research operations
- `frontend/src/hooks/useExperimentApi.ts` — Experiment CRUD
- `frontend/src/hooks/useCouncilApi.ts` — Council operations

### Sidebar addition
Add "AI Company" section in [AppSidebar.tsx](frontend/src/components/layout/AppSidebar.tsx) with sub-items: Dashboard, Deep Research, Experiment Lab, Council Room

### Patterns to follow
- React Query with key factory pattern (existing pattern in all hooks)
- shadcn/ui components, TailwindCSS dark theme (bg-gray-900, indigo accent)
- Zustand for any global state if needed

---

## Phase 7: Scheduler Integration & Orchestration Wiring

### New scheduler jobs
Add to [scheduler_service.py](backend/app/services/scheduler_service.py):

| Job | Schedule | Description |
|-----|----------|-------------|
| `continuous_deep_research` | Every 6 hours | Researcher picks top priority research topic, runs deep research |
| `idea_deep_validation` | Every 4 hours | Validates top-scoring unvalidated ideas from money_maker |
| `daily_council_review` | Daily 9 AM | CEO proposes strategic decisions based on overnight findings |
| `experiment_monitor` | Every 2 hours | Check running experiments, flag stale ones |

### Orchestration graph additions
4 new routes in [orchestration_graph.py](backend/app/services/orchestration_graph.py):
- `ai_company` — Agent tasks, role status, company dashboard
- `deep_research` — Start/view deep research
- `experiment` — Design/run/view experiments
- `council` — Propose/view council decisions

---

## Cost Optimization Strategy: Kimi Plans, Gemma Executes

| Activity | Est. Cost | Breakdown |
|----------|-----------|-----------|
| Deep research report | ~$0.05 | Kimi: outline + synthesis ($0.04). Gemma: research + validation (FREE) |
| Council decision | ~$0.05 | Kimi CEO ($0.03) + Gemini Validator ($0.02) + Gemma x2 (FREE) |
| Idea deep validation | ~$0.03 | Kimi CEO plan ($0.02) + Gemma Analyst/Validator/Researcher (FREE) + Kimi synthesis ($0.01) |
| Experiment design+run | ~$0.04 | Kimi CEO design ($0.03) + Gemma Engineer/Analyst (FREE) + Kimi conclusion ($0.01) |
| Daily budget cap | $5.00 | Inherited from existing LLM router — with Gemma this goes much further |

**Estimated daily cost at full autonomy** (6 research reports + 5 validations + 2 experiments + 1 council): **~$0.60/day** vs ~$4.50/day without Gemma.

**Fallback chain**:
1. Kimi K2.5 (planning/synthesis) → Gemma 4:26b (execution) — default
2. If Kimi budget exhausted → Gemma 4:31b for planning (larger model, still free, slightly lower quality)
3. If VRAM pressure → Gemma 4:e4b for execution (lighter, faster)
4. System never stops — worst case is all-Gemma which is free

**Quality guardrail**: CEO (Kimi) always reviews final outputs. If Gemma produces a response that fails JSON parsing or is flagged as low-confidence by the CEO's review prompt, that subtask is re-run with Kimi. Expected escalation rate: <5% of subtasks.

---

## Implementation Order

1. **Phase 1** (Agent Roles) — Foundation everything else builds on
2. **Phase 2** (Deep Research) — Highest standalone value
3. **Phase 4** (Idea Pipeline) — Enhances existing money_maker
4. **Phase 3** (Experiments) — Needs roles + research working
5. **Phase 5** (Council) — Needs all roles active to vote
6. **Phase 6** (Frontend) — Can start after Phase 1-2, iterate as backend grows
7. **Phase 7** (Scheduler) — Final polish, automation

---

## Verification Plan

After each phase:
1. **Backend**: `docker compose -f docker-compose.sprint.yml build --no-cache zero-api && docker compose -f docker-compose.sprint.yml up -d zero-api`
2. **API test**: Hit endpoints with `curl` or via MCP tools to verify responses
3. **Frontend**: Verify pages load at `http://localhost:5173`
4. **Orchestration**: Test via Discord bot or orchestrator API — verify new routes classify correctly
5. **Cost tracking**: Check `llm_usage` table to verify per-role cost recording
6. **End-to-end**: Trigger deep research via chat → verify report generated → verify stored in DB → verify viewable in UI
