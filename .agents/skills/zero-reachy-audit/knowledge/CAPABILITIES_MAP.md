# Reachy Capabilities Map (generated 2026-04-24)

Layer-by-layer inventory of every Reachy-related surface in `c:/code/zero`. Source of truth for Phase 1 of the audit. **Do not hand-edit** — regenerate via the Explore agent brief in SKILL.md.

## Backend services (`backend/app/services/`)

| File | Purpose |
|------|---------|
| `reachy_service.py` | Daemon REST client. Motion primitives, media, volume, motors, camera, TTS say. (687 lines) |
| `reachy_motion_library.py` | 81 emotions + 19 dances catalog with alias resolver + kind-filter. (259 lines) |
| `reachy_move_recorder.py` | 50 Hz state-polling move recorder + replay via streaming `set_target`. |
| `reachy_personas.py` | 12 persona profiles + `MOTION_TAG_INSTRUCTIONS` tail. (364 lines) |
| `reachy_persona_state.py` | Per-persona interaction counters + optional auto-rotation. |
| `reachy_persona_intros_service.py` | **NEW** — runtime persona intro/greeting customization with DB persistence. |
| `reachy_user_memory_service.py` | **NEW** — per-user memory state for long-form voice sessions. |
| `reachy_emotion_parser.py` | `[emotion:..] [dance:..] [motion:..] [look:x,y,z]` parser + offset tracking. (101 lines) |
| `reachy_presence_service.py` | Pomodoro + idle watcher + hourly chime + presence beat + meeting mode (DoA look-at-speaker). (521 lines) |
| `reachy_radio_service.py` | BPM detector (librosa) + background dance dispatcher. |
| `reachy_wake_word_service.py` | Optional openwakeword wrapper (degrades to `available:false`). |
| `reachy_vision_service.py` | Face (OpenCV Haar) + hand (MediaPipe) detection with lazy imports. |
| `reachy_context_service.py` | Builds `### CURRENT CONTEXT` block from calendar + pomodoro + meeting + time. |
| `reachy_chat_provider.py` | Runtime provider selector (vLLM / Gemini / Kimi) for voice fallback, persisted. |
| `reachy_sequence_service.py` | User-defined motion-chain library, DB-backed, namespace-shared with motion library resolver. (367 lines) |
| `reachy_realtime/__init__.py` | Session lifecycle bootstrap. (36 lines) |
| `reachy_realtime/common.py` | Shared types. (112 lines) |
| `reachy_realtime/bg_tool_manager.py` | Async background tool execution with result buffering. (185 lines) |
| `reachy_realtime/tools.py` | Tool definitions for realtime LLM. (331 lines) |
| `reachy_realtime/profiles.py` | Persona-to-realtime-profile mapping. (219 lines) |
| `reachy_realtime/config_store.py` | Persists realtime session config. (135 lines) |
| `reachy_realtime/sway.py` | Body sway animation handler. (234 lines) |
| `reachy_realtime/head_wobbler.py` | Speech-reactive head wobble during TTS. (185 lines) |
| `reachy_realtime/openai_handler.py` | OpenAI Realtime API client. (532 lines) |
| `reachy_realtime/gemini_handler.py` | Google Gemini Live API client. (393 lines) |
| `reachy_realtime/session.py` | Unified session orchestrator. (345 lines) |
| `voice_bridge_service.py` | LiveKit Agents bridge scaffold (SecondBrain Phase 6). |
| `voice_intent_router.py` | Keyword + LLM-fallback intent classifier (read/ignore/delete/respond/send/cancel). (186 lines) |
| `email_voice_session_service.py` | FSM for voice email triage (REQ-002). (451 lines) |
| `meeting_auto_recorder_service.py` | Opt-in per-event auto-record (REQ-002). (148 lines) |
| `home_assistant_service.py` | HA REST client (status / states / call-service). |
| `home_assistant_watcher.py` | Polls HA entities, fires Reachy gestures on state transitions. |
| `voice_loop_service.py` | STT → persona-wrapped LLM → gesture strip → parallel dispatch → TTS. Email-session short-circuit + voice_override plumbing. (507 lines) |
| `meeting_recording_service.py` | Starts/stops Reachy meeting mode on recording start/stop. |
| `tts_service.py` | Text-to-speech wrapper (per-utterance voice override supported). |
| `gmail_service.py` | Gmail client (list/read/delete/send) for voice triage. |
| `gmail_oauth_service.py` | Gmail OAuth token lifecycle. |
| `sight/reachy_provider.py` | Reachy camera-frame SightProvider integration. |

## Backend routers (`backend/app/routers/`)

| File | Prefix | Notes |
|------|--------|-------|
| `reachy.py` | `/api/reachy` | **89 routes** (was 61 at 2026-04-23). Added sequences, chat-provider, daemon diagnostics, persona intros, motion/recent. |
| `reachy_intent.py` | `/api/reachy-intent` | Voice intent classification. |
| `reachy_email.py` | `/api/reachy/email` | REQ-002 voice email triage. |
| `reachy_realtime.py` | `/api/reachy/realtime` | Config, profiles, WS audio bridge. |
| `voice_bridge.py` | `/api/voice-bridge` | LiveKit control surface (self-prefixed). |
| `home_assistant.py` | `/api/home-assistant` | 5 routes. |

### `/api/reachy/*` surface (89 routes grouped)

**State + daemon** (12): `/status`, `/state`, `/doa`, `/health-check`, `/daemon/status`, `/daemon/start`, `/daemon/stop`, `/daemon/restart`, `/daemon/logs`, `/daemon/diagnostics`, `/daemon/audio/reset`, `/daemon/watchdog` (GET/POST).

**Motion library** (6): `/emotion`, `/dance`, `/motion/library`, `/motion/play`, `/motion/resolve`, `/motion/recent`.

**Sequences** (6): `/sequences` (GET/POST), `/sequences/{id_or_name}` (GET/PATCH/DELETE), `/sequences/{id_or_name}/play`.

**Personas** (10): `/personas`, `/personas/stats`, `/personas/stats/reset`, `/personas/{persona_id}`, `/personas/select`, `/personas/{persona_id}/intro` (GET/POST/DELETE), `/personas/{persona_id}/preview`, `/personas/intros`.

**Gestures** (1): `/gesture/parse`.

**Presence** (6): `/presence/pomodoro`, `/presence/pomodoro/start`, `/presence/pomodoro/stop`, `/presence/meeting`, `/presence/meeting/start`, `/presence/meeting/stop`.

**Move recorder** (6): `/moves/record/start`, `/moves/record/stop`, `/moves/record/status`, `/moves/user`, `/moves/user/{lib}/{name}/play`, `/moves/user/{lib}/{name}` (DELETE).

**Vision** (2): `/vision/backends`, `/vision/detect`. **Wake-word** (2): `/wake-word/status`, `/wake-word/predict`.

**Radio** (4): `/radio/status`, `/radio/start`, `/radio/stop`, `/radio/analyze`.

**Context** (1): `/context/hint`. **Chat provider** (3): `/chat-provider/status`, `/chat-provider/select`, `/chat-provider/list`.

**Audio** (8): `/say`, `/test-sound`, `/sounds`, `/sounds/upload`, `/sounds/{file}` (DELETE), `/sounds/play`, `/sounds/stop`, `/volume`, `/volume/microphone`.

**Motors** (2): `/motors`, `/motors/mode`. **Camera** (3): `/camera/specs`, `/camera/stream`, `/camera`.

**Realtime** (1): `/realtime` (WebSocket). **Misc** (2): `/tts`, `/voice`.

### `/api/home-assistant/*` surface (5 routes)
`/status`, `/states`, `/states/{id}`, `/service`, `/gesture-map`.

## Backend models + migrations

| File | Purpose |
|------|---------|
| `backend/app/models/reachy_sequence.py` | `SequenceCreate`, `SequenceUpdate`, `SequencePlay` Pydantic schemas. |
| `backend/app/models/meeting.py` | Meeting-related schemas. |
| `backend/app/db/models.py` | ORM: `MeetingModel`, `MeetingRecordingModel`, `MeetingTranscriptSegmentModel`, `MeetingSummaryModel`, `MeetingSpeakerMappingModel`, `ReachySequenceModel`. |
| `backend/app/migrations/versions/038_reachy_sequences.py` | Migration: create `reachy_sequences` table. |

## Data directories (NEW this cycle)

| Path | Contents |
|------|----------|
| `backend/app/data/reachy_profiles/` | 16 persona profile directories (default, example, bored_teenager, captain_circuit, chess_coach, cosmic_kitchen, hype_bot, mad_scientist_assistant, mars_rover, nature_documentarian, noir_detective, sorry_bro, tedai, time_traveler, victorian_butler). Each has `instructions.txt` + `tools.txt`; `example/` also has `sweep_look.py` custom motion handler. |
| `backend/app/data/reachy_prompts_library/` | Composable prompts: `default_prompt.txt`, `passion_for_lobster_jokes.txt`, `identities/{basic_info.txt, witty_identity.txt}`, `behaviors/silent_robot.txt`. |

## Scheduler jobs

**Registered in `scheduler_service.py` DAILY_SCHEDULE:**
- `reachy_calendar_nudge`
- `reachy_email_nudge`
- `reachy_meeting_auto_record` — NEW (REQ-002, uncommitted)
- `reachy_meeting_auto_stop` — NEW (REQ-002, uncommitted)

**Registered at runtime in `reachy_presence_service.start()`:**
- `reachy_pomodoro_tick` (1 min), `reachy_idle_watcher` (10 min), `reachy_hourly_chime` (cron :00), `reachy_presence_beat` (3 min)

**Registered at runtime in `home_assistant_watcher.start()` (only if gesture_map configured):**
- `ha_gesture_watcher` (15 s, configurable)

## Frontend

| File | Route | Purpose |
|------|-------|---------|
| `frontend/src/pages/ReachyMotionLibraryPage.tsx` | `/reachy` | 100-clip browser + persona picker + PTT + modes + stats |
| `frontend/src/pages/ReachyTeleopPage.tsx` | `/reachy/teleop` | Keyboard + sliders + 3D puppet + diagnostics + radio + vision + move recorder |
| `frontend/src/pages/ReachyHomeAssistantPage.tsx` | `/reachy/home-assistant` | HA status + entity browser + gesture-map viewer |
| `frontend/src/pages/ReachyMeetingsPage.tsx` | `/reachy/meetings` | REQ-002 — calendar events + auto-record toggle + quick add |
| `frontend/src/components/reachy/*` | — | 10 components: SequenceBuilder, ReachyRealtimeSettings, LiveMeetingPanel, QuickMeetingDialog, MeetingCard, AddEventDialog, DaemonPanel, FloatingVoiceButton, ReachyCameraViewer (NEW), plus 1 more |
| `frontend/public/reachy-mic-worklet.js` | — | AudioWorklet for browser-side PCM16 capture (realtime voice) |
| `frontend/src/hooks/useReachyApi.ts` | — | React Query hooks covering all backend routes |
| `frontend/src/hooks/useRealtimeVoice.ts` | — | Realtime API connection lifecycle + audio streaming |
| `frontend/src/lib/reachy-realtime-audio.ts` | — | Low-level audio capture + WebSocket feed for realtime |
| `frontend/src/tests/reachy-realtime-audio.test.ts` | — | Vitest coverage of audio pipeline |
| `frontend/src/components/layout/AppSidebar.tsx` | — | "Reachy" / "Teleop" / "Reachy + HA" / "Meetings" entries |

## Config keys (`backend/app/infrastructure/config.py` + `.env`)

| Key | Purpose |
|-----|---------|
| `ZERO_REACHY_API_URL` | Daemon URL, default `http://host.docker.internal:8000` |
| `ZERO_REACHY_TTS_CONFIRMATIONS` | Speak "Recording started" / "Meeting saved" |
| `ZERO_REACHY_REALTIME_BACKEND` | "openai" or "gemini" (NEW) |
| `ZERO_REACHY_REALTIME_MODEL` / `_VOICE` / `_PROFILE` | Realtime overrides (NEW) |
| `ZERO_HA_BASE_URL` / `ZERO_HA_TOKEN` | HA bridge creds |
| `ZERO_HA_POLL_SECONDS` / `ZERO_HA_GESTURE_MAP` | HA watcher config |
| `ZERO_REACHY_WAKE_MODEL` / `_THRESHOLD` / `_COOLDOWN` | Wake-word tuning |
| `ZERO_REACHY_PERSONA_ROTATION` | Auto-rotation JSON |
| `ZERO_HOST_AGENT_URL` | host_agent base URL (default `http://127.0.0.1:18794`) |
| `ZERO_REACHY_EMAIL_READER_VOICE` | Reader voice (default `en-GB-RyanNeural`) |

## External surfaces

### `host_agent/` — MAJOR EXPANSION this cycle (14 .py + 4 .bat, mostly uncommitted)

Standalone daemon supervisor + mic/wake-word/live-transcription stack running on Windows host outside Docker.

| File | Purpose |
|------|---------|
| `main.py` | FastAPI server (:18794) exposing `/record/*`, `/transcribe/*`, `/audio/*`; coordinates all host_agent subsystems. |
| `supervisor.py` | Daemon supervisor: spawns `run_reachy_daemon.py`, monitors stdout, auto-restart on failure. |
| `supervisor_only.py` | Minimal supervisor (skip audio/transcription). |
| `wake_loop.py` | Porcupine-based always-on wake-word listener. |
| `whisper_wake_loop.py` | Fallback: continuous Whisper "hey zero" phrase detector. |
| `audio_capture.py` | USB audio capture with RingBuffer + device discovery (sounddevice + numpy). |
| `voice_capture.py` | Voice-specific audio capture (higher sensitivity). |
| `live_transcription.py` | Real-time Whisper (base, int8, CPU) on rolling window; broadcasts to WebSocket. |
| `camera_worker.py` | Background camera capture thread (scaffold). |
| `audio_buffer.py` | Fixed-size circular buffer for streaming audio. |
| `check_threads.py` / `probe_mic.py` / `probe_callback.py` | Diagnostic utilities. |
| `run_reachy_daemon.py` | Headless launcher for Reachy SDK FastAPI sidecar. |
| `*.bat` | `run.bat`, `run-supervisor.bat`, `run-mockup.bat`, `run_reachy_daemon.bat`. |

### `reachy_app/`
Installable Zero-as-Reachy-app scaffold. Not deployed to robot yet.

### `C:\code\reachy-apps\` (reference mirror)
80 upstream repos (8 official + 12 Pollen + 14 SDK + 3 datasets + 43 community). `CATALOG.md` + `HARVEST_MANIFEST.md`.

## Capability matrix

| Capability | Implemented? | Evidence |
|------------|--------------|----------|
| Play any of 100 motion clips | yes | `reachy_motion_library.py` + `/emotion`, `/dance`, `/motion/play` |
| Switch personas | yes | `reachy_personas.py` + `/personas/select` + UI |
| Persona-aware LLM turn with gestures | yes (live 2026-04-22) | `voice_loop_service._get_llm_response` + marker parser |
| Meeting mode look-at-speaker | yes | `reachy_presence_service._meeting_loop` + `start_meeting_mode` |
| Meeting mode nod-on-highlight | no | No transcription→gesture hook |
| Speaker diarization | no | DoA angle only; no speaker ID |
| User-defined motion sequences | yes (uncommitted) | `reachy_sequence_service.py` + migration 038 + `SequenceBuilder.tsx` |
| Streaming voice (OpenAI Realtime / Gemini Live) | yes (uncommitted) | `reachy_realtime/` + `reachy-mic-worklet.js` + `ReachyRealtimeSettings.tsx` |
| Speech-reactive head wobble during TTS | partial (uncommitted) | Active in realtime, not yet wired to chunked path (II-012) |
| Voice email triage (REQ-002) | yes (uncommitted, **0/7 verified**) | `email_voice_session_service.py` + `reachy_email.py` + `voice_intent_router.py` |
| Meeting auto-record by calendar event | yes (uncommitted, **0/7 verified**) | `meeting_auto_recorder_service.py` + scheduler jobs + `/reachy/meetings` |
| Runtime voice LLM provider switching | yes | `reachy_chat_provider.py` + `/chat-provider/*` |
| Pomodoro + ambient beats | yes | 4 scheduler jobs in `reachy_presence_service` |
| Home Assistant gesture watcher | partial | Client works; gesture-map file not configured |
| Face detection | yes | OpenCV Haar via `/vision/detect?kind=face` |
| Hand tracking | yes | MediaPipe 0.10.14 via `/vision/detect?kind=hands` |
| Move recorder | yes (live-verified 2026-04-22: 279 frames) | `reachy_move_recorder.py` |
| Radio mode (BPM-locked dances) | yes (live-verified 2026-04-22) | `reachy_radio_service.py` |
| 3D puppet viewer | partial (CSS 3D) | `PuppetView` on teleop page |
| Wake word (local openwakeword) | scaffold only | Degrades to `available:false` |
| Wake word (host-side Whisper) | partial (NEW, uncommitted) | `host_agent/whisper_wake_loop.py` — continuous rolling-window detector |
| Per-persona tool grants | yes (NEW, uncommitted) | `reachy_profiles/*/tools.txt` |
| Composable prompt library | yes (NEW, uncommitted) | `reachy_prompts_library/{identities,behaviors,default_prompt.txt}` |
| Persona intros (custom greetings) | yes (NEW, uncommitted) | `reachy_persona_intros_service.py` + `/personas/{id}/intro` |
| Per-user memory (long-form context) | yes (NEW, uncommitted) | `reachy_user_memory_service.py` |
| host_agent live transcription stream | yes (NEW, uncommitted) | `host_agent/live_transcription.py` + WebSocket broadcast |
| host_agent daemon supervisor | yes (NEW, uncommitted) | `host_agent/supervisor.py` + `/daemon/*` surface in `reachy.py` |
| Camera WebRTC frontend client | no | Only URL passthrough |
| Installable Zero-as-Reachy-app | scaffold | `reachy_app/`, not installed on robot |
| Headless daemon (no Pollen desktop app) | yes | `host_agent/run_reachy_daemon.bat` + supervisor |

## Deltas vs 2026-04-23 inventory

**New files (28):**
- 2 backend services: `reachy_persona_intros_service.py`, `reachy_user_memory_service.py`
- 0 routers (realtime/intent/email/voice_bridge already counted last run)
- 14 host_agent files (supervisor, wake_loop, whisper_wake_loop, audio_capture, voice_capture, live_transcription, camera_worker, audio_buffer, check_threads, main, probe_*, supervisor_only) + 3 bat files
- 2 frontend: `LiveMeetingPanel.tsx`, `ReachyCameraViewer.tsx`, `useRealtimeVoice.ts`, `lib/reachy-realtime-audio.ts`, `tests/reachy-realtime-audio.test.ts`, `FloatingVoiceButton.tsx` (some counted last run; delta is incremental)
- 2 data directories: `reachy_profiles/` (16 subdirs), `reachy_prompts_library/`

**Modified files (~20 including 12 Reachy-touching ones):** `reachy.py` (routes 61→89), `voice_loop_service.py`, `reachy_presence_service.py` (introduced bare `datetime.now()`), `reachy_emotion_parser.py`, `reachy_personas.py`, `reachy_vision_service.py`, `reachy_service.py`, meeting suite, host_agent requirements.

**Deleted files:** 0.

**Capability regressions:** 0. Coverage expanded in every dimension. Trade-off is Freshness + Quality drag from uncommitted state.

**Still 0 Reachy commits on main since 2026-04-22** (commits `caf89be`, `9a01e35`, `cf06530`, `8d28e24`, `b05af9a`). The uncommitted slab is **2 audits old** and growing.
