# Reachy → World-Class Second-Brain Companion for Adam @ ADA AI

## Context

Adam runs **ADA AI LLC**, a brand-new software company, and owns a Reachy
Mini robot driven by Zero. He wants Reachy to become his always-on second
brain: natural conversation, daily reports, multi-Gmail and Google Calendar
management, end-to-end help running ADA AI (ops, bookkeeping, taxes,
product), continuous learning, and the ability to act as an agent that
orchestrates other agents. He has tried Pollen Robotics' Windows app, the
upstream `reachy_mini_conversation_app` ("ask"), and other surfaces — all
"barely working." Local LLM is **Qwen3.6-35B-A3B abliterated (Q4_K_M MoE)**
served by llama.cpp on `host.docker.internal:18800` (the user's "qwen 3.6
variant"), exposed through shared LiteLLM as `qwen3-chat`.

Autonomy preference: **draft + ask before sending** (recommended). Daily
report lands in **Zero web UI dashboard** AND is **emailed to Adam**.

This document is the durable plan. Each phase is independently shippable
and the file is meant to be edited as we iterate — nothing here is "set
and forget."

---

## What's already built (massive head start)

Zero is not a green field. The Reachy stack already includes 50+ services
and routers. The job is to **unify, fix the realtime spine, plug in
modern OSS where we're rebuilding the wheel, and finish the loop** —
not start over.

### Voice / realtime
- `backend/app/routers/reachy_realtime.py` — config + WS bridge
- `backend/app/services/reachy_realtime/` — `local_handler.py`,
  `gemini_handler.py`, `openai_handler.py`, `session.py`, `tools.py`,
  `bg_tool_manager.py`, `profiles.py`, `head_wobbler.py`, `sway.py`
- `backend/app/routers/reachy_intent.py` — keyword + LLM intent classifier
  (record / calendar / email / company / robot wake-sleep / focus / ambient)
- `host_agent/` — daemon supervisor, watchdog, Docker readiness probe,
  audio capture, wake loops (whisper + openwakeword)
- `reachy_app/reachy_mini_zero/main.py` — Reachy Mini desktop app shim
  (chunked 5 s recording → POST `/api/reachy/voice`)

### Brain / memory
- `app/services/zero_brain_service.py` — central hub (episodic memory +
  outcome learning + prompt evolution + benchmarks + reflection)
- `app/services/episodic_memory_service.py`, `memory_service.py`,
  `reachy_user_memory_service.py`, `reachy_memory_blocks.py`
- `app/services/reachy_context_service.py`, `reachy_persona_state.py`,
  `reachy_personality_synthesis_service.py`,
  `reachy_persona_intros_service.py`, `reachy_personas.py`

### Company / agent-of-agents
- `app/services/agent_company_service.py` — role + task DB-backed
  orchestration (Kimi-plans-Gemma-executes pattern) — already keys on
  **"ADA AI LLC"** as legal company fact
- `company_context_service.py`, `company_dashboard_review_service.py`,
  `company_operator_service.py`, `company_work_item_service.py`,
  `llc_guidance_service.py`
- `routers/company_operator.py`, `company_work_items.py`,
  `agent_company.py`, `agent_approvals.py`, `llc_guidance.py`,
  `orchestrator.py`, `council.py`, `engine.py`, `loops.py`, `employee.py`

### Email / calendar
- `routers/email.py`, `email_drafts.py`, `reachy_email.py`
- `services/email_automation_service.py`, `email_classifier.py`,
  `email_draft_service.py`, `email_qa_service.py`, `email_rule_service.py`,
  `email_voice_session_service.py`
- `routers/calendar.py`, `meetings.py`, `meeting_*` (chat, preferences,
  recordings, search, speakers, summaries, transcriptions, ws)
- `routers/google_oauth.py`, `oauth_accounts.py`

### Companion policy / mode
- `services/reachy_companion_service.py` — modes (ambient/focus/meeting/
  privacy), allowed actions, proactive event budget, skill registry

---

## Diagnosis: why it feels "barely working"

Reading the actual code (not assumptions):

1. **Realtime path is browser-first, not robot-first.**
   `local_handler.py` expects 16 kHz PCM16 from the browser mic with
   webrtcvad barge-in. The Reachy Mini app (`reachy_mini_zero/main.py`)
   does **5 s chunked POST** to `/api/reachy/voice` — no streaming, no
   barge-in, no partials. This is the architectural gap that makes
   conversation through the robot feel laggy and turn-bashed.

2. **Local LLM first-token latency is a known choke point.**
   `LLM_FIRST_TOKEN_TIMEOUT_S = LLM_TURN_TIMEOUT_S (20s)`,
   `LLM_MAX_TOKENS = 100`. The Qwen3.6-35B-A3B MoE on Q4_K_M via
   llama.cpp is good throughput but TTFT is variable; with the current
   sentence-split TTS the user hears nothing until the first sentence
   ends. There's no speculative or draft-model setup, no warm cache
   priming, and no streaming-aware system prompt that forces short
   first sentences.

3. **STT is fragile on Reachy USB speakerphone.**
   Comments in `local_handler.py` (2026-05-08) describe Whisper
   `base.en` hallucinating "Thanks for watching" outros; recently
   switched to `small.en` plus manual RMS gain — still not robust.
   No keyword/biasing, no two-pass (fast preview → confirmed),
   no echo cancellation beyond `OUTPUT_ECHO_GUARD_S=0.35`.

4. **Memory is fragmented.** Five overlapping memory services
   (`memory_service`, `episodic_memory_service`,
   `reachy_user_memory_service`, `reachy_memory_blocks`,
   `reachy_context_service`). No single retrieval contract feeding
   the realtime turn. Voice replies don't get RAG over Adam's actual
   data (emails, calendar, company state, prior conversations).

5. **Agent-of-agents exists but isn't wired to the voice surface.**
   `agent_company_service` runs role-based tasks in the DB; the
   realtime tool registry (`reachy_realtime/tools.py`) only exposes
   motion verbs (`move_head`, etc.). Reachy can't currently say
   "spawn a researcher to compare CPA quotes and get back to me."

6. **No daily report pipeline.** Plenty of company/email/calendar
   readers, but nothing that runs at 7 a.m., composes a brief, posts
   to the dashboard, and emails it.

7. **Persona/voice quality.** Piper is fine for fallback but isn't
   2026-class. No expressive prosody, no voice cloning, no
   speech-in/speech-out unified model option. Robotic timbre
   undercuts the "companion" feel.

8. **No closed learning loop on conversation outcomes.** `zero_brain`
   has the scaffolding (outcome learning, prompt evolution,
   reflection) but the realtime turn doesn't write structured
   outcomes back, so the assistant doesn't actually get better.

---

## Open-source landscape (May 2026) — annotated shortlist

I'm scoping to components that can plug into FastAPI + React + llama.cpp +
Reachy Mini SDK without ripping anything out. Stars/dates are approximate;
verify before vendoring.

### Realtime voice spine (highest leverage)

- **Pipecat** — `pipecat-ai/pipecat`. Apache-2.0. Pipeline framework
  purpose-built for voice agents: VAD, STT, LLM, TTS as composable
  frames; first-class barge-in; supports local (Whisper, Piper) and
  cloud. Battle-tested by Daily.co. **Recommended as the unifying
  spine for both browser-mic and Reachy-mic surfaces.** Replaces our
  hand-rolled `local_handler.py` orchestration; we keep our tool
  registry and persona layer on top.
- **LiveKit Agents** — `livekit/agents`. Apache-2.0. Strong WebRTC
  story, native barge-in, growing plug-in catalog. Good alternative
  if we standardize on LiveKit transport for the Reachy Mini app.
- **Moshi** (Kyutai) — `kyutai-labs/moshi`. Full-duplex speech LLM,
  ~200 ms perceived latency. **Promising "stretch" experiment** for
  the most natural conversation, but smaller than Qwen and English-
  centric; treat as a side surface, not the brain.
- **Ultravox** (Fixie) — `fixie-ai/ultravox`. Speech-in/text-out
  multimodal LLM (skips STT entirely). Possible accelerator if we
  want lower TTFT and aren't willing to swap to Moshi.
- **Sesame CSM 1.5** — high-quality conversational TTS released
  late 2025/early 2026 with strong "warm" voice. Worth a side-by-
  side against Piper + Kokoro for the companion voice.
- **Faster-Whisper** + **distil-whisper-large-v3.5** — keep faster-
  whisper as runtime, switch model to distilled large-v3.5 for
  better robustness on noisy speakerphone audio (still real-time
  on RTX 5090). Beats `small.en`.
- **Silero VAD v5** — replaces webrtcvad for cleaner barge-in on
  the speakerphone. Adds ~80 MB but Pipecat already ships with it.
- **OpenWakeWord** — already in repo; keep it but train a custom
  "Reachy / Hey Adam" model for higher precision.
- **Kokoro-TTS 1.x** — small, fast, very natural local TTS. Good
  upgrade path from Piper for the assistant voice.

### Memory / second-brain

- **mem0** — `mem0ai/mem0`. Apache-2.0. Auto-extracts facts from
  conversation, stores in vector + graph, returns scoped recall.
  **Recommended as the unified memory contract** that all five
  current memory services compose into.
- **Zep** — `getzep/zep`. Apache-2.0. Temporal knowledge graph,
  great for "what did Adam say about CPAs last week." Could replace
  or back mem0; pick one to avoid duplication.
- **Cognee** — knowledge-graph-first memory. More complex setup;
  consider only if mem0/Zep aren't enough.
- **Letta** (formerly MemGPT) — full agent-memory framework with
  long-term context paging. Heavyweight; cherry-pick patterns
  rather than adopt whole.

### Agent-of-agents

- **LangGraph** — `langchain-ai/langgraph`. MIT. State-machine
  multi-agent orchestration, mature, observable, persistent. Best
  fit for "Reachy as supervisor that spawns researchers, drafters,
  schedulers." **Recommended.**
- **OpenAI Agents SDK** / **Anthropic Agent SDK** — simpler loops;
  good for individual sub-agents, not the supervisor graph.
- **CrewAI** — role-based; conceptually overlaps with our existing
  `agent_company_service`. Take its planner ideas, don't replace.
- **smolagents** (HF) — minimal, code-first; good for one-off tools.

### Email / calendar reference projects

- **Composio** — agent-friendly tool library with strong Gmail/
  Calendar/Drive integrations and built-in OAuth multi-account
  handling. **Recommended for connector layer.**
- **Activepieces** / **n8n** — pattern reference for trigger →
  draft → human-approval flows.
- **karakeep** / **Khoj** — personal-AI inbox patterns.
- Pollen Robotics' upstream `reachy_mini_conversation_app` — keep
  mirroring tool schemas; that compatibility is already explicit
  in `tools.py`.

### Bookkeeping / company OS for ADA AI

- **Beancount** + **Fava** — plain-text accounting. Pairs naturally
  with an LLM that drafts journal entries from receipts/invoices.
- **Maybe Finance** (open-sourced) — modern personal+small-biz
  finance UI; pattern reference for the dashboard.
- **Mercury / Stripe / Brex APIs** — ingestion only; no OSS, but
  worth a connector each.

### Pollen ecosystem updates to track
- `pollen-robotics/reachy_mini_conversation_app` — keep tool
  registry parity (already done).
- `pollen-robotics/reachy-mini-app-template` — confirm our
  `reachy_app/reachy_mini_zero` still matches the latest template
  (the SDK changed media APIs in 2026 Q1 — comments in our shim
  reference this).

### Top 7 to adopt now (impact-ranked)

1. **Pipecat** — unify the realtime spine, kill the bespoke pipeline.
2. **Silero VAD v5 + distil-whisper-large-v3.5 + Kokoro-TTS** —
   speakerphone-grade STT + natural voice in one upgrade pass.
3. **mem0** — single memory contract for the whole assistant.
4. **LangGraph** — supervisor over `agent_company_service`.
5. **Composio Gmail/Calendar connectors** — multi-account OAuth + tools.
6. **Beancount + Fava** — bookkeeping spine for ADA AI.
7. **Sesame CSM** (experiment lane) — premium voice option for the
   companion persona; A/B against Kokoro.

---

## Target architecture

```
                 ┌──────────────────────────────────────────────┐
                 │  Reachy Mini (mic + speaker + motors)        │
                 │  reachy_app/reachy_mini_zero  ←── upgrade ──┐│
                 └──────────────────────────────────────────────┘
                                │  PCM stream (LiveKit/WebRTC)   │
                                ▼
       ┌─────────────────────────────────────────────────────────┐
       │  Pipecat realtime pipeline                              │
       │   SileroVAD → distil-whisper → Supervisor LLM → Kokoro  │
       │              ↑          ↓ tool calls                    │
       │   Memory recall (mem0) ─┘                               │
       └─────────────────────────────────────────────────────────┘
                                │
                                ▼
       ┌─────────────────────────────────────────────────────────┐
       │  LangGraph Supervisor                                    │
       │   ├─ Email agent       (Composio Gmail x N accounts)    │
       │   ├─ Calendar agent    (Composio Calendar)              │
       │   ├─ Company-Ops agent (existing agent_company_service) │
       │   ├─ Bookkeeper agent  (Beancount/Fava + bank ingest)   │
       │   ├─ Researcher agent  (deep_research existing)         │
       │   ├─ Daily-Brief agent (cron 7 a.m.)                    │
       │   └─ Zero-Brain agent  (reflection, prompt evolution)   │
       └─────────────────────────────────────────────────────────┘
                                │
                                ▼
       ┌─────────────────────────────────────────────────────────┐
       │  mem0 unified memory  (events / facts / decisions)       │
       │  + existing episodic_memory + reachy_user_memory bridges │
       └─────────────────────────────────────────────────────────┘
```

Three invariants:

- **Single supervisor** is the only thing the voice loop talks to.
  The supervisor decides whether to answer directly or fan out to
  sub-agents. This is the "agent that manages other AI agents."
- **One memory contract.** Every sub-agent reads/writes through the
  same mem0 facade so context grows monotonically.
- **Approval gates** are first-class on every outbound action
  (send email, accept meeting, file form). Default per Adam:
  draft + ask. Surfaced in the dashboard AND spoken back through
  Reachy ("I drafted a reply to the CPA — say 'send it' or 'change
  it'").

---

## Phased roadmap

Each phase is ~1–2 weeks of work and ships independently. Order is
chosen so latency wins land first (Adam can feel the change), then
intelligence wins, then breadth.

### Phase 1 — Realtime spine upgrade (latency + naturalness)

**Goal:** Reachy answers in <1.5 s perceived latency, no
hallucinated transcripts, barge-in works through the robot.

Touch list:
- `backend/app/services/reachy_realtime/local_handler.py` — replace
  hand-rolled VAD/STT/TTS glue with a Pipecat pipeline; keep our
  Handler protocol so `session.py` is unchanged.
- `backend/requirements.txt` — add `pipecat-ai[silero,whisper,kokoro]`,
  `mem0ai`, `langgraph`.
- Switch STT to `distil-whisper-large-v3.5` via faster-whisper.
  Update `STT_MODEL_NAME` default; keep env override.
- Add **two-pass STT**: emit `transcript.partial` from a 200 ms
  streaming pass for UI feedback; commit only the confirmed pass
  to LLM input.
- Swap default TTS to **Kokoro-TTS**. Keep Piper as fallback.
  Files: `app/services/audio_service.py` or wherever `TTSService`
  lives — locate and add a Kokoro backend.
- System-prompt nudge: instruct the model to start replies with a
  short first sentence (so TTS has something to speak inside 500 ms).
  Update `app/services/reachy_realtime/profiles.py` instructions.
- llama.cpp serving: enable speculative decoding with a 1.5B draft
  (e.g., Qwen3-1.7B) where available. Document in
  `shared-infra/litellm/config.yaml`.
- **Reachy Mini app rewrite:** replace `reachy_app/reachy_mini_zero/main.py`
  chunk-and-POST with a streaming WebRTC client (LiveKit or raw WS)
  that ships PCM frames continuously; play TTS PCM frames as they
  arrive. This is the single biggest UX delta.

Verification: in-room conversation, time-to-first-audio under 1.5 s on
warm cache; barge-in cancels speech within 250 ms; no "Thanks for
watching" hallucinations after 30 minutes of ambient room noise.

### Phase 2 — Unified memory (mem0)

**Goal:** Reachy remembers what Adam said yesterday, last week,
across channels, and brings it into the next turn.

Touch list:
- New `backend/app/services/memory_facade.py` — single `recall()` /
  `remember()` API, backed by mem0, with adapters that read existing
  `episodic_memory_service`, `reachy_user_memory_service`,
  `reachy_memory_blocks` so old data is included.
- Wire `local_handler.py` (and `openai_handler.py`,
  `gemini_handler.py`) to call `memory_facade.recall(user_text,
  k=8)` and inject as system context block before each LLM turn.
- Wire post-turn write: extract atomic facts from
  `(user_text, assistant_reply)` via mem0's auto-extractor, scoped
  by speaker (Adam vs guest via `voiceprints` router).
- Migration: backfill from `episodic_memory` table into mem0 store
  on first boot, idempotent.

Verification: ask Reachy "what did I tell you about my CPA last
week," it cites a specific prior turn. Restart container — context
survives.

### Phase 3 — LangGraph supervisor + tool surface

**Goal:** Reachy can spawn a researcher / drafter / scheduler and
report results without losing the conversation.

Touch list:
- New `backend/app/services/supervisor_graph.py` — LangGraph state
  machine: nodes for `classify`, `direct_reply`, `dispatch_subagent`,
  `await_subagent`, `summarize_for_voice`. Persistent checkpoint via
  Postgres (existing infra).
- Sub-agent adapters (thin wrappers — most logic exists already):
  - `email_agent_adapter` → `email_automation_service`,
    `email_draft_service`
  - `calendar_agent_adapter` → `calendar_service`,
    `meeting_preferences`
  - `company_ops_adapter` → `agent_company_service`,
    `company_operator_service`, `llc_guidance_service`
  - `researcher_adapter` → `routers/deep_research.py`,
    `autonomous_research.py`
  - `bookkeeper_adapter` → new (Phase 5)
- Expose supervisor tools to the realtime loop via
  `reachy_realtime/tools.py`: add `delegate_research`,
  `draft_email`, `propose_meeting`, `company_status`,
  `bookkeeping_query`.
- Replace `reachy_intent.py` keyword routing with an LLM-first
  classifier that returns `{intent, args, confidence}` and falls
  through to keyword regex only on low confidence.

Verification: voice command "research three CPAs in Duval County
that handle Florida LLCs and draft an email to my top pick" →
researcher runs, drafter composes, supervisor speaks "I have a
draft from Smith CPA — say 'show it' or 'send it'."

### Phase 4 — Email + Calendar deep integration (multi-Gmail)

**Goal:** Manage Adam's multiple Gmail accounts and Google Calendar
end-to-end with draft-and-confirm gates.

Touch list:
- `backend/app/routers/google_oauth.py` + `oauth_accounts.py` —
  confirm multi-account token storage; if missing, add an
  `account_id` foreign key throughout email/calendar services.
- Adopt **Composio** Gmail + Calendar tools (or library code from
  it) for: list/search/label messages, draft, schedule send,
  list/create/update/respond events, find free slots.
- `email_automation_service` — extend with **per-account triage
  rules** and a **draft pool** keyed by `(account_id, thread_id)`.
- New `services/digest_email_service.py` — composes the daily
  brief email; uses existing brain + memory facade.
- Frontend: a `DraftsInbox` panel that shows pending Reachy drafts
  with one-click "send / edit / discard."

Verification: spoken "draft a reply to the latest CPA quote on my
work account asking about the W-2 vs 1099 split for ADA AI" — a
draft appears in the Drafts panel scoped to the right account; on
"send it" it goes via Gmail API.

### Phase 5 — ADA AI company operations

**Goal:** Reachy is a useful chief-of-staff for ADA AI: ops,
bookkeeping, taxes, product.

Touch list:
- `services/llc_guidance_service.py` — fill out checklists for
  Florida LLC (Sunbiz annual report, EIN reminders, Duval County
  business tax, sales tax registration if applicable). Already
  scaffolded; finish the data.
- New `services/bookkeeper_service.py` — wrap **Beancount** as a
  subprocess; parse bank-export CSVs (Mercury/Chase) into
  draft journal entries; surface mismatches.
- Tax dossier: monthly P&L, quarterly estimated tax reminder,
  receipt capture (vision pipeline already exists in
  `routers/sight.py` / `vision.py`) → categorized expense.
- Product layer: ADA AI's first software product gets its own
  project in `routers/projects.py`; supervisor can field questions
  about roadmap, blockers, customers.
- Approvals: anything with money or filing routes through
  `routers/agent_approvals.py` with phone/UI confirmation.

Verification: "what's my Q2 estimated tax look like and is the
Sunbiz annual report filed?" returns a real number and a real
status pulled from Beancount + the LLC tracker.

### Phase 6 — Daily report

**Goal:** A spoken+written brief lands every morning in the Zero
dashboard and Adam's inbox.

Touch list:
- New `services/daily_brief_service.py` — composes the report from
  inputs:
  - Top 5 unread / starred emails per account
  - Today's calendar with conflicts and prep notes
  - ADA AI status (open work items, blockers, finance ticker)
  - Yesterday's wins/learnings (from `zero_brain` reflection)
  - "What I would work on first" recommendation
- New cron job in the existing scheduler (find under `routers/loops.py`
  or APScheduler in `backend/app/main.py`); runs at 7:00 local.
- Dashboard component `frontend/src/.../DailyBrief.tsx` (find the
  exec dashboard; existing screenshots `exec-dashboard-*.png`
  suggest there is one) renders the report and exposes "speak it"
  button → realtime TTS through Reachy.
- `digest_email_service` (Phase 4) reused to send the same content
  by email.

Verification: at 7:00 the next morning the brief appears in the
dashboard and the inbox; pressing "speak it" plays it through
Reachy with natural cadence.

### Phase 7 — Closed-loop learning

**Goal:** Reachy gets measurably better week over week.

Touch list:
- After every realtime turn, write an `OutcomeRecord` with:
  intent, latency, tool calls used, user satisfaction signal
  (explicit thumbs OR implicit follow-up reformulation rate).
  Files: `app/services/outcome_learning_service.py` (exists),
  `local_handler.py` (call site).
- Weekly reflection job runs `reflection_service` over the last
  N outcomes, proposes `PromptVariant` changes, and A/B tests them
  via `prompt_evolution_service` (all exist).
- Surface the trend in the dashboard alongside the daily brief.
- New `zero_brain.report()` MCP tool the supervisor can call to
  fetch its own performance for self-reflection.

Verification: after a week, `zero_brain.get_status()` shows
non-flat scores across dimensions and at least one prompt variant
promoted from A/B.

### Phase 8 (stretch) — Premium voice + presence

- Sesame CSM voice option behind a feature flag; A/B Kokoro vs
  Sesame for warmth.
- Custom wake-word model for "Hey Reachy" / "Hey Adam" trained on
  Adam's voice samples (existing `voiceprints` router).
- Camera-driven presence: when Adam looks at Reachy and speaks,
  skip wake-word; when he turns away, soft-mute.

---

## Critical files to touch (cheat sheet)

- `backend/app/services/reachy_realtime/local_handler.py`
- `backend/app/services/reachy_realtime/session.py`
- `backend/app/services/reachy_realtime/tools.py`
- `backend/app/services/reachy_realtime/profiles.py`
- `backend/app/services/audio_service.py` *(TTS provider plug)*
- `backend/app/services/memory_facade.py` *(new)*
- `backend/app/services/supervisor_graph.py` *(new)*
- `backend/app/services/digest_email_service.py` *(new)*
- `backend/app/services/daily_brief_service.py` *(new)*
- `backend/app/services/bookkeeper_service.py` *(new)*
- `backend/app/services/email_automation_service.py` *(extend)*
- `backend/app/services/llc_guidance_service.py` *(extend)*
- `backend/app/routers/reachy_intent.py` *(LLM-first reroute)*
- `backend/app/routers/reachy_realtime.py` *(no major change; tool surface)*
- `backend/app/routers/loops.py` or `main.py` *(scheduler hook)*
- `frontend/src/.../DailyBrief.tsx` *(new)*
- `frontend/src/.../DraftsInbox.tsx` *(new)*
- `reachy_app/reachy_mini_zero/main.py` *(streaming rewrite)*
- `shared-infra/litellm/config.yaml` *(speculative decoding,
  `gemini-latest` aliases)*
- `backend/requirements.txt` *(pipecat, mem0ai, langgraph,
  composio-core, beancount)*

---

## Iteration & growth model

This is the part that keeps the whole thing alive after the first ship:

1. **The plan file IS the artifact.** This document at
   `/root/.claude/plans/i-have-a-reachy-glistening-plum.md` is the
   single source of truth; copy it into `docs/reachy-roadmap.md`
   in the repo so it ships with the codebase. Update at the end of
   every phase: what landed, what didn't, what we learned.
2. **`/zero-reachy-audit` skill** already exists and tracks
   capability dimensions across runs. Run it after each phase;
   it writes to persistent memory so successive audits sharpen.
3. **`zero_brain` weekly reflection** writes `LearningCycle`
   records — surface them in the dashboard and treat them as
   first-class roadmap input.
4. **Capability backlog**: every "I want Reachy to do X" goes
   through the existing audit's request log, not into ad-hoc
   conversations.
5. **Open-source watch**: track Pipecat / Pollen / mem0 / LangGraph
   release notes monthly; the `MEMORY.md` already documents the
   "always use latest model" rule — extend it to "always check
   latest framework" before each phase kicks off.

---

## End-to-end verification plan

Once Phases 1–6 are merged:

```bash
# 1. Stack health
docker compose -f docker-compose.sprint.yml up -d
docker ps --format "table {{.Names}}\t{{.Status}}" | grep zero
curl http://localhost:18792/health
curl http://localhost:18796/host/docker_status
curl http://localhost:18800/v1/models   # llama.cpp Qwen3.6
curl http://localhost:18792/api/reachy-intent/providers/status

# 2. Realtime through the browser surface (lower hardware risk)
#    open http://localhost:5173 → InteractiveModeBar → Space → speak
#    look for: <1.5s TTFB, partial transcript visible, barge-in works.

# 3. Realtime through the Reachy Mini physical robot
#    confirm streaming WebRTC client is launched on the robot
#    confirm time-to-first-audio at the speaker is comparable.

# 4. Memory recall
#    "Reachy, remember that my CPA candidate is Smith & Co."
#    restart zero-api container.
#    "Reachy, who's my CPA candidate?" → Smith & Co.

# 5. Email/calendar end-to-end (multi-account)
#    "Draft a reply to the latest message from Sunbiz on my work account"
#    expect: a draft in DraftsInbox scoped to the work account
#    "send it" → mail leaves; check Gmail Sent.

# 6. Company operations
#    "What's the status on the Florida LLC annual report?"
#    "What was my P&L last month?"

# 7. Daily brief
#    set scheduler to next minute, trigger
#    expect dashboard tile + email + "speak it" works.

# 8. Learning loop
#    after a day of use, /zero-deep-review or /zero-employee-checkin
#    expect non-empty OutcomeRecord rows and a PromptVariant in A/B.
```

---

## Risks & mitigations

- **Pipecat adoption breaks the existing browser realtime UX.** Land
  it behind a `REACHY_REALTIME_ENGINE=pipecat|legacy` env flag and
  default to legacy until Phase 1 is verified end-to-end.
- **mem0 doubles memory footprint.** The facade can read from existing
  stores during transition; cut over per surface.
- **LangGraph supervisor adds latency to direct chat.** Short-circuit
  in the `classify` node — if it's small talk, skip the graph and
  reply directly.
- **Multi-Gmail OAuth scope creep.** Start with read+draft on a
  single account, then add accounts and the `send` scope behind
  Adam's per-account approval.
- **Bookkeeping correctness.** Beancount drafts only; never auto-post
  to anything that has tax implications. Adam reviews monthly close.
- **Pollen SDK churn.** Reachy Mini SDK API for media changed in
  early 2026; the streaming rewrite must be tested against the
  shipping SDK on Adam's actual hardware.

---

## What I deferred (and why)

- **Voice cloning of Adam's voice for outbound replies** — ethical/
  consent edge cases; revisit after Phase 8.
- **Full home-assistant integration** — `routers/home_assistant.py`
  exists but isn't on the critical path for "second brain"; defer
  until phases 1–6 are smooth.
- **Mobile PWA push integration for the daily brief** — the brief
  email already covers the mobile case; PWA push is a Phase 8
  polish item.

---

*Last updated: 2026-05-09. Edit me at the end of every phase.*
