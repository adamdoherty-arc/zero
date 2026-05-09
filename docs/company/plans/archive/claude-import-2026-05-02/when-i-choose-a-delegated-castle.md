# Reachy Motion Library: from bare-bones to a robot that feels alive

## Context

The Reachy Motion Library page looks capable but is broken where it counts.

Concretely:
- **"Hold to talk" is dead**: the button sits on "Thinking..." forever. Root cause is a stack of missing timeouts: `frontend/src/pages/ReachyMotionLibraryPage.tsx:80` fetches `/api/reachy/voice` with no `AbortController`; `backend/app/services/voice_loop_service.py:268-315` has no `asyncio.wait_for` around the LLM call; any slow provider (Ollama, Kimi, edge-tts cold start) hangs the whole turn. The user also gets no visibility into *which* stage is stalled.
- **Persona picker has no way to hear the persona**. All 12 personas use the same voice (no `voice` field on the `Persona` dataclass), and there is no preview endpoint.
- **Everything on the page is siloed**. Persona, modes (pomodoro / meeting / context hint), emotion library, sequences, and daemon status are separate cards with no crosstalk. The context hint block just displays static strings.
- **Nothing learns between turns**. Persona stats count uses, but Reachy has no memory of *what* you talked about, preferences, or corrections. Every conversation starts from zero.
- **Robot never feels present**. No listening posture when you hold the mic. No live wobble while TTS plays. Emotions fire silently — user has no feedback that Reachy reacted.

The user wants this page to feel like a robot they can actually talk to — context-aware, emotional, continuously improving. The fixes are narrow (6 concrete surfaces) but interdependent; doing only the voice-loop timeout leaves the page feeling as bare as before.

Per project rule ([c:\code\zero\CLAUDE.md](c:\code\zero\CLAUDE.md) "Finish what you start"), this lands as one push, all phases, with Docker rebuild + verification at the end.

---

## Critical files

### Backend (Python, rebuild required)
- [backend/app/services/voice_loop_service.py](backend/app/services/voice_loop_service.py) — add timeouts + phase reporting
- [backend/app/services/reachy_personas.py](backend/app/services/reachy_personas.py) — add `voice` + `preview_line` + `signature_gesture` fields
- [backend/app/services/reachy_user_memory_service.py](backend/app/services/reachy_user_memory_service.py) — NEW, cross-session memory
- [backend/app/routers/reachy.py](backend/app/routers/reachy.py) — add `/personas/{id}/preview`, `/memory/*`, harden `/voice`
- [backend/app/services/tts_service.py](backend/app/services/tts_service.py) — already supports `voice_override`, verify edge-tts voice list
- [backend/app/services/reachy_service.py:512](backend/app/services/reachy_service.py#L512) — `say()` already exists; wire preview through it when robot connected

### Frontend (volume-mounted, restart only; no rebuild unless new npm pkgs)
- [frontend/src/pages/ReachyMotionLibraryPage.tsx](frontend/src/pages/ReachyMotionLibraryPage.tsx) — the page, gets a significant overhaul
- [frontend/src/hooks/useReachyApi.ts](frontend/src/hooks/useReachyApi.ts) — add `usePersonaPreview`, `useUserMemory`, `useVoiceTurn` (streaming phases)
- [frontend/src/components/reachy/DaemonPanel.tsx](frontend/src/components/reachy/DaemonPanel.tsx) — keep, minor styling alignment
- [frontend/src/components/reachy/SequenceBuilder.tsx](frontend/src/components/reachy/SequenceBuilder.tsx) — keep, add "play this sequence as intro when I switch to persona X" affordance (ties into II-010)

---

## Plan

### Phase 1 — Make hold-to-talk actually work

**Backend** [backend/app/services/voice_loop_service.py](backend/app/services/voice_loop_service.py):
- Wrap STT call (`audio_service.transcribe_upload`, line 105) in `asyncio.wait_for(..., timeout=15)`
- Wrap `chat_service.chat` and `unified_llm_client.chat` (lines 289, 304) in `asyncio.wait_for(..., timeout=20)`
- Wrap `tts_service.synthesize` (line 204) in `asyncio.wait_for(..., timeout=10)`
- On timeout at any stage, return a structured `{stage: "stt"|"llm"|"tts", error: "timeout"}` plus a canned fallback TTS line ("I'm having trouble thinking right now — try again?") so the user *hears* the failure instead of watching a spinner.
- Add `phase_log: list[{phase, ms}]` to every voice-turn response so the frontend can show timing.

**Backend** [backend/app/routers/reachy.py:890](backend/app/routers/reachy.py#L890):
- Wrap the whole `voice_service.process_voice_input` call in a 45 s outer `asyncio.wait_for` as a last-line backstop.

**Frontend** [frontend/src/pages/ReachyMotionLibraryPage.tsx:45-147](frontend/src/pages/ReachyMotionLibraryPage.tsx#L45):
- Replace the bare `fetch` with an `AbortController` + 50 s timeout. On abort → reset `busy`, toast the stage that stalled.
- Replace the single "Thinking…" with a 3-step indicator: **Listening → Transcribing → Thinking → Speaking**. Bind to `payload.phase_log`.
- Surface `lastResult.phase_log` as collapsible debug chips ("stt 0.4s • llm 1.2s • tts 0.6s") so the user can see why a turn feels slow.
- Render `lastResult.gesture_actions` as badges under the transcript ("played [emotion:thoughtful1]"). Already in payload; just not displayed.

### Phase 2 — Persona voice preview

**Backend** [backend/app/services/reachy_personas.py](backend/app/services/reachy_personas.py):
- Extend `Persona` dataclass with optional `voice: str | None` (edge-tts voice name like `"en-US-GuyNeural"`) and `preview_line: str | None` and `signature_gesture: str | None` (a clip name from the motion library).
- Assign voice + preview line + signature gesture for all 12 personas. Examples:
  - `bored_teenager` → voice `en-US-AshleyNeural`, preview `"ugh… you want me to say something? fine. hi."`, gesture `reluctant_wave`
  - `noir_detective` → voice `en-US-EricNeural`, preview `"The dame walked in. Trouble followed. Name's Reachy."`, gesture `thoughtful1`
  - `cosmic_kitchen` → voice `en-US-JennyNeural`, preview `"Gravity's a suggestion in my kitchen. What do you want burnt?"`, gesture `sarcastic_shrug`
  - Full mapping derived from each persona's system prompt tone.
- Edge-tts voice catalog check at module load (verify all selected voices are valid; log warn + fall back to default if not).

**Backend** [backend/app/routers/reachy.py](backend/app/routers/reachy.py):
- New `POST /api/reachy/personas/{persona_id}/preview` that:
  1. Looks up persona → `preview_line` + `voice`
  2. Calls `tts_service.synthesize(line, voice_override=voice)` (3 s timeout)
  3. If robot connected: fires `signature_gesture` via `reachy_service.play_emotion` (parallel, don't await)
  4. Returns `{audio_b64, line, gesture}`

**Frontend** [frontend/src/pages/ReachyMotionLibraryPage.tsx:149-191](frontend/src/pages/ReachyMotionLibraryPage.tsx#L149):
- Add a speaker button next to the persona dropdown. On click:
  - Plays the preview WAV in the browser
  - Shows the preview line in small text below the tagline ("🔊 The dame walked in. Trouble followed. Name's Reachy.")
  - Shows "also played: thoughtful1" if robot connected

### Phase 3 — Make the robot feel present

**Listening posture**: when `PushToTalk.start()` fires, kick off a fire-and-forget call to `/api/reachy/emotion` with a short "attentive" clip (e.g. `listening1` or head tilt toward mic). Already have `attentive1`/`thoughtful1` in the library — verify via `get_motion_library()` and pick one.

**Speaking wobble**: in `voice_loop_service` after TTS starts playing on the robot, fire a lightweight sway pattern via `reachy_service.play_emotion("head_bob_light")` or similar — reuses the existing head-wobbler idea from [INTEGRATION_IDEAS.md II-012](.claude/skills/zero-reachy-audit/knowledge/INTEGRATION_IDEAS.md). This is important for `/voice` PTT flow since realtime streaming already has wobble.

**LLM prompt reinforcement**: extend `build_full_prompt` to always append a one-paragraph rubric ("Use `[emotion:name]` or `[dance:name]` markers when emotion is warranted. See reachy_motion_library for valid names.") so the LLM actually uses gestures. Currently some personas never emit markers — makes Reachy feel flat.

**Recent emotions strip** (frontend, new component): small row above the motion library grid showing the last 5 clips fired (with timestamp), clickable to replay. Data source: new `GET /api/reachy/motion/recent` that tails `reachy_persona_state`'s existing clip log.

### Phase 4 — Visible context

Currently [reachy_context_service.py](backend/app/services/reachy_context_service.py) builds rich context (time of day, pomodoro phase, meeting flag, next calendar event within 30 min, imminent event if < 5 min) but it's only injected into the LLM prompt — **invisible to the user**.

Replace the static "CONTEXT HINT" card with a live "What Reachy knows right now" card:
- New endpoint `GET /api/reachy/context/debug` that returns the structured context dict (not just the formatted string)
- Frontend polls every 30 s. Shows each fact as a chip: 🕒 "Friday afternoon", 🎯 "Pomodoro: focus (18m left)", 📅 "Next: Team sync in 12m", 🤝 "Meeting mode", 💬 "User likes short replies" (from memory, see Phase 5).
- Chips fade in/out as context changes. Gives a transparent sense that Reachy is paying attention.

### Phase 5 — Cross-session learning

This is the biggest payoff and the feature that turns "toy" into "companion".

**New service** [backend/app/services/reachy_user_memory_service.py](backend/app/services/reachy_user_memory_service.py):
- JSON-backed store at `workspace/reachy/user_memory.json`. Schema:
  ```python
  {
    "turns": [{ts, persona_id, user_text, reachy_text, gestures: [...]}, ...],  # last 500
    "notes": [{id, category, text, confidence, learned_at, last_used_at, uses: int}, ...],
    "stats": {total_turns, per_persona: {...}, topics_frequency: {...}}
  }
  ```
- Categories: `preference` (user likes brief replies), `fact` (user has a cat named Miso), `correction` (user corrected "hey man" — prefers more formal address), `topic` (user often asks about X).
- `async def log_turn(persona_id, user_text, reachy_text, gestures)` called from `voice_loop_service` after each successful turn.
- `async def extract_notes(recent_turns)` — runs every 5 turns. Calls the **light** Kimi model (`moonshot-v1-32k` per [MEMORY.md](C:\Users\hadam\.claude\projects\c--code-zero\memory\MEMORY.md) — $0.024/1M, matches "Kimi plans, Gemma executes" pattern). Single structured-output call: *"Given these 5 turns, extract 0-3 durable notes the robot should remember about the user. Return JSON array of {category, text, confidence}."* Keeps a 50-note cap; dedupe against existing by semantic similarity (simple embedding cosine — reuse pgvector already in project).
- `async def relevant_notes(user_text, k=5)` — returns top-5 notes by embedding similarity to current user input. Used to inject into system prompt.

**Wire into voice loop** [backend/app/services/voice_loop_service.py](backend/app/services/voice_loop_service.py):
- After `_get_llm_response` completes successfully: `await memory.log_turn(...)`.
- In `_get_llm_response` before building prompt: prepend top-5 relevant notes as `### WHAT YOU REMEMBER ABOUT THIS USER\n- ...`.
- Extract notes (non-blocking `asyncio.create_task`) every 5 turns.

**Scheduler job** [backend/app/services/scheduler_service.py](backend/app/services/scheduler_service.py):
- `reachy_memory_compact` every 6 h: re-run extraction on the last 100 turns, dedupe, age out low-confidence unused notes (uses < 2 AND learned > 7 days ago).

**Router** [backend/app/routers/reachy.py](backend/app/routers/reachy.py):
- `GET /api/reachy/memory` — returns `{notes, stats}`
- `DELETE /api/reachy/memory/notes/{id}` — user can prune bad notes
- `POST /api/reachy/memory/notes` — user can manually add "remember that I prefer X"

**Frontend** — new section "What Reachy remembers about you":
- Lists current notes grouped by category (preferences, facts, corrections, topics)
- Each note has a ✕ delete button
- Text input to manually teach: "Remember that I prefer British spelling"
- Counter: "Reachy has had 42 conversations with you and learned 8 things"

### Phase 6 — Page layout audit and polish

The current layout (per the screenshot) has 5+ disconnected cards. Reorganise so every section earns its place:

**New page structure** (top to bottom):

1. **Header row** — title (81 emotions · 19 dances) + connection badge + Wake/Sleep/Stop. Keep.
2. **Presence card** (NEW consolidation) — combines daemon status, "What Reachy knows right now" context chips, and persona picker + preview button into one strip. Shows at a glance: "online, alert, noir detective, knows it's afternoon and you're in a meeting".
3. **Talk strip** — hold-to-talk button, 4-phase indicator, last transcript, gesture badges, timing chips. Same component but vastly more feedback.
4. **Memory card** (NEW) — "Reachy remembers" with notes + stats + manual teach input.
5. **Modes card** — pomodoro, meeting, "add context hint". Keep but tighten: the 3 sub-panels should be equal-width, no more 2-line descriptions that cost space.
6. **Sequences card** — MY SEQUENCES. Keep builder. Add "set as signature intro for persona: [dropdown]" so sequences become persona-scoped intros (II-010).
7. **Recent activity strip** (NEW) — last 5 emotions/dances fired with timestamps, clickable to replay.
8. **Motion library grid** — unchanged logic, but each tile gets a ⭐ favourite button (stored in user_memory as `preference` notes, so Reachy knows which you prefer).

**Remove dead space**: CONTEXT HINT box and PersonaStatsPanel (currently at [ReachyMotionLibraryPage.tsx:513-551](frontend/src/pages/ReachyMotionLibraryPage.tsx#L513)) fold into the new Presence and Memory cards.

### Phase 7 — Meeting mode wiring (bundled because user said "combine all these features")

Meeting mode currently just flips a boolean and injects a "keep replies short" hint. Make it a real mode:

- **Auto persona swap** on `POST /presence/meeting/start`: save current persona, switch to a new meeting-appropriate persona (`attentive_colleague` — NEW, add to persona catalog: quiet, professional, short replies). On stop, restore previous persona.
- **Idle animations**: `reachy_presence_service` already runs a meeting loop — add idle fidgets (head wiggle, antenna flutter) every 30-60 s of speech silence. Use existing clips `thoughtful1`, `attentive1`.
- **DoA indicator** in frontend: poll `reachy_vision_service` for current gaze direction, show "👀 looking right" chip in the meeting panel.

---

## Verification

### Automated
1. `docker compose -f docker-compose.sprint.yml build --no-cache zero-api && docker compose -f docker-compose.sprint.yml up -d zero-api` — rebuild backend (CLAUDE.md rule: backend is COPY'd).
2. Frontend has no new npm deps → `docker compose -f docker-compose.sprint.yml restart zero-ui`.
3. `docker ps --format "table {{.Names}}\t{{.Status}}" | grep zero` → both healthy.
4. `docker logs zero-api --tail 200 | grep -iE "error|fail|traceback"` → no startup errors.
5. Run existing test suite: `docker exec zero-api pytest backend/tests -k reachy -x` → green.

### Manual (in browser at http://localhost:5173/reachy)

**Phase 1 (hold-to-talk)**:
- Click hold-to-talk, say "hello". Should see **Listening → Transcribing → Thinking → Speaking** advance, then transcript + reply appear. Phase chips show timing.
- Stop the LLM provider (`docker stop ollama` or break Kimi key) → should fail with a **stage-specific toast** within ~20 s (not hang forever) and reset the button.

**Phase 2 (persona preview)**:
- Change persona to each of the 12, click the speaker button. Each persona should use a **different voice** and play a **different preview line**. With robot connected, a signature gesture fires too.

**Phase 3 (feel present)**:
- Hold-to-talk → robot physically tilts toward mic on press.
- During reply → robot does small sway.
- Last transcript shows a gesture badge like "🎭 thoughtful1".

**Phase 4 (context)**:
- Context chips appear: time, pomodoro (after `/presence/pomodoro/start`), meeting (after meeting toggle), next calendar event (if any).
- Start pomodoro → chip updates within 30 s.

**Phase 5 (memory)**:
- Have 5 turns about a topic. Memory card populates with a note like "User is interested in X".
- Say "Remember I prefer one-sentence replies" → note appears with category `preference`.
- Next turn → LLM honours the preference. Verify in `docker logs zero-api` that `### WHAT YOU REMEMBER` prefix appears in logged prompt.
- Delete a note → confirm it stops being injected.

**Phase 6 (layout)**:
- Visual sweep: every section has a purpose, nothing is duplicated, nothing is static placeholder text.
- Mobile viewport (1080×720): everything stacks cleanly, no horizontal scroll.

**Phase 7 (meeting)**:
- Toggle meeting mode → persona swaps to `attentive_colleague`, DoA chip appears, idle fidgets every ~45 s of silence.
- Stop meeting → persona restores.

### Sanity
- `GET /api/reachy/personas` shows all 12 with new `voice` + `preview_line` + `signature_gesture` fields populated.
- `GET /api/reachy/memory` returns notes + stats.
- `GET /api/reachy/context/debug` returns the structured context object.
- `POST /api/reachy/personas/cosmic_kitchen/preview` returns WAV audio + gesture name.

---

## Out-of-scope (deliberate)

- Realtime streaming voice (OpenAI / Gemini) — already shipped separately per REQ-002, handled by FloatingVoiceButton, not this page.
- Wake word integration — lives in `host_agent`, not the web UI.
- Camera vision on this page — exists via MJPEG endpoint but belongs on a different surface.
- PAD (Pleasure/Arousal/Dominance) emotion blending from Feeling Machine — interesting but a week of work; filed as separate integration idea, not this push.
