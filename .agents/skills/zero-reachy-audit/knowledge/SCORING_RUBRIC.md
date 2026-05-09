# Zero Reachy Audit — Scoring Rubric

**Scope**: Reachy Mini capability inside Zero. Infra (Docker, DB, ports) is graded by `zero-docker-health`; this skill grades the robot surface only.

**Grade scale**:
`A+ (97–100) · A (93–96) · A- (90–92) · B+ (87–89) · B (83–86) · B- (80–82) · C+ (77–79) · C (73–76) · C- (70–72) · D (60–69) · F (0–59)`

## Six capability dimensions

Each dimension is graded on four sub-metrics, composited at 40/25/20/15.

### 1. Motion & Body

**Target surface**
- [ ] Head pose control (xyzrpy) via `goto` + `set_target`
- [ ] Body yaw control
- [ ] Antennas control (2-axis)
- [ ] Emotion clip library ≥ 81 clips with alias resolver
- [ ] Dance clip library ≥ 19 clips with BPM-lock capability
- [ ] Free-form LLM-tag resolver (`"i did it"` → `proud3`)
- [ ] User-recorded move library (record + replay + list + delete)
- [ ] Motor torque toggle (enabled / compliant / disabled)
- [ ] Wake / sleep routines
- [ ] Motion playback graceful when daemon offline

**Quality deductions**
- `except Exception:` in `reachy_motion_library.py`, `reachy_service.py`, `reachy_move_recorder.py`, `reachy_radio_service.py`: −3 each, max −30
- `TODO/FIXME/NotImplementedError` in same: −5 each, max −25
- `datetime.now()` without tz: −10 each, max −30
- `print()` in prod code: −5 each, max −15

**Freshness check**
- Waves 1, 10, 13 from `HARVEST_MANIFEST.md` listed as done and on main.
- `pollen-robotics/reachy-mini-emotions-library` clip count matches `EMOTION_CLIPS` length.
- `pollen-robotics/reachy-mini-dances-library` clip count matches `DANCE_CLIPS` length.

**Observability**
- `structlog.get_logger()` imported in every motion service.
- `reachy_motion_play_failed` / `reachy_dance_failed` log events present.

---

### 2. Voice & Conversation

**Target surface**
- [ ] STT via audio service (whisper)
- [ ] Persona-prepended LLM call through `unified_llm_client`
- [ ] TTS synthesis via `tts_service`
- [ ] Gesture-marker parsing before TTS
- [ ] Parallel gesture dispatch during speech
- [ ] Push-to-talk from browser (MediaRecorder upload)
- [ ] Wake word detector scaffold (opt-in openwakeword)
- [ ] `audio_response_b64` returned to HTTP clients
- [ ] Error recovery: LLM fail → canned fallback → TTS still runs

**Quality deductions** — `voice_loop_service.py`, `reachy_emotion_parser.py`, `reachy_wake_word_service.py`.

**Freshness check**
- Wave 2 + Wave 8 + Wave 11 from `HARVEST_MANIFEST.md`.
- `reachy-mini-conversation-app/profiles/` count matches `PERSONAS`.
- Upstream streaming-voice (Voxtral/Parakeet) tracked in `INTEGRATION_IDEAS.md`.

**Observability**
- `voice_transcribed`, `voice_llm_failed`, `voice_gesture_malformed` all logged with context.

---

### 3. Persona & Emotion

**Target surface**
- [ ] 12 personas with `system_prompt` + `tools` allowlist
- [ ] `[emotion:..] [dance:..] [motion:..] [look:x,y,z]` marker grammar
- [ ] `parse_and_strip()` returns clean text + actions with offsets
- [ ] Persona state counters (interactions/emotions/dances)
- [ ] Optional auto-rotation config
- [ ] Context hint appends time/calendar/mode to every turn
- [ ] Persona switch via `/reachy/personas/select`
- [ ] Frontend persona picker
- [ ] Gesture dispatch fires in parallel with TTS (<500 ms gap)

**Freshness check** — Waves 2 + 15 + 17.

**Observability**
- `voice_loop_persona_changed`, `persona_state_update_failed`, `reachy_context_build_failed`.

---

### 4. Presence & Ambient

**Target surface**
- [ ] APScheduler jobs attached to Zero's main scheduler
- [ ] Pomodoro state machine (work/break) with emotion triggers
- [ ] Idle watcher: fires tired/boredom gestures after quiet time
- [ ] Hourly chime (quiet hours respected)
- [ ] Presence beat (low-probability dance when nothing else active)
- [ ] Voice activity marking from voice loop
- [ ] Calendar nudge jobs (already in scheduler_service as `reachy_calendar_nudge` + `reachy_email_nudge`)
- [ ] All jobs no-op cleanly when daemon offline

**Freshness check** — Wave 5.

**Observability**
- Each tick logs `reachy_pomodoro_phase`, `reachy_presence_play_failed`, etc.

---

### 5. Meeting Mode

**Target surface**
- [ ] `start_meeting_mode()` + `stop_meeting_mode()` as service methods
- [ ] `_meeting_loop()` polls `/api/state/doa` every ~3 s
- [ ] Look-at-speaker via `look_at(x,y,z)` on angle change > 0.15 rad
- [ ] Periodic `attentive1` gesture every ~45 s
- [ ] Wired into `meeting_recording_service.start/stop_recording`
- [ ] Manual start/stop endpoints exposed
- [ ] Frontend meeting-mode button
- [ ] Collision suppression: pomodoro / hourly chime / presence beat all skip while meeting active

**Freshness check** — Wave 4.

**Observability**
- `reachy_meeting_mode_started/stopped`, `reachy_meeting_doa_tick_failed`, `reachy_meeting_loop_crashed`.

**Known gaps** (as of 2026-04-22)
- No speaker diarization — just DoA angle. Doesn't know *who* is talking.
- Nod-on-highlight (transcription-driven gesture) not implemented.
- Meeting summary → gesture reaction loop not implemented.
- No persona-aware meeting mode (e.g., victorian_butler at formal meetings).

---

### 6. Environment & Integrations

**Target surface**
- [ ] Home Assistant REST client (status / states / call-service)
- [ ] HA gesture-map watcher (entity transition → Reachy gesture)
- [ ] Vision: face detection (OpenCV Haar), hand tracking (MediaPipe)
- [ ] Camera stream URL passthrough
- [ ] Reachy-installable app scaffold (`reachy_app/`)
- [ ] Zero-as-Reachy-app bridge (mic → Zero → TTS back)
- [ ] Headless daemon launcher (`host_agent/run_reachy_daemon.bat`)
- [ ] Ecosystem mirror at `C:\code\reachy-apps\` with `pull.sh`, `CATALOG.md`, `HARVEST_MANIFEST.md`

**Freshness check** — Waves 3 + 6 + 7 + 8 + 12.

**Observability**
- `ha_watcher_started`, `ha_gesture_fired`, `ha_request_failed`, vision-service lazy-import errors.

---

## Cross-cutting scores (reported alongside, not weighted in)

### Infrastructure Health
- Daemon reachable at `host.docker.internal:8000`? (`GET /api/reachy/status` connected=true)
- `host_agent/` venv exists and up-to-date?
- USB audio device "Reachy Mini Audio" bound?
- Port 8000 held by the intended process (desktop app vs `run_reachy_daemon.py`)?

Output: `GREEN` (all 4 ok), `YELLOW` (1–2 issues), `RED` (3+).

### Interweaving Index
Count of end-to-end flows that actually compose multiple dimensions:
- Voice loop persona + gesture dispatch (dims 2 + 3) — **required**
- Meeting mode + DoA look + attentive gesture (dims 1 + 5) — **required**
- Calendar context → persona tone (dims 3 + 6) — **stretch**
- HA trigger → Reachy reaction (dims 4 + 6) — **stretch**
- Radio BPM → beat-locked dances (dim 1 internal + external audio) — **stretch**

Score: integer count of flows verified working. Target ≥ 3.

### Backlog Debt
Count of `REQUESTS_LOG.md` entries with `State: pending` older than 14 days. Target = 0.

## Sub-metric composite formula

```
dimension_score = coverage * 0.40
                + quality  * 0.25
                + freshness * 0.20
                + observability * 0.15

overall = mean(six dimension scores)
```

## Trend deadband

Per-dimension arrows:
- ↑ if new_score - old_score ≥ 5
- ↓ if old_score - new_score ≥ 5
- → otherwise

Prevents noise from small rebuilds.
