# Legion Employee: World-Class Autonomous AI Employee

## Context

Legion currently operates as a powerful but **silent** autonomous task executor. It has a brain that makes decisions, an agentic loop that runs 24/7, 36 agents, a 6-layer learning system, and a chat interface called "AskLegion" -- but these systems are **disconnected**. The brain makes decisions silently (only visible in server logs), the chat system can't see what the brain is doing, learning is partially dormant (episodic retrievals = 0), and there's no proactive communication with the operator.

The goal is to transform Legion into a **world-class AI employee** -- an intelligent, communicative team member that the operator can talk to naturally, that explains its reasoning, learns from every interaction, manages multiple projects, and continuously improves itself by studying the best agentic systems (Claude Code, Devin, Cursor, DeerFlow, Hermes, OpenClaw, CrewAI).

Research shows the gap between world-class and mediocre agents is: **persistent memory** (26% accuracy gain), **explicit error recovery** (30-40% completion boost), **outcome tracking**, **workspace isolation**, and **behavioral observability**. Legion has ~70% of this infrastructure built but the systems aren't talking to each other.

---

## Phase 1: Brain-Chat Bridge (Sprint: Employee-01)

**Goal**: Make the brain visible to chat so the operator can talk to Legion like an employee.

### 1.1 Brain Context Builder
- **File**: [chat_service.py](backend/app/services/chat_service.py)
- Add `_get_brain_context()` method that queries:
  - `brain_decisions` table: last 10 decisions with type, reason, confidence, timestamp
  - Current brain state (IDLE/PLANNING/EXECUTING/LEARNING/WAITING) via `get_brain()` singleton
  - Active sprint info: what's running, progress, ETA
  - Recent self-improvement cycle results from `self_improvement_cycles` table
  - Recent reasoning events from `rca_clusters`, `health_finding_snapshots`, `work_discovery_runs`
- Inject this as a new `## Brain Status & Recent Decisions` section in `_build_system_prompt()`
- Result: When user asks "what are you working on?" or "why did you start that sprint?", the LLM has the brain's actual decisions in its context

### 1.2 Brain Event Publishing
- **File**: [autonomous_brain.py](backend/app/services/autonomous_brain.py)
- After every `_persist_decision()` call, publish to event bus:
  ```python
  event_bus.publish(EventType.BRAIN_DECISION, {
      "decision_type": decision.decision_type.value,
      "reason": decision.reason,
      "confidence": decision.confidence,
      "target_id": decision.target_id,
      "db_id": decision.db_id,
  })
  ```
- Also publish `BRAIN_PLANNING` when entering planning state, `BRAIN_REVIEW` when learning from outcomes
- **File**: [nervous_system/event_bus.py](backend/app/services/nervous_system/event_bus.py) -- verify EventType enum has BRAIN_* types (research says they exist but are never fired)

### 1.3 Employee System Prompt Upgrade
- **File**: [chat_service.py](backend/app/services/chat_service.py)
- Replace generic `LEGION_SYSTEM_PROMPT` with employee-persona prompt:
  - Name: "Legion" -- first-person identity ("I decided to...", "I'm currently working on...")
  - Personality: Direct, transparent about reasoning, proactive in surfacing concerns
  - Capabilities awareness: knows it can start/pause sprints, learn from outcomes, manage multiple projects
  - Communication style: Reports like an employee ("Here's my status...", "I recommend we...", "I noticed a problem...")
  - Uncertainty handling: When confidence is low, says so and asks for input
- Keep existing RAG + live data context injection

### 1.4 Brain Query Endpoints
- **File**: [chat.py](backend/app/api/endpoints/chat.py) -- add new endpoints (BEFORE any `/{param}` routes):
  - `GET /chat/brain/status` -- current brain state, active sprints, recent decisions
  - `GET /chat/brain/decisions/{decision_id}/explain` -- detailed explanation of a specific decision with alternatives_considered from metadata
  - `GET /chat/brain/activity` -- last 24h activity feed (decisions + sprints + learning events)

### Files Modified
- `backend/app/services/chat_service.py` -- brain context builder + employee persona
- `backend/app/services/autonomous_brain.py` -- event publishing after decisions
- `backend/app/api/endpoints/chat.py` -- 3 new brain query endpoints

---

## Phase 2: Persistent Sessions + Decision Linking (Sprint: Employee-02)

**Goal**: Chat sessions survive restarts and link to brain decisions for full conversation continuity.

### 2.1 ChatSessionDB Migration
- **New migration**: `backend/alembic/versions/035_chat_sessions.py`
- Tables:
  ```sql
  chat_sessions:
    id: Integer PK
    session_id: String(64) UNIQUE NOT NULL  -- maps to current in-memory session_id
    project_id: Integer FK(projects.id) NULLABLE
    title: String(200)
    created_at: DateTime
    last_active_at: DateTime
    metadata: JSON  -- extensible (persona preferences, context prefs)

  chat_messages:
    id: Integer PK
    session_id: Integer FK(chat_sessions.id) ON DELETE CASCADE
    role: String(20)  -- "user", "assistant", "system"
    content: Text NOT NULL
    sources: JSON  -- RAG source citations
    linked_decision_id: Integer NULLABLE  -- FK to brain_decisions.id
    created_at: DateTime
  ```

### 2.2 Hybrid Session Store
- **File**: [chat_service.py](backend/app/services/chat_service.py)
- Keep in-memory `_sessions` dict as hot cache (fast reads)
- On every message: persist to `chat_messages` table async (fire-and-forget, never block chat)
- On session create: persist to `chat_sessions` table
- On startup: load last 20 sessions from DB into memory cache
- On session access miss: check DB before creating new session
- TTL cleanup: mark `last_active_at` in DB, sweep stale sessions weekly (not 24h -- employee memory should be durable)

### 2.3 Decision Linking
- When brain context builder finds a decision that matches the user's question (e.g., user asks about sprint #X and brain has a START_SPRINT decision for #X), set `linked_decision_id` on the assistant's response message
- Frontend can render linked decisions as expandable cards

### Files Modified
- New: `backend/alembic/versions/035_chat_sessions.py`
- New: `backend/app/models/chat_session.py` (ChatSessionDB, ChatMessageDB)
- `backend/app/services/chat_service.py` -- hybrid storage, decision linking
- `backend/app/models/__init__.py` -- export new models

---

## Phase 3: Proactive Communication + Operator Feed (Sprint: Employee-03)

**Goal**: Legion proactively tells the operator what it's doing, like an employee giving status updates.

### 3.1 Proactive Message Service
- **New file**: `backend/app/services/legion_employee_service.py` (~200 lines)
- Subscribes to event bus events and generates operator-facing messages:
  - `BRAIN_DECISION` with confidence > 0.7 --> "I started sprint X because..." (auto-message)
  - `BRAIN_DECISION` with confidence < 0.5 --> "I'm considering X but I'm not confident. Should I proceed?" (approval request)
  - `SPRINT_COMPLETED` --> "Sprint X completed successfully. Key findings: ..."
  - `SPRINT_FAILED` --> "Sprint X failed. Root cause: ... I recommend: ..."
  - Self-improvement cycle complete --> "Daily self-check done. Found N issues, created M sprints"
  - Health finding detected --> "I noticed a health issue: ..."
- Messages stored in a `proactive_messages` queue (in-memory deque, max 50)
- Endpoint: `GET /chat/proactive` -- returns unread proactive messages
- Endpoint: `POST /chat/proactive/{id}/acknowledge` -- marks as read

### 3.2 Frontend Activity Feed
- **File**: [AskLegion.tsx](frontend/src/pages/AskLegion.tsx) or new sidebar component
- Poll `GET /chat/proactive` every 30s (or WebSocket subscription)
- Show in a sidebar panel: "Legion's Activity"
  - Recent decisions with confidence indicators
  - Active sprint progress
  - Proactive messages (unread highlighted)
  - Current brain state badge (Idle/Planning/Executing/Learning)
- **File**: [useChat.ts](frontend/src/hooks/useChat.ts) -- add `useProactiveMessages()` hook

### 3.3 Human-in-the-Loop for Low-Confidence Decisions
- **File**: [autonomous_brain.py](backend/app/services/autonomous_brain.py)
- Add confidence threshold check before executing decisions:
  - `confidence >= 0.7`: auto-execute (current behavior)
  - `confidence >= 0.4 && < 0.7`: create proactive message asking for approval, wait up to 10 minutes, then auto-execute with warning
  - `confidence < 0.4`: create proactive message, block until operator responds or 1-hour timeout
- New endpoint: `POST /chat/brain/approve/{decision_id}` -- operator approves/rejects pending decisions
- Decision states: `pending_approval`, `approved`, `rejected`, `auto_approved_timeout`

### Files Modified
- New: `backend/app/services/legion_employee_service.py`
- `backend/app/services/autonomous_brain.py` -- confidence gating
- `backend/app/api/endpoints/chat.py` -- proactive + approval endpoints
- `frontend/src/pages/AskLegion.tsx` -- activity feed sidebar
- `frontend/src/hooks/useChat.ts` -- proactive messages hook
- New: `frontend/src/components/LegionActivityFeed.tsx`

---

## Phase 4: Episodic Memory Activation + Reflexion (Sprint: Employee-04)

**Goal**: Make the learning system actually work -- episodic retrievals flowing into task execution, and self-critique before decisions.

### 4.1 Episodic Retrieval Activation
- **File**: [agent_swarm_service.py](backend/app/services/agent_swarm_service.py) -- `coder_node()` already has LearningEngine enrichment (Audit-Remediation-01). Verify `episodic_memory_service.retrieve_similar()` is called inside `enrich_task_context()` and returns results.
- **File**: [episodic_memory_service.py](backend/app/services/episodic_memory_service.py) -- verify `retrieve_similar()` actually queries and returns episodes. If it requires Qdrant vector similarity and Qdrant is empty, fall back to PostgreSQL `task_type` + recency matching.
- **File**: [learning_engine.py](backend/app/services/learning_engine.py) -- verify `enrich_task_context()` includes episodic results in the enrichment output.
- Goal: `legion_learning_engine_enrichments_total{source="episodic_memory"}` counter goes from 0 to positive

### 4.2 Reflexion Layer (Pre-Decision Critique)
- **File**: [autonomous_brain.py](backend/app/services/autonomous_brain.py)
- Before executing any `START_SPRINT` or `CREATE_FIX_SPRINT` decision, run a lightweight critique:
  ```python
  async def _reflexion_check(self, decision: BrainDecision) -> BrainDecision:
      """Self-critique: should I really do this?"""
      # Check: have we tried this before and failed?
      similar_past = await self._find_similar_past_decisions(decision)
      if similar_past and similar_past.outcome == "failed":
          decision.confidence *= 0.5
          decision.reason += f" [Reflexion: similar decision #{similar_past.db_id} failed previously]"

      # Check: is this a duplicate of recent work?
      recent_sprints = await self._get_recent_sprints(hours=24)
      if any(s.name similar to decision.metadata.get("sprint_name") for s in recent_sprints):
          decision.confidence *= 0.3
          decision.reason += " [Reflexion: duplicate of recent sprint]"

      return decision
  ```
- This is NOT a full LLM call -- it's a DB-only heuristic check (zero cost, <50ms)
- Reduces false-positive Fix sprints (Sprint-Cleanup-02 showed 64% failure rate was from auto-creation spam)

### 4.3 Post-Execution Reflection
- After sprint completion (success or failure), brain calls:
  ```python
  async def _post_execution_reflection(self, sprint_id: int):
      """What did I learn from this sprint?"""
      grade = await SprintQualityGrader().grade_sprint(sprint_id)
      # Store as episodic memory if quality >= 0.7
      # Update routing optimizer with outcome
      # If failed: store failure pattern for reflexion_check
  ```
- This already partially exists via auto-grade hooks and learning aggregator. Wire them together.

### Files Modified
- `backend/app/services/autonomous_brain.py` -- reflexion check + post-execution reflection
- `backend/app/services/episodic_memory_service.py` -- verify/fix retrieval path
- `backend/app/services/learning_engine.py` -- verify enrichment includes episodes
- `backend/app/services/agent_swarm_service.py` -- verify LearningEngine call in coder_node

---

## Phase 5: Continuous Research & Self-Improvement Skill (Sprint: Employee-05)

**Goal**: Create the `legion-employee` skill that continuously researches and improves the employee.

### 5.1 Skill Definition
- **New file**: `.claude/skills/legion-employee/SKILL.md`
- Modes:
  - `--status`: Current employee health (brain activity, learning metrics, chat engagement, episodic memory stats, proactive message delivery rate)
  - `--research`: Research latest best practices in AI agents (web search for new patterns, compare with current implementation, propose improvement sprints)
  - `--improve`: Apply the most impactful improvement from research backlog
  - `--audit`: Full audit of employee capabilities vs world-class benchmarks (Claude Code, Devin, Cursor, DeerFlow, Hermes patterns)
  - `--persona`: Review and refine the employee persona (communication style, proactivity level, confidence thresholds)
- Knowledge files:
  - `knowledge/research_backlog.json` -- improvement ideas from research, ranked by impact
  - `knowledge/benchmark_scores.json` -- current scores vs world-class benchmarks across 8 dimensions
  - `knowledge/persona_config.json` -- personality settings, communication style, confidence thresholds
  - `knowledge/applied_improvements.md` -- log of what's been researched, applied, and measured

### 5.2 Research Framework
- 8 benchmark dimensions (scored 0-100):
  1. **Memory Persistence**: Cross-session learning retention (episodic retrievals, knowledge reuse)
  2. **Error Recovery**: Reflexion effectiveness (false-positive rate, recovery success rate)
  3. **Communication**: Proactive messaging quality (operator satisfaction, response relevance)
  4. **Multi-Project**: Cross-project learning transfer (patterns applied across projects)
  5. **Decision Quality**: Brain decision outcomes (success rate, confidence calibration)
  6. **Learning Velocity**: How fast the system improves (grade trend over time)
  7. **Operator Trust**: Human-in-the-loop usage (approval rate, override frequency)
  8. **Autonomy**: Tasks completed without operator intervention

### 5.3 Research Cycle
- When invoked with `--research`:
  1. Web search for latest AI agent patterns (2026 best practices, new frameworks, competitor updates)
  2. Compare findings against current Legion implementation
  3. Rank improvements by (impact on benchmark dimension) x (implementation effort)
  4. Add top 3 to `research_backlog.json` with proposed sprint name + tasks
  5. Report findings to operator

### Files Created
- `.claude/skills/legion-employee/SKILL.md` -- full skill specification
- `.claude/skills/legion-employee/knowledge/research_backlog.json`
- `.claude/skills/legion-employee/knowledge/benchmark_scores.json`
- `.claude/skills/legion-employee/knowledge/persona_config.json`
- `.claude/skills/legion-employee/knowledge/applied_improvements.md`

---

## Phase 6: Frontend Polish + Integration Testing (Sprint: Employee-06)

**Goal**: Make the AskLegion page feel like talking to an intelligent employee.

### 6.1 Enhanced AskLegion UI
- **File**: [AskLegion.tsx](frontend/src/pages/AskLegion.tsx)
- Split into 2-column layout:
  - **Left (70%)**: Chat conversation (existing, enhanced)
  - **Right (30%)**: Legion Activity Feed (new sidebar)
- Activity feed shows:
  - Brain state badge (colored dot: green=idle, blue=planning, amber=executing, purple=learning)
  - Recent decisions (last 5, with confidence bars)
  - Proactive messages (unread count badge)
  - Quick actions: "What are you working on?", "Show recent decisions", "Daily report"
- Chat bubbles enhanced:
  - Decision-linked messages show expandable decision card
  - Source citations rendered as collapsible chips (existing)

### 6.2 Quick Action Buttons
- Pre-built questions the operator can ask with one click:
  - "What are you working on right now?"
  - "Show me today's decisions"
  - "How are the projects doing?"
  - "What did you learn recently?"
  - "Run a self-check"
- These just send the text as a chat message (no special backend logic needed)

### 6.3 WebSocket Integration for Real-Time Updates
- **File**: [useChat.ts](frontend/src/hooks/useChat.ts)
- Subscribe to `ws://localhost:8005/ws/events` filtered by `BRAIN_*` event types
- On `BRAIN_DECISION` event: add to activity feed, show notification toast if high importance
- On `SPRINT_COMPLETED`/`SPRINT_FAILED`: update activity feed
- Existing WebSocket infrastructure at `/ws/events` -- just subscribe and filter

### Files Modified
- `frontend/src/pages/AskLegion.tsx` -- 2-column layout + activity feed
- `frontend/src/hooks/useChat.ts` -- WebSocket subscription + proactive messages hook
- New: `frontend/src/components/LegionActivityFeed.tsx` -- sidebar component
- New: `frontend/src/components/BrainDecisionCard.tsx` -- decision card component
- New: `frontend/src/hooks/useBrainStatus.ts` -- brain state polling hook

---

## Sprint Naming & Tracking

All work tracked as Legion sprints (project_id=3):
- `Employee-01: Brain-Chat Bridge` (Phase 1)
- `Employee-02: Persistent Sessions` (Phase 2)
- `Employee-03: Proactive Communication` (Phase 3)
- `Employee-04: Episodic Memory + Reflexion` (Phase 4)
- `Employee-05: Continuous Research Skill` (Phase 5)
- `Employee-06: Frontend Polish` (Phase 6)

---

## Verification Plan

After each phase, verify:

1. **Employee-01**: Ask "what are you working on?" in AskLegion chat --> response includes actual brain decisions, not generic text. Check `docker logs` for BRAIN_DECISION events being published.

2. **Employee-02**: Restart backend (`docker-compose restart legion-backend`), reopen AskLegion --> previous session restored with full message history. Check `chat_sessions` and `chat_messages` tables have rows.

3. **Employee-03**: Wait for brain to make a decision --> proactive message appears in activity feed within 30s. Low-confidence decision shows "Should I proceed?" prompt. `GET /chat/proactive` returns unread messages.

4. **Employee-04**: Check Prometheus: `legion_learning_engine_enrichments_total{source="episodic_memory"}` > 0. Brain creates Fix sprint --> reflexion check logged ("similar decision failed previously"). Grade trends improving.

5. **Employee-05**: Run `/legion-employee --status` --> returns benchmark scores across 8 dimensions. Run `/legion-employee --research` --> produces 3 ranked improvement proposals in `research_backlog.json`.

6. **Employee-06**: Open AskLegion page --> 2-column layout with activity feed on right. Brain makes decision --> toast notification appears in real-time. Click quick action button --> sends pre-built question.

---

## Key Patterns Borrowed from Research

| Pattern | Source | How Used in Legion |
|---------|--------|--------------------|
| Layered memory (always-on / session / persistent) | Claude Code, Hermes | Brain context (always-on) + chat sessions (session) + episodic DB (persistent) |
| Reflexion (self-critique before action) | Reflexion framework | Pre-decision heuristic check in brain |
| Human-in-the-loop with confidence gating | Claude Code, DeerFlow | Confidence threshold: auto/ask/block |
| Proactive communication | Hermes, Devin | Brain publishes events --> operator feed |
| Procedural memory (learned skills) | Hermes | Research skill evolves improvement backlog |
| State machine orchestration | LangGraph | Brain state machine (existing, enhanced) |
| Role-based agent coordination | CrewAI | 36 agents already role-based (existing) |
| Workspace isolation per project | Cursor, DeerFlow | Per-project context in chat (existing, enhanced) |
| Outcome-based learning | Devin | Sprint grades --> episodic memory --> retrieval |
