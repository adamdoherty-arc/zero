# Reachy Integration Ideas

Cross-dimension interweavings and upstream pickups. Every idea has a state (`hot` → `warm` → `cold` → `archived`) that ages one step per audit unless actioned. `[PINNED]` tags prevent aging. An idea that survives 3 audits without being actioned ages `hot → warm`; 3 more gets it to `cold`; 3 more archives it.

## Interweavings (hot)

### II-010: Persona-scoped motion sequences
- **Dimensions touched**: 1 (Motion) + 3 (Persona)
- **Idea**: Pair `reachy_sequence_service` (user-defined clip chains) with persona metadata — each persona can own a `signature_sequences: list[str]` registry so `cosmic_kitchen` opens with its own "entering orbit" chain while `noir_detective` plays a slow brooding intro. Sequence resolver already shares namespace with emotions/dances.
- **Min code delta**: 40 LOC — extend `reachy_sequence_service` with `persona_id` foreign key, load on persona switch, auto-play an `on_greeting` sequence.
- **Why**: Sequences become persona identity, not just generic user creations.
- **Blocking dep**: none. Sequence service already exists (uncommitted).
- **Effort**: S.
- **State**: hot.  _(Filed 2026-04-23; still hot.)_

### II-011: Realtime → router fallback for cost control
- **Dimensions touched**: 2 (Voice) + 6 (Environment)
- **Idea**: `reachy_chat_provider` already lets the user flip between vLLM / Gemini / Kimi. Pair with new `reachy_realtime` config so a single setting (`voice_mode = realtime | chunked`) picks streaming vs chunked at runtime. Useful when realtime cost spikes or offline.
- **Min code delta**: 30 LOC — one config field + a guard at the top of `voice_loop_service.process_voice_input` that short-circuits to the realtime WS when enabled.
- **Why**: Keeps the low-cost chunked path alive as fallback; makes realtime opt-in per session.
- **Blocking dep**: none.
- **Effort**: S.
- **State**: hot.  _(Filed 2026-04-23; still hot.)_

### II-012: Head wobbler on chunked TTS too
- **Dimensions touched**: 1 + 2
- **Idea**: `head_wobbler.py` currently lives inside `reachy_realtime/`. Extract it as a shared service so the chunked voice loop feeds it the TTS WAV frames before playback — robot sways during chunked speech too, not only realtime.
- **Min code delta**: 50 LOC — move the wobbler up to `reachy_motion_sway.py`, call from `voice_loop_service` when TTS starts.
- **Why**: Unifies "robot looks alive while speaking" across both voice paths.
- **Blocking dep**: none.
- **Effort**: S.
- **State**: hot.  _(Filed 2026-04-23; still hot.)_

### II-013: Persona-scoped tool grants (NEW 2026-04-24)
- **Dimensions touched**: 2 (Voice) + 3 (Persona) + 6 (Environment via Gmail/scheduler actions)
- **Idea**: The new `backend/app/data/reachy_profiles/*/tools.txt` file already names per-persona tool allowlists. Wire it into `voice_intent_router` so `victorian_butler` can read emails but NOT delete (deletion is destructive and formal); `hype_bot` can start radio but NOT touch Gmail (keeps the silly persona sandboxed); `noir_detective` can do email triage but in a low-light TTS voice. Each intent resolution checks the active persona's `tools.txt` before dispatching.
- **Min code delta**: 60 LOC — loader in `reachy_personas.py` that reads `data/reachy_profiles/{persona_id}/tools.txt`, a `has_tool(persona_id, tool_name)` helper, and a guard in `voice_intent_router.route_intent` that returns `ACTION_DENIED` when the active persona lacks the grant. Plus a fallback message the LLM can speak ("I'd rather not do that in this mood.").
- **Why**: The infrastructure is already in the tree (all 16 personas have `tools.txt`). Hook it up and the system becomes safer and characterful simultaneously. Prevents "cosmic_kitchen" from emptying your inbox by accident.
- **Blocking dep**: REQ-002 needs to land first (that's where `voice_intent_router` lives).
- **Effort**: S.
- **State**: hot.

### II-014: Composable prompt fragments (NEW 2026-04-24)
- **Dimensions touched**: 3 (Persona)
- **Idea**: `backend/app/data/reachy_prompts_library/` already hosts `identities/basic_info.txt`, `identities/witty_identity.txt`, `behaviors/silent_robot.txt`, `default_prompt.txt`, `passion_for_lobster_jokes.txt`. Let personas reference these fragments with `{{identity:witty_identity}}` / `{{behavior:silent_robot}}` tokens in `instructions.txt`, resolved at load time. Runtime rotation can then mix identity + behavior fragments (e.g. "witty identity + silent robot = Mr. Bean mode").
- **Min code delta**: 40 LOC — add a `resolve_prompt_fragments(text)` preprocessor in `reachy_personas.py` called when profile is loaded. Build out 3–5 more identity + behavior fragments.
- **Why**: Ships a real compose-from-pieces prompt system without an editor UI. Future: let users save fragment combos as named "moods".
- **Blocking dep**: none, once `reachy_profiles/` lands on main.
- **Effort**: S.
- **State**: hot.

### II-015: host_agent wake word → email triage (NEW 2026-04-24)
- **Dimensions touched**: 2 (Voice) + 4 (Presence)
- **Idea**: `host_agent/whisper_wake_loop.py` continuously scans for "hey zero" on the Reachy mic. Combined with REQ-002 email voice triage, this means: new email arrives → Reachy speaks "from X about Y, read or ignore?" → user says "hey zero read it" → the wake loop catches that exact phrase, routes it to `/api/reachy/email/voice-input` without any PTT button press. Hands-free end-to-end.
- **Min code delta**: 50 LOC — `whisper_wake_loop.py` currently POSTs to `/api/reachy-intent`. Add a mode that, if `email_voice_session_service.is_active()`, routes the post-wake utterance to the session endpoint instead. Plus a config flag `ZERO_REACHY_HANDSFREE=true`.
- **Why**: Moves Reachy from "appliance waiting for button presses" to "ambient assistant waiting for its name." Biggest single UX upgrade this audit has surfaced.
- **Blocking dep**: REQ-002 landed + host_agent landed. Both currently uncommitted.
- **Effort**: S–M (more about plumbing than novelty).
- **State**: hot.

## Interweavings (warm)

_Aged from hot this audit because they've survived 3 audit cycles since 2026-04-22 without being actioned. If you want one to stay hot, add `[PINNED]` to its header._

### II-001: Auto-persona-by-time-of-day
- **Dimensions touched**: 3 + 6
- **Idea**: Context service already reports `morning/afternoon/evening/night`. Add a rule that auto-switches persona when the time bucket changes.
- **Min code delta**: 20 LOC in `voice_loop_service._get_llm_response`; consult `reachy_persona_state` to avoid rotating a manually-selected persona.
- **Effort**: S. **State**: warm.

### II-002: Meeting-mode persona swap
- **Dimensions touched**: 3 + 5
- **Idea**: When meeting mode starts, snapshot current persona and switch to a meeting-appropriate one.
- **Min code delta**: 25 LOC in `reachy_presence_service.start_meeting_mode/stop_meeting_mode`, plus a `meeting_mode_personas: dict[str, str]` config.
- **Effort**: S. **State**: warm.  _Linked to REQ-001 handoff; if REQ-001 starts, this is the first target — promote to hot at that time._

### II-003: Nod on meeting-transcript highlight
- **Dimensions touched**: 5
- **Idea**: Hook a highlight detector to transcript segments, fire `understanding1` on match.
- **Min code delta**: 80 LOC: new `meeting_highlight_service.py` subscribing to transcript WebSocket.
- **Blocking dep**: need WebSocket subscription plumbing. `host_agent/live_transcription.py` now provides this as a broadcast source — the blocker is weaker as of 2026-04-24. Could promote back to hot if the connection is wired.
- **Effort**: M. **State**: warm.

### II-004: HA "arrived home" → morning briefing
- **Dimensions touched**: 4 + 6
- **Blocking dep**: HA gesture-map file needs configuring.
- **Effort**: S. **State**: warm.

### II-005: Radio mode + Spotify now-playing
- **Dimensions touched**: 1 + 6
- **Blocking dep**: Spotify API credentials.
- **Effort**: M. **State**: warm.

### II-006: Calendar-imminent → persona warn
- **Dimensions touched**: 3 + 6
- **Min code delta**: 10 LOC — tighten existing hint in `reachy_context_service`.
- **Effort**: XS. **State**: warm.  _XS effort should be nominated for hot if unactioned for 1 more audit — it's literally free._

### II-007: Per-persona TTS voice config
- **Dimensions touched**: 2 + 3
- **Min code delta**: 30 LOC: load JSON in `voice_loop_service`, look up active persona's voice, pass to `reachy.say(..., voice_override=...)`.
- **Blocking dep**: none (`voice_override` is shipped in REQ-002, still uncommitted).
- **Effort**: S. **State**: warm.

### II-008: Gmail Pub/Sub webhook for real-time email arrival
- **Dimensions touched**: 4 + 2
- **Blocking dep**: Cloud project + public URL.
- **Effort**: M. **State**: warm.

## Interweavings (cold)

### II-009: Respond-as-persona
- **Dimensions touched**: 2 + 3
- **Effort**: S. **State**: cold (aged from warm; depends on II-007 which is itself warm).  _Next audit → archived unless II-007 gets traction._

## Upstream pickups (hot)

### UP-007: `itsMarco-G/reachy_phone_home` — Phone focus companion (NEW 2026-04-24)
- **Source**: HF Space, **349 likes** (highest-rated Reachy Mini community app).
- **Dimensions touched**: 4 (Presence) + 6 (Environment)
- **Why it's interesting**: A focus-session companion that pairs a phone with Reachy. Design patterns to learn: session framing, notification suppression, ambient focus state. Adjacent to Zero's pomodoro but with a phone pairing layer.
- **What to lift**: The UX pattern (start focus → Reachy goes quiet → end focus → Reachy celebrates). Probably not direct-port, more study-for-inspiration.
- **Effort**: M (pattern lift, not code port). **State**: hot.

### UP-008: `ravediamond/baby-reachy-mini-companion` — Fully-local companion (NEW 2026-04-24)
- **Source**: HF Space, **165 likes**.
- **Dimensions touched**: 2 (Voice) + 3 (Persona)
- **Why it's interesting**: Fully-local AI companion for babies/kids. Relevant to a privacy-first / offline persona mode for Zero. Could also seed a child-safe persona preset (`reachy_profiles/kid_friendly/`).
- **What to lift**: Local-first architecture patterns + child-safe content filters. Again, study-for-inspiration.
- **Effort**: M. **State**: hot.

### UP-009: `RemiFabre/marionette` — Manual guide + motion+sound capture (NEW 2026-04-24)
- **Source**: HF Space, 16 likes, last mod **2026-04-23** (very fresh).
- **Dimensions touched**: 1 (Motion)
- **Why it's interesting**: Extends the "manual pose capture" pattern (which Zero already has via `reachy_move_recorder`) with **synchronised audio capture**. Record a motion while narrating, play both back together.
- **What to lift**: The audio-track alignment technique. Would upgrade Zero's move recorder from silent gestures to narrated scenes.
- **Effort**: M. **State**: hot.

### UP-010: `backtoengineering/reachy_mini_object_detector` — Real-time object detection + head tracking (NEW 2026-04-24)
- **Source**: HF Space, 1 like, last mod 2026-04-20 (fresh).
- **Dimensions touched**: 6 (Environment) + 5 (Meeting) stretch
- **Why it's interesting**: Head tracks an object in frame. Low likes count but concept is directly useful for meeting mode ("look at who's raising their hand") and for teleop ("look at the object I'm manipulating").
- **What to lift**: The object detector model choice + the head-tracking control loop.
- **Effort**: M. **State**: hot.

### UP-003: Wake word via Porcupine / openwakeword
- **Source**: `fcollonval/reachy_mini_wake_word` + `luisomoreau/hey_reachy_wake_word_detection`
- **Dimensions touched**: 2
- **Status**: **Partially overtaken by events.** `host_agent/whisper_wake_loop.py` already implements a Whisper-based variant in-tree. UP-003 upstream reference is the Porcupine path. If the Whisper variant works well in practice, UP-003 can archive. If latency/accuracy are inadequate, install `openwakeword + onnxruntime` per this entry.
- **Effort**: S install + S frontend always-on mode.
- **State**: hot.  _(3rd audit in hot; promoting now likely.)_

## Upstream pickups (warm)

### UP-004: Full 3D puppet via `8bitkick/reachy_mini_3d_web_viz`
- **Source**: HF Space, 24 likes.
- **Dimensions touched**: 1 + 6 (frontend).
- **Effort**: M. Bundle +~300 KB.
- **State**: warm (aged from warm; no new signal).

### UP-005: MediaPipe Tasks migration
- **Dimensions touched**: 6.
- **Effort**: M. **State**: warm (aged; works today, no deadline).

## Upstream pickups (cold)

_(none yet.)_

## Archived (shipped or obviated)

### UP-001: Streaming voice loop — SHIPPED as OpenAI Realtime + Gemini Live
- **Landing**: `backend/app/services/reachy_realtime/` (uncommitted), `reachy-mic-worklet.js`, `ReachyRealtimeSettings.tsx`.
- **Status**: archived-pending-commit. Will fully archive once commits land.

### UP-002: Move recorder from `reachy_mini_toolbox/moves/recorder.py`
- **Landing**: Zero's `reachy_move_recorder.py` is the REST-adapted version.
- **State**: archived.

### UP-006: Speech-reactive head wobbler — HARVESTED
- **Landing**: `reachy_realtime/head_wobbler.py`.
- **State**: archived-pending-commit.

## Aging rules

On each audit:
1. Any `hot` idea not actioned and past its 3rd audit ages to `warm`.
2. Any `warm` idea not actioned and past its 3rd audit ages to `cold`.
3. Any `cold` idea not actioned and past its 3rd audit archives to `history/ideas_archive.md`.
4. `[PINNED]` ideas never age.
5. Actioning an idea = opening a `planned` entry in `REQUESTS_LOG.md` referencing it. The audit then links them and freezes the idea's age at its current tier.
