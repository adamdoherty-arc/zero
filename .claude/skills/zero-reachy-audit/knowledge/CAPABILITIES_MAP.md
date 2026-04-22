# Reachy Capabilities Map (generated 2026-04-22)

Layer-by-layer inventory of every Reachy-related surface in `c:/code/zero`. Source of truth for Phase 1 of the audit. **Do not hand-edit** — regenerate via the Explore agent brief in SKILL.md.

## Backend services (`backend/app/services/`)

| File | Purpose |
|------|---------|
| `reachy_service.py` | Daemon REST client. Motion primitives, media, volume, motors, camera, TTS say. |
| `reachy_motion_library.py` | 81 emotions + 19 dances catalog with alias resolver + kind-filter. |
| `reachy_move_recorder.py` | 50 Hz state-polling move recorder + replay via streaming `set_target`. |
| `reachy_personas.py` | 12 persona profiles + `MOTION_TAG_INSTRUCTIONS` tail. |
| `reachy_persona_state.py` | Per-persona interaction counters + optional auto-rotation. |
| `reachy_emotion_parser.py` | `[emotion:..] [dance:..] [motion:..] [look:x,y,z]` parser + offset tracking. |
| `reachy_presence_service.py` | Pomodoro + idle watcher + hourly chime + presence beat + **meeting mode** (DoA look-at-speaker). |
| `reachy_radio_service.py` | BPM detector (librosa) + background dance dispatcher. |
| `reachy_wake_word_service.py` | Optional openwakeword wrapper (degrades to `available:false`). |
| `reachy_vision_service.py` | Face (OpenCV Haar) + hand (MediaPipe) detection with lazy imports. |
| `reachy_context_service.py` | Builds `### CURRENT CONTEXT` block from calendar + pomodoro + meeting + time. |
| `home_assistant_service.py` | HA REST client (status / states / call-service). |
| `home_assistant_watcher.py` | Polls HA entities, fires Reachy gestures on state transitions. |
| `voice_loop_service.py` | STT → persona-wrapped LLM → gesture strip → parallel dispatch → TTS. |
| `meeting_recording_service.py` | Starts/stops Reachy meeting mode on recording start/stop. |

## Backend routers (`backend/app/routers/`)

| File | Prefix | Route count |
|------|--------|-------------|
| `reachy.py` | `/api/reachy` | 58 |
| `reachy_intent.py` | `/api/reachy-intent` | — (separate skill, not audited here) |
| `home_assistant.py` | `/api/home-assistant` | 5 |

### `/api/reachy/*` surface (61 routes)

State + basics: `/status`, `/state`, `/doa`, `/health-check`, `/wake-up`, `/sleep`, `/move`, `/look`, `/antennas`, `/move/stop`, `/move/running`.

Motion library: `/emotion`, `/dance`, `/motion/library`, `/motion/play`, `/motion/resolve`.

Personas: `/personas`, `/personas/stats`, `/personas/stats/reset`, `/personas/{id}`, `/personas/select`, `/gesture/parse`.

Presence: `/presence/pomodoro`, `/presence/pomodoro/start`, `/presence/pomodoro/stop`, `/presence/meeting`, `/presence/meeting/start`, `/presence/meeting/stop`.

Move recorder: `/moves/record/start`, `/moves/record/stop`, `/moves/record/status`, `/moves/user`, `/moves/user/{lib}/{name}/play`, `/moves/user/{lib}/{name}` (DELETE).

Vision: `/vision/backends`, `/vision/detect`. Wake-word: `/wake-word/status`, `/wake-word/predict`.

Radio: `/radio/status`, `/radio/start`, `/radio/stop`, `/radio/analyze`.

Context: `/context/hint`.

Audio: `/say`, `/test-sound`, `/sounds`, `/sounds/upload`, `/sounds/{file}` (DELETE), `/sounds/play`, `/sounds/stop`.

Volume: `/volume`, `/volume/microphone`.

Motors: `/motors`, `/motors/mode`.

Camera: `/camera/specs`, `/camera/stream`, `/camera`.

Misc: `/tts`, `/voice`.

### `/api/home-assistant/*` surface (5 routes)
`/status`, `/states`, `/states/{id}`, `/service`, `/gesture-map`.

## Scheduler jobs

Registered in `scheduler_service.py` (pre-existing):
- `reachy_calendar_nudge`
- `reachy_email_nudge`

Registered at runtime in `reachy_presence_service.start()`:
- `reachy_pomodoro_tick` (1 min interval)
- `reachy_idle_watcher` (10 min interval)
- `reachy_hourly_chime` (cron :00)
- `reachy_presence_beat` (3 min interval)

Registered at runtime in `home_assistant_watcher.start()` (only if `gesture_map.json` or `ZERO_HA_GESTURE_MAP` present):
- `ha_gesture_watcher` (15 s interval, configurable)

## Frontend

| File | Route | Purpose |
|------|-------|---------|
| `frontend/src/pages/ReachyMotionLibraryPage.tsx` | `/reachy` | 100-clip browser + persona picker + PTT + modes panel + persona stats |
| `frontend/src/pages/ReachyTeleopPage.tsx` | `/reachy/teleop` | Keyboard + sliders + 3D puppet + diagnostics + radio + vision + move recorder |
| `frontend/src/pages/ReachyHomeAssistantPage.tsx` | `/reachy/home-assistant` | HA status + entity browser + gesture-map viewer |
| `frontend/src/hooks/useReachyApi.ts` | — | 40 React Query hooks covering all backend routes |
| `frontend/src/components/layout/AppSidebar.tsx` | — | "Reachy" / "Teleop" / "Reachy + HA" entries |

## Config keys (`backend/app/infrastructure/config.py` + `.env`)

| Key | Purpose |
|-----|---------|
| `ZERO_REACHY_API_URL` | Daemon URL, default `http://host.docker.internal:8000` |
| `ZERO_HA_BASE_URL` / `ZERO_HA_TOKEN` | HA bridge credentials |
| `ZERO_HA_POLL_SECONDS` | HA watcher tick interval |
| `ZERO_HA_GESTURE_MAP` | Inline gesture-map JSON (alternative to file) |
| `ZERO_REACHY_WAKE_MODEL` / `ZERO_REACHY_WAKE_THRESHOLD` / `ZERO_REACHY_WAKE_COOLDOWN` | Wake-word tuning |
| `ZERO_REACHY_PERSONA_ROTATION` | Auto-rotation config JSON (alternative to file) |

## External surfaces

| Path | Purpose |
|------|---------|
| `host_agent/run_reachy_daemon.py` | Headless launcher for the SDK's FastAPI sidecar — replaces the Pollen Tauri desktop app |
| `host_agent/run_reachy_daemon.bat` | Windows bootstrap: creates venv, installs `reachy-mini==1.6.4`, runs the daemon |
| `reachy_app/` | Installable Reachy Mini app package (mic → Zero `/voice` → TTS back) |
| `C:\code\reachy-apps\` | Local mirror of 80 upstream repos (8 official + 12 Pollen + 14 SDK + 3 datasets + 43 community) |
| `C:\code\reachy-apps\CATALOG.md` | Auto-generated catalog of cloned repos with live HF metadata |
| `C:\code\reachy-apps\HARVEST_MANIFEST.md` | Audit trail mapping upstream → Zero commits per Wave |

## Capability matrix

| Capability | Implemented? | Evidence |
|------------|--------------|----------|
| Play any of 100 motion clips | yes | `reachy_motion_library.py` + `/emotion`, `/dance`, `/motion/play` |
| Switch personas | yes | `reachy_personas.py` + `/personas/select` + UI dropdown |
| Persona-aware LLM turn with gestures | yes (live-verified 2026-04-22) | `voice_loop_service._get_llm_response` + marker parser |
| Meeting mode look-at-speaker | yes | `reachy_presence_service._meeting_loop` + `start_meeting_mode` |
| Meeting mode nod-on-highlight | **no** | No transcription→gesture hook yet |
| Speaker diarization | **no** | DoA gives angle only; no ID |
| Pomodoro + ambient beats | yes | 4 scheduler jobs registered at startup |
| Home Assistant gesture watcher | partial | Client works; gesture-map file not configured on this install |
| Face detection | yes | OpenCV Haar via `/vision/detect?kind=face` |
| Hand tracking | yes | MediaPipe 0.10.14 via `/vision/detect?kind=hands` |
| Move recorder (user-authored moves) | yes (live-verified 2026-04-22: 279 frames) | `reachy_move_recorder.py` |
| Radio mode (BPM-locked dances) | yes (live-verified 2026-04-22: 6 dances in 10s) | `reachy_radio_service.py` |
| 3D puppet viewer | partial (CSS 3D, not three.js) | `PuppetView` on teleop page |
| Wake word | scaffold only | `reachy_wake_word_service.py`, openwakeword not installed |
| Streaming voice (Realtime-style) | **no** | Chunked 5 s windows only |
| Camera WebRTC frontend client | **no** | Only URL passthrough |
| Installable Zero-as-Reachy-app | scaffold | `reachy_app/`, not installed on robot yet |
| Headless daemon (no Pollen desktop app) | yes | `host_agent/run_reachy_daemon.bat` |
