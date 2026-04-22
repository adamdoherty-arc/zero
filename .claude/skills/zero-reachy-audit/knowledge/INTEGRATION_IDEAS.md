# Reachy Integration Ideas

Cross-dimension interweavings and upstream pickups. Every idea has a state (`hot` → `warm` → `cold` → `archived`) that ages one step per audit unless actioned. `[PINNED]` tags prevent aging.

## Interweavings (hot)

### II-001: Auto-persona-by-time-of-day
- **Dimensions touched**: 3 (Persona) + 6 (Environment via context service)
- **Idea**: Context service already reports `morning/afternoon/evening/night`. Add a rule that auto-switches persona when the time bucket changes — e.g., `cosmic_kitchen` weekday mornings, `victorian_butler` evenings, `hype_bot` during a pomodoro focus phase.
- **Min code delta**: 20 LOC in `voice_loop_service._get_llm_response` before building the full prompt; consult `reachy_persona_state` to avoid rotating a manually-selected persona.
- **Why**: Makes Reachy feel situationally aware without user intervention.
- **Blocking dep**: none.
- **Effort**: S
- **State**: hot

### II-002: Meeting-mode persona swap
- **Dimensions touched**: 3 + 5
- **Idea**: When meeting mode starts, snapshot current persona and switch to a meetings-appropriate one (e.g., `victorian_butler` for formal meetings, `noir_detective` for 1:1s by keyword match on meeting title). Restore on meeting stop.
- **Min code delta**: 25 LOC in `reachy_presence_service.start_meeting_mode/stop_meeting_mode`, plus a `meeting_mode_personas: dict[str, str]` config.
- **Why**: Keeps cosmic_kitchen out of serious meetings.
- **Blocking dep**: none.
- **Effort**: S
- **State**: hot

### II-003: Nod on meeting-transcript highlight
- **Dimensions touched**: 5 (Meeting Mode)
- **Idea**: `meeting_transcription_service` emits segments; hook a highlight detector (keyword list + LLM-classified "agreement marker") that triggers `understanding1` when a highlight fires.
- **Min code delta**: 80 LOC: new `meeting_highlight_service.py` subscribing to transcript WebSocket, calls `play_emotion("understanding1")` on match.
- **Why**: Reachy physically acknowledges when important things are said.
- **Blocking dep**: Need WebSocket subscription plumbing — check if `meeting_ws.py` exposes a consumer API.
- **Effort**: M
- **State**: hot

### II-004: HA "arrived home" → morning briefing
- **Dimensions touched**: 4 + 6
- **Idea**: HA watcher fires `welcoming1` when `person.<user>` → `home`. Chain it to Zero's briefing_service to speak today's agenda.
- **Min code delta**: HA rule entry + a service that calls `briefing_service.get_morning_briefing()` then `reachy_service.say()`.
- **Why**: Walk in the door → Reachy greets + summarizes.
- **Blocking dep**: HA gesture-map file needs configuring.
- **Effort**: S
- **State**: hot

### II-005: Radio mode + Spotify now-playing
- **Dimensions touched**: 1 + 6
- **Idea**: Zero reads Spotify's "now playing" BPM from an API/webhook, auto-starts radio mode at that BPM, switches on song change.
- **Min code delta**: New `spotify_service.py` client + a scheduler job polling every 30s; on BPM change, call `reachy_radio_service.start(bpm)`.
- **Why**: Reachy becomes a reactive dance partner for whatever's playing.
- **Blocking dep**: Spotify API credentials (if user has premium) or Sonos / generic audio-fingerprint fallback.
- **Effort**: M
- **State**: hot

### II-006: Calendar-imminent → persona warn
- **Dimensions touched**: 3 + 6
- **Idea**: Context service already flags "meeting starts in <5 min". When imminent, append to prompt: *"User's next meeting is in N minutes — proactively remind them if topic comes up."* Already half-wired in `reachy_context_service`.
- **Min code delta**: 10 LOC — tighten the existing hint to include action guidance.
- **Why**: Reachy proactively nudges without being asked.
- **Blocking dep**: none.
- **Effort**: XS
- **State**: hot

## Interweavings (warm)

_(none — first audit. Ideas age to warm after 1 unactioned audit.)_

## Interweavings (cold)

_(none.)_

## Upstream pickups (hot)

### UP-001: Streaming voice loop (Voxtral + Parakeet)
- **Source**: `pollen-robotics/reachy-mini-chatbox` (Mac-only on-device pipeline: Voxtral-Mini-4B-Realtime + Parakeet TDT + Kokoro TTS + SmolVLM2 + YOLO face)
- **Dimensions touched**: 2 (Voice)
- **Why**: Replaces Zero's 5-second chunked voice loop with ~200 ms streaming. Major UX upgrade.
- **Effort**: L. Needs WebSocket voice endpoint, Voxtral model download (~2 GB), streaming TTS pipe.
- **Blocking dep**: GPU on host for Voxtral inference; pipeline architecture change.
- **State**: hot

### UP-002: Move recorder from `reachy_mini_toolbox/moves/recorder.py`
- **Source**: Pollen toolbox (the official reference)
- **Dimensions touched**: 1 (Motion)
- **Status**: Already implemented — Zero's `reachy_move_recorder.py` is the REST-adapted version. Log here as `[HARVESTED]` so future audits don't suggest again.
- **State**: archived (already done)

### UP-003: Wake word via Porcupine or openwakeword
- **Source**: `fcollonval/reachy_mini_wake_word` (Space) + `luisomoreau/hey_reachy_wake_word_detection`
- **Dimensions touched**: 2
- **Status**: scaffolded in `reachy_wake_word_service.py`, not installed. Install path:  
  `.venv/Scripts/python.exe -m pip install openwakeword onnxruntime`
- **Effort**: S (install) + S (frontend always-on mode).
- **State**: hot

### UP-004: Full 3D puppet via `8bitkick/reachy_mini_3d_web_viz`
- **Source**: HF Space, 24 likes. Three.js-based.
- **Dimensions touched**: 1 + 6 (frontend surface)
- **Status**: Zero ships a CSS-3D facsimile. This would replace it with a faithful rendering.
- **Effort**: M. Adds `@react-three/fiber` + `three` + `@react-three/drei` to the bundle (~300 KB gzipped).
- **Blocking dep**: bundle-size budget decision.
- **State**: warm (not urgent; CSS puppet is adequate)

### UP-005: MediaPipe Tasks migration
- **Source**: Google; mediapipe.tasks.vision.HandLandmarker
- **Dimensions touched**: 6
- **Why**: Current hand tracker uses the deprecated `mp.solutions.hands`. Upstream is sunsetting it.
- **Effort**: M. Requires downloading `.task` file; changes the call site.
- **State**: warm (works today, no deadline).

## Upstream pickups (warm/cold)

_(none yet.)_

## Aging rules

On each audit:
1. Any `hot` idea not actioned ages to `warm`.
2. Any `warm` idea not actioned ages to `cold`.
3. Any `cold` idea not actioned moves to `archived` in `history/ideas_archive.md`.
4. `[PINNED]` ideas never age.
5. Actioning an idea = opening a `planned` entry in `REQUESTS_LOG.md` referencing it. The audit then links them and freezes the idea's age at its current tier.
