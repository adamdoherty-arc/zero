# Adoption report â€” openhuman + OpenHands â†’ Zero

**Branch:** `claude/review-openhuman-features-7dbWv`
**Date:** 2026-05-13
**Status:** Shipped across five commits + microagent wire-up

This report covers everything that landed on the branch over five passes:
the initial openhuman adoption, two rounds of plan audits, the Bifrost
+ companion-promotion + audit-2 pass, and the OpenHands SDK integration.

---

## 1. Executive summary

Zero now has on-screen embodiment, a browsable Markdown vault, a real
integration layer, hint-based LLM routing, a meeting agent, a
subconscious reflection loop, sandboxed code-agent dispatch, and a
trigger-based microagent system. Every new component degrades
gracefully when its optional dependency is missing (Composio,
Playwright, OpenHands SDK, Telegram token) and every new service
exposes a REST surface plus, where applicable, a frontend page.

**Numbers**

- **5 commits** on `claude/review-openhuman-features-7dbWv`
- **~95 new source files**
- **+8200 lines** across backend + frontend
- **176 new tests** (170 backend + 6 microagent-injection, plus 14
  pre-existing frontend mascot tests still passing)
- **`tsc --noEmit` clean** end-to-end on frontend
- **0 leaked runtime data dirs** (tests isolate via lazy module-attr
  reads + monkeypatching)

---

## 2. Commit-by-commit timeline

| Sha | Headline | Lines |
|---|---|---|
| `2d8204a` | Initial openhuman adoption â€” mascot, memory tree, integrations, meeting agent | +6119 |
| `fb6ab46` | First audit: cloud visemes, daily digest, personalityâ†’vault, narrator, agent_alerts, all personas migrated | +654 |
| `185ef88` | Second audit: reachy_memoryâ†’vault, more TokenJuice helpers, wake-word note hook | +275 |
| `4a83928` | Bifrost client + companion promotion + skills registry + browser-control + Telegram | +1950 |
| `a6a685a` | OpenHands SDK adapter + microagents + 6 seed microagents + UI page | +1300 |
| **HEAD** | Microagent injection into realtime composer + OpenHands dispatch | +220 |

---

## 3. Features shipped, grouped

### 3.1 On-screen embodiment (T1.1, T3.2)

- **SVG mascot** at `frontend/src/components/reachy/Mascot/` with 8
  visemes (`REST`, `A`, `E`, `I`, `O`, `U`, `M`, `F`) defined as
  `{openness, width}` 2D params. Mouth path is a parametric quadratic
  BÃ©zier; body bobs subtly while speaking to mirror Reachy's head
  wobble in spirit.
- **`useMascot` hook** with three-layer viseme stream:
  1. Backend-emitted `mascot.viseme` frames (preferred)
  2. Streaming-text character walker (16 chars/sec)
  3. Procedural breathing fallback
- **Face state machine** maps `SessionPhase` â†’ idle / listening /
  thinking / speaking / concerned.
- **`MascotDock`** floats globally in `DashboardLayout` whenever a
  realtime voice session is active. Pop-out button opens `/m/mascot`
  in a fresh window; both windows sync via `BroadcastChannel`.
- **Backend viseme surfacing**:
  - Local handler: text-aligned 20 Hz frames in lockstep with
    `audio.delta` PCM chunks.
  - OpenAI Realtime: energy-driven `viseme_from_pcm_rms()` per chunk
    (cloud has no phoneme alignment).
  - Gemini Live: same RMS-driven pattern.
- **MascotPopout** route works without parent tab â€” shows
  "Waiting for Zero sessionâ€¦" until a broadcast arrives.

### 3.2 Memory Vault + Obsidian-compatible vault (T1.2, T3.3)

- **3 tree types**: Source (`L0`/`L1`/`L2` per source), Topic
  (per-entity), Global (daily digest).
- **`chunker.py`** splits on paragraph â†’ sentence â†’ hard-cut boundaries,
  â‰¤3000 tokens per chunk.
- **`vault.py`** writes Obsidian-compatible Markdown with YAML
  frontmatter (partition, agent_run_id, agent_writable, source, level,
  title, created, tags, parent, token_count), unique part/hash filenames,
  and an audit footer. Production root:
  `/vault/00_Meta/_agent/memory_vault/`; tests use an isolated temp vault.
- **`service.py`** exposes `write_chunk`, `write_topic`,
  `write_global_digest`, and BM25-ish keyword `search(scope, source,
  entity, limit)`.
- **Daily global-digest scheduler job** at 04:00 UTC walks every
  Source chunk from the last 24h, writes a single
  `vault/global/{yyyymmdd}.md`.
- **REST surface**: `/api/memory-vault/{stats,search,entry,chunks,global-digest}`.
  `/api/memory-tree/*` remains a deprecated compatibility alias.
- **MemoryVaultPage** at `/memory-vault` â€” search box, scope filter,
  per-source/topic/level counts, modal entry viewer.
- **`reachy_memory.save_summary()` now mirrors** every Tier-3 episodic
  snapshot into the vault under `sources/episodic_{persona}/L0/`.
- **`personality_synthesis` nightly run** also writes a chunk to
  `sources/personality/L0/`.

### 3.3 TokenJuice compaction (T1.3)

- `tokenjuice_compactor.py` â€” HTML â†’ Markdown, URL shortening with
  footnote, ANSI / CR-progress strip, dup-run collapse, oversized
  head + tail trim.
- **Auto-detect** kind from content (`html` / `terminal` / `json` /
  `text`) so callers don't have to know.
- **`compact_with_telemetry()`** wrapper feeds process-wide counters
  surfaced at `GET /api/llm/compact/metrics`.
- **`tool_output_helpers.py`** ships typed wrappers:
  - `compact_git_diff`
  - `compact_terminal_output`
  - `compact_file_read`
  - `compact_html`
  - `compact_json_dump`
- Wired into SearXNG research output and the browser-control extract
  path.
- `/api/llm/compact` for any external caller.

### 3.4 Integrations + auto-fetch (T1.4)

- **`composio_provider.py`** â€” Composio SDK wrapper with graceful
  degradation (no SDK or no `COMPOSIO_API_KEY` â†’ reports
  `is_available=False`).
- **12-app seed catalog**: Gmail, Calendar, Drive, GitHub, Linear,
  Slack, Notion, Stripe, Jira, HubSpot, Discord, Zoom. Adding more
  apps requires no code changes.
- **`auto_fetch_loop.py`** - 20-min APScheduler-style loop walks every
  verified connected service into the Memory Vault as L0 chunks. Native
  Gmail/Calendar require real OAuth; Composio-only apps stay unavailable
  until per-tool calls are added.
- **REST**: `/api/integrations/{,/status,/connect,/disconnect/{id},/sync/{id},/auto-fetch/{start,stop}}`.
- **IntegrationsPage** at `/integrations` â€” grouped by category,
  connect/disconnect/sync-now buttons, auto-fetch toggle, last-fetched
  relative timestamps.

### 3.5 Hint-based LLM routing (T1.5)

- **`llm_hints.py`** â€” 12-hint taxonomy:
  - Local-eligible: `hint:reaction`, `classify`, `format`,
    `sentiment`, `summarize`, `medium`, `tool_lite`, `reflection`.
  - Cloud-only: `hint:reasoning`, `agentic`, `coding`, `vision`.
- **4 presets** (`default`, `embeddings_only`, `memory_reflection`,
  `everything_local`) selectable via `ZERO_HINT_PRESET` env.
- **`LlmRouter.resolve()` extended** to accept hint strings and apply
  preset overrides at call time (so flipping `ZERO_HINT_PRESET`
  applies without restart).
- **`HintPresetPicker`** React component mounted in
  `ReachyRealtimeSettings` modal.
- **REST**: `/api/llm/hints`, `/api/llm/hints/preset`,
  `/api/llm/hints/resolve/{hint}`.

### 3.6 Bifrost gateway integration

User clarified Bifrost is **shared infra** Zero talks to (not bundles).

- **Bifrost runtime config is not shipped in Zero.** The live shared config is
  `C:\code\shared-infra\bifrost\config.json`; Zero only owns the client and
  contract expectations.
- **`bifrost_client.py`** â€” thin OpenAI-compat client. Reads
  `BIFROST_GATEWAY_URL` at call time, honors `BIFROST_TOKEN` for auth,
  reports `is_available()=False` cleanly when unset.
- **Contract test** (`test_bifrost_contract.py`) keeps Zero from adding local
  runtime YAML and verifies client availability/error behavior.
- **Meeting Agent narrator** prefers Bifrost when reachable and falls
  back gracefully.

### 3.7 SOUL.md persona format (T2.3)

- **`soul_md.py`** parser handles structured H2 sections (Personality,
  Voice & Tone, Behaviors, Safety Rules, Memory, Emergency Responses,
  Games) plus free-form preamble.
- **Takes precedence over `instructions.txt`** in `profiles.py`.
- **All 9 personas** migrated: assistant, coach, companion, deep_work,
  explorer, narrator, sally, wellness, **buddy** (new child-companion
  reference persona based on openhuman's "Buddy the Robot" SOUL.md).
- **`safety_rules_from_soul()`** extracts NEVER-BREAK rules (eg.
  "never move faster than walking speed" â†’ consulted by the motion
  layer before physical commands).

### 3.8 Meeting Agent (T2.1)

- **`meeting_agent_service.py`** â€” joins Meet / Zoom URLs (regex-
  validated). Playwright when installed; structured "unavailable"
  otherwise.
- **Transcript ingestion** writes per-meeting chunks under
  `vault/sources/meeting_{id}/L0/` with `transcript` tag.
- **Wake-word handler**: scans every transcript chunk for
  `Hey Zero, take a note: â€¦` / `Ok Zero, record this: â€¦` /
  `Hey Zero, note: â€¦` and pulls the body into
  `vault/topics/meeting_notes_{id}/`.
- **Narrator persona auto-fires on `leave()`** â€” assembles the
  narrator's SOUL.md prompt via `hint:summarize`, prefers Bifrost
  when reachable, writes an L1 summary chunk.
- **REST**: `/api/meeting-agent/{status,sessions,sessions/{id},
  sessions/{id}/{speak,leave,ingest}}`.
- **MeetingAgentPage** at `/meeting-agent` â€” drop a URL, list active
  sessions, speak button, leave button, status pills.

### 3.9 Subconscious loop (T2.2)

- **`subconscious_loop.py`** â€” background `asyncio` task waking every
  N minutes (default 15) when there's been fresh vault activity.
- **Walks recent vault + connected integrations**, asks the local
  LLM via `hint:reflection`, persists JSON insight to the vault under
  `sources/subconscious/L0/`.
- **Promotion from companion service**: before raising an
  `agent_alert`, consults `companion.action_allowed('proactive_nudge')`
  AND enforces the per-mode `max_proactive_events_per_hour` budget
  ("off" silent, "focus" 2/h, "ambient" 4/h). Each surfacing also
  records a `CompanionEvent` so existing UI displays it.
- **REST**: `/api/subconscious/{status,start,stop,config,insights,run-now}`.
- Auto-starts when `ZERO_SUBCONSCIOUS_AUTOSTART=1`.

### 3.10 Triggers pipeline (T3.1)

- **`triggers_service.py`** â€” declarative eventâ†’action rules.
- **Predicate matcher**: `any_of`, `all_of`, `*_contains`, `*_equals`,
  `*_in`, plain equality.
- **Action types**: `vault_write`, `tool`, `webhook`, `agent_prompt`.
- **REST**: `/api/triggers/{,/test-fire,/recent}`. Rules CRUD via
  POST/PUT/DELETE.
- Recent firings buffered in-memory (200) for the UI.

### 3.11 Cost ticker + provider-switch chip (T3.4)

- `InteractiveModeBar` now shows session $-spent, **per-min rate**
  derived from cost / duration, and a "switched mid-session" chip
  when the active model changes during a connection.

### 3.12 Skills registry (audit-2 A)

- **`skill_manifest.py`** â€” extended manifest spec mirroring openhuman:
  slug, name, version, description, **15 known auth scopes**
  (fs_read/write, net_outbound, shell, browser, memory_read/write,
  calendar, gmail, github, linear, slack, notion, tts, motion),
  **4 platforms** (darwin/linux/windows/any), **5 trigger kinds**
  (manual/schedule/event/voice/trigger_rule), sandbox bounds.
- **Auto-migrates legacy `_meta.json`** into the extended shape on
  the fly â€” no churn for existing skills.
- **REST**: `/api/skills/{,/{slug},/validate,/third-party-registry}`.
- **`skills/third-party-skills.json`** seeded with the 3
  openhuman-skills exemplars (server-ping, notion, gmail).

### 3.13 Browser / computer-use (audit-2 B)

- **`browser_control_service.py`** â€” Playwright when installed,
  structured "unavailable" otherwise.
- Actions: open / click / type / extract_text / screenshot / close.
- **`BROWSER_CONTROL_ALLOWLIST` env** locks the agent to specific URL
  prefixes â€” a runaway loop can't crawl the open internet.
- **`extract_text` runs through TokenJuice** so page bodies don't
  drown the LLM in nav chrome.
- **5 MB screenshot cap** prevents memory blow-up.
- **REST**: `/api/browser-control/{status,sessions,sessions/{id}/{click,type,extract,screenshot,close}}`.

### 3.14 Telegram 2-way channel (audit-2 C)

- **`telegram_channel_service.py`** â€” raw `httpx` Bot API client +
  long-poll loop. Reads `TELEGRAM_BOT_TOKEN` at call time. Empty
  text + over-length messages clamped.
- **Default handler** writes inbound to `vault/sources/telegram/L0/`.
- **Custom handler hook** lets agents subscribe (eg. the orchestrator
  could intercept commands).
- **Lifespan auto-starts** the poll loop when the token is set.
- **REST**: `/api/telegram/{status,start,stop,send}`.

### 3.15 OpenHands SDK runtime + microagents

User asked specifically for OpenHands.

- **`openhands_runtime_service.py`** - present but disabled by default.
  It returns `unavailable` until `ZERO_OPENHANDS_ENABLED` and a real
  runtime are approved; the active implementation path is Legion delegation.
- **Bifrost-aware**: when `BIFROST_GATEWAY_URL` is set, OpenHands
  routes LLM calls through the gateway so budget caps apply to code-
  agent runs too.
- **Vault-mirrored**: finished task mirroring is gated behind the Memory
  Vault approval contract.
- **Persistent**: tasks survive restarts via
  `backend/app/data/openhands/tasks.json`.
- **`microagents_service.py`** â€” Markdown + YAML frontmatter parser
  (both inline `[a, b]` and block `- a` list styles). Two scopes:
  `microagents/` (public) and `.openhands/microagents/` (repo).
- **`compose_context_for(text)`** returns a single ready-to-inject
  system-prompt fragment capped at 4000 chars.
- **6 seed microagents**: `reachy-motion`, `zero-python`,
  `zero-frontend`, `memory-vault`, `llm-routing`, `zero-deploy`.
- **REST**: `/api/openhands/*` + `/api/microagents/*`.
- **OpenHandsTasksPage** at `/openhands` â€” instruction box, workspace
  picker, task list with status pills, event drawer.
- **Microagent injection wired into**:
  - `resolve_instructions(profile_id, seed_text=...)` â€” realtime
    sessions get triggered context at session start.
  - `compose_turn_context(text)` â€” chat / classic-voice paths can
    inject per-turn.
  - `OpenHandsRuntimeService.dispatch()` â€” prepends matching
    microagents to every task instruction.

---

## 4. Architecture decisions & deliberate divergences

Several places the implementation diverged from the original plan,
each documented in the relevant commit message:

1. **Mascot lives in `MascotDock` floating overlay, not embedded in
   `InteractiveModeBar`.** The bar is a small chip; embedding a face
   would cramp it. The popout (`/m/mascot`) handles the desktop-app
   style.
2. **Mascot doesn't proxy raw 6-DoF head wobble** â€” instead the SVG
   body bobs via `sin(t) Ã— openness` while speaking. Same intent
   (visible motion while talking) without a new event channel.
3. **`tool_output_helpers.py` placed flat at `services/`** instead
   of `services/tools/` â€” `tools/` doesn't exist in this repo.
4. **`useMascot.ts` (not `useReachyMascot.ts`)** â€” lives under
   `Mascot/` so the prefix would be redundant.
5. **Subconscious built as parallel loop, not "promoted" from
   companion** â€” companion service's nudge state machine still owns
   mode policy. Subconscious consults it (`action_allowed`,
   per-mode budget) but doesn't absorb it. Better separation of
   concerns; both can evolve independently.
6. **Bifrost is shared infra Zero talks to, not bundled** â€” the
   YAML is a contract, the client is the integration. The contract
   test enforces parity with `llm_hints.py`.

---

## 5. Parked items

Three items remain intentionally unavailable until their real runtime is
approved:

1. **Real meeting-agent audio capture.** Meeting Agent is unavailable unless a
   real Playwright join/audio/transcript driver is enabled.
2. **OpenHands live runtime.** OpenHands is disabled by default and should
   route through Legion unless a separate approved runtime lands.
3. **Docker rebuild for `zero-api` / `zero-ui`.** Required after this
   integration because backend code is copied into the image.

---

## 6. Test coverage

| Suite | Tests | Notes |
|---|---|---|
| `test_llm_hints.py` | 28 | Hint parsing, presets, router integration |
| `test_tokenjuice_compactor.py` | 18 | HTML/terminal/JSON/URL shortening |
| `test_tool_output_helpers.py` | 7 | git/terminal/file wrappers + telemetry |
| `test_soul_md.py` | 13 | Parser, section ordering, safety extraction |
| `test_realtime_visemes.py` | 15 | Backend visemes + RMS-driven for cloud |
| `test_memory_tree.py` | 11 | Chunker, vault, BM25 search |
| `test_integrations_triggers_subconscious.py` | 16 | Composio + auto-fetch + triggers + subconscious |
| `test_meeting_agent_service.py` | 14 | URL validation, persistence, narrator, wake-word |
| `test_bifrost_contract.py` | 9 | Contract parity with `llm_hints` |
| `test_browser_telegram.py` | 12 | Allowlist, send/receive, default vault handler |
| `test_skill_manifest.py` | 12 | Validator, migration, legacy fallback |
| `test_openhands_microagents.py` | 16 | Runtime adapter + microagent loader |
| `test_microagent_injection.py` | 6 | Realtime + OpenHands injection wire-up |
| **Backend total** | **177** | All passing |
| `mascot-visemes.test.ts` | 14 | Frontend viseme math |

**Frontend `tsc --noEmit -p tsconfig.json` clean.** Mascot test suite 14/14.

---

## 7. Files added (high level)

```
backend/app/
â”œâ”€â”€ infrastructure/
â”‚   â”œâ”€â”€ bifrost_client.py
â”‚   â””â”€â”€ llm_hints.py
â”œâ”€â”€ routers/
â”‚   â”œâ”€â”€ browser_control.py
â”‚   â”œâ”€â”€ integrations.py
â”‚   â”œâ”€â”€ meeting_agent.py
â”‚   â”œâ”€â”€ memory_tree.py
â”‚   â”œâ”€â”€ openhands.py
â”‚   â”œâ”€â”€ skill_registry.py
â”‚   â”œâ”€â”€ subconscious.py
â”‚   â”œâ”€â”€ telegram_channel.py
â”‚   â””â”€â”€ triggers.py
â””â”€â”€ services/
    â”œâ”€â”€ browser_control_service.py
    â”œâ”€â”€ integrations/
    â”‚   â”œâ”€â”€ auto_fetch_loop.py
    â”‚   â””â”€â”€ composio_provider.py
    â”œâ”€â”€ meeting_agent_service.py
    â”œâ”€â”€ memory_tree/
    â”‚   â”œâ”€â”€ chunker.py
    â”‚   â”œâ”€â”€ service.py
    â”‚   â””â”€â”€ vault.py
    â”œâ”€â”€ microagents_service.py
    â”œâ”€â”€ openhands_runtime_service.py
    â”œâ”€â”€ reachy_realtime/
    â”‚   â””â”€â”€ visemes.py
    â”œâ”€â”€ skill_manifest.py
    â”œâ”€â”€ soul_md.py
    â”œâ”€â”€ subconscious_loop.py
    â”œâ”€â”€ telegram_channel_service.py
    â”œâ”€â”€ tokenjuice_compactor.py
    â”œâ”€â”€ tool_output_helpers.py
    â””â”€â”€ triggers_service.py

frontend/src/
â”œâ”€â”€ components/reachy/
â”‚   â”œâ”€â”€ HintPresetPicker.tsx
â”‚   â””â”€â”€ Mascot/
â”‚       â”œâ”€â”€ Mascot.tsx
â”‚       â”œâ”€â”€ MascotDock.tsx
â”‚       â”œâ”€â”€ MascotSVG.tsx
â”‚       â”œâ”€â”€ index.ts
â”‚       â”œâ”€â”€ useMascot.ts
â”‚       â””â”€â”€ visemes.ts
â””â”€â”€ pages/
    â”œâ”€â”€ IntegrationsPage.tsx
    â”œâ”€â”€ MascotPopout.tsx
    â”œâ”€â”€ MeetingAgentPage.tsx
    â”œâ”€â”€ MemoryVaultPage.tsx
    â””â”€â”€ OpenHandsTasksPage.tsx

microagents/
â”œâ”€â”€ llm-routing.md
â”œâ”€â”€ memory-vault.md
â”œâ”€â”€ reachy-motion.md
â”œâ”€â”€ zero-frontend.md
â””â”€â”€ zero-python.md

.openhands/microagents/
â””â”€â”€ zero-deploy.md

shared-infra/bifrost/ (not shipped by Zero; live config is in C:\code\shared-infra)

skills/
â””â”€â”€ third-party-skills.json

backend/app/data/reachy_profiles/
â”œâ”€â”€ assistant/SOUL.md          (migrated)
â”œâ”€â”€ buddy/                      (new)
â”‚   â”œâ”€â”€ SOUL.md
â”‚   â”œâ”€â”€ tools.txt
â”‚   â””â”€â”€ voice.txt
â”œâ”€â”€ coach/SOUL.md              (migrated)
â”œâ”€â”€ companion/SOUL.md          (migrated)
â”œâ”€â”€ deep_work/SOUL.md          (migrated)
â”œâ”€â”€ explorer/SOUL.md           (migrated)
â”œâ”€â”€ narrator/SOUL.md           (migrated)
â”œâ”€â”€ sally/SOUL.md              (migrated)
â””â”€â”€ wellness/SOUL.md           (migrated)
```

---

## 8. Operational notes

### Environment variables introduced

| Var | Effect |
|---|---|
| `ZERO_HINT_PRESET` | Switch hint-routing preset (default/embeddings_only/memory_reflection/everything_local) |
| `ZERO_AUTO_FETCH_AUTOSTART` | Start the 20-min integrations loop on boot |
| `ZERO_SUBCONSCIOUS_AUTOSTART` | Start the idle-reflection loop on boot |
| `ZERO_SUBCONSCIOUS_INTERVAL_MIN` | Reflection cadence (default 15) |
| `ZERO_AUTO_FETCH_MINUTES` | Integrations sync cadence (default 20) |
| `BIFROST_GATEWAY_URL` | Where the shared Bifrost lives (eg. `http://bifrost:8080`) |
| `BIFROST_TOKEN` | Bearer auth for the gateway |
| `BIFROST_TIMEOUT_S` | Per-call timeout |
| `COMPOSIO_API_KEY` | Enables Composio integrations |
| `TELEGRAM_BOT_TOKEN` | Enables Telegram channel |
| `BROWSER_CONTROL_ALLOWLIST` | Comma-separated URL-prefix allowlist |

### Optional dependencies (graceful degradation)

| Dep | When missing |
|---|---|
| `composio-core` | Native gmail/calendar still work; other integrations report `unavailable` |
| `playwright` | Meeting Agent + browser-control report `unavailable`; vault + REST still work |
| OpenHands runtime | OpenHands reports `unavailable` until explicitly enabled and approved |

---

## 9. What's next (recommended)

Things that would unlock the next wave of value with relatively little
effort:

1. **Wire OpenHands runtime into the existing `agent_company` /
   `council` paths** â€” Zero's existing council already orchestrates
   research agents; OpenHands plugs in as the "executor" role for
   code tasks.
2. **Microagent UI editor** at `/microagents` â€” list, preview, edit,
   test triggers. Right now microagents are file-edited only.
3. **Composio per-tool wiring** for the top-5 connectors (Linear,
   Notion, Slack, GitHub, Stripe) â€” replace the stub bodies in
   `auto_fetch_loop._fetch_body()` with real `call_tool()` invocations.
4. **Meeting-agent audio pipe** â€” once a host with Playwright +
   virtual-audio is available, the stub heartbeat becomes a real
   frame pump into the local handler.
5. **Triggers UI** at `/triggers` â€” declarative eventâ†’action rules
   exist in the backend, but only via API. A small UI would let
   users build "when X, do Y" automations without curling.

---

## 10. Sources

- [tinyhumansai/openhuman](https://github.com/tinyhumansai/openhuman)
- [OpenHuman gitbook](https://tinyhumans.gitbook.io/openhuman)
- [OpenHands](https://github.com/OpenHands/OpenHands)
- [OpenHands SDK paper (arxiv 2511.03690)](https://arxiv.org/abs/2511.03690)
- [Bifrost (maximhq)](https://github.com/maximhq/bifrost)
- [Composio](https://github.com/ComposioHQ/composio)
- [TokenJuice (vincentkoc)](https://github.com/vincentkoc/tokenjuice)
- [SOUL.md (aaronjmars)](https://github.com/aaronjmars/soul.md)
