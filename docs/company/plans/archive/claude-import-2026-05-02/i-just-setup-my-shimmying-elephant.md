# Reachy Mini Lite as Zero's Voice — Milestone 1: Meeting Recording

## Context

The user just set up a **Pollen Robotics Reachy Mini Lite** (tethered USB version, $299, 2 mics, 1 speaker, 6-DOF head, antennae) plugged into their Windows 11 host. They want the robot to become the physical embodiment of **Zero**, their personal assistant. The first milestone is: **use the Reachy mic to record meetings, transcribe them, summarize them**, with short TTS confirmations through the Reachy speaker ("Recording started", "Meeting saved").

### Key architectural realities

1. **The Reachy Mini Desktop App works on Windows** (user has it running).
   - Source: [pollen-robotics/reachy-mini-desktop-app](https://github.com/pollen-robotics/reachy-mini-desktop-app). Tauri + React frontend, Python FastAPI **daemon sidecar on port 8000**, WebRTC on 8443 for camera + DoA audio.
   - Zero already has a client for this daemon: [reachy_service.py](backend/app/services/reachy_service.py#L18) connects to `http://localhost:8000/api/v1` (move_head, look_at, play_emotion, say, capture_image, audio/direction). **The integration is already written.** Just needs `REACHY_API_URL=http://host.docker.internal:8000` since Zero runs in Docker.

2. **Zero already has a real meeting recording pipeline** — the user didn't realize this.
   - [meeting_audio_capture.py](backend/app/services/meeting_audio_capture.py) is a full WASAPI loopback + sounddevice capture implementation (not a stub).
   - [meeting_recording_service.py](backend/app/services/meeting_recording_service.py) orchestrates WAV writing + triggers the processing pipeline.
   - Meeting processing services exist for diarization, transcription (faster-whisper), summarization, vector search, and RAG chat.
   - Routers exist: [meeting_recordings.py](backend/app/routers/meeting_recordings.py), [meeting_transcriptions.py](backend/app/routers/meeting_transcriptions.py), [meeting_summaries.py](backend/app/routers/meeting_summaries.py), [meeting_ws.py](backend/app/routers/meeting_ws.py), [meetings.py](backend/app/routers/meetings.py).

3. **But the recording code can't run in Docker.**
   - `pyaudiowpatch` and `sounddevice` are commented out in [requirements.txt](backend/requirements.txt): `# pip install pyaudio.audio sounddevice PyAudioWPatch`.
   - The `/capabilities` endpoint at [meeting_recordings.py:43-74](backend/app/routers/meeting_recordings.py#L43) explicitly says: *"These are not installed in the Docker container. Run Zero on the host for recording."*
   - Docker on Windows can't access host USB audio devices anyway.

4. **There's an existing sibling project, [DailyMeetings](C:\code\DailyMeetings)** (port 18793) that was extracted previously to run on the Windows host because of this constraint. It has its own copy of the recording/transcription/summary services and is proxied by [frontend/nginx.conf](frontend/nginx.conf) for `/api/meeting*` + `/ws/meeting*` routes. Neither Zero nor DailyMeetings is running right now (both `curl` health checks returned connection-refused).

5. **The critical empirical question — can Reachy's USB mic be selected as a standard Windows audio input device?**
   - If yes (USB Audio Class-compliant): existing code just needs **device-selection support**. Trivial.
   - If the mic is exclusively claimed by the Reachy daemon and only accessible via its WebRTC/DoA pipeline: significant extra work (WebRTC client).
   - Must be verified empirically as the first step — neither my research nor the user knows for sure yet.

6. **Zero has a complete TTS + `reachy.say()` path already wired** — no new work needed to speak confirmations. See [reachy_service.py:156-181](backend/app/services/reachy_service.py#L156) (`ReachyService.say()` → TTSService synth → POST `/api/v1/audio/play` on daemon).

### Decision: where to run the host-side audio capture

Three viable options:
- **A. Resurrect DailyMeetings** — exists, most of the work is done, has known device-selection gaps. Parallel service; branding/mental-model mismatch with "Zero does everything".
- **B. Run Zero backend as a second process on host (uvicorn, audio deps installed)** — reuses Zero code directly, but creates two Zero backends sharing a DB. Messy.
- **C. New minimal "Zero Host Audio Agent"** — thin FastAPI at e.g. `:18794`, imports `meeting_audio_capture` + `meeting_transcription_service` from `backend/`, exposes only record/stop/devices/live-transcript. Cleanest mental model ("one Zero, with a tiny local audio helper"), smallest surface area.

**Recommended: Option C.** DailyMeetings has duplicate code and the user doesn't know it exists; fresh minimal agent is easier to understand and maintain. Small enough (~150 lines) to not warrant dragging DailyMeetings' history along. Zero's existing `meeting_audio_capture.py` and `meeting_transcription_service.py` are reused directly by the host agent via a shared Python path (same git repo, agent venv points at `backend/`).

---

## Milestone 1 Plan

### Phase 0 — Discovery (BEFORE writing code)

These answers determine the actual implementation path. Do them first, as read-only / sandbox actions.

1. **Confirm the Reachy desktop app's daemon is reachable from Zero's Docker perspective.**
   ```bash
   curl -s http://localhost:8000/api/v1/status
   ```
   If 200: good. Then from inside zero-api container: `docker exec zero-api curl -s http://host.docker.internal:8000/api/v1/status`. If that works too, move on.

2. **Enumerate Windows audio input devices and check whether the Reachy mic shows up.**
   Create a throwaway script (or run inline Python on host with a temp venv) using `sounddevice.query_devices()` and `pyaudiowpatch`'s device enumeration. Look for device names containing "reachy", "xmos", "xvf", "respeaker", or the USB vendor ID Pollen uses. Record the index and name.
   - **If the Reachy mic IS listed** → Path A (simple): just need device-selection support.
   - **If NOT listed** → Path B (complex, deferred to milestone 2): need to tap the desktop app's WebRTC audio. Flag to user, milestone 1 falls back to using system mic.

3. **Verify the Reachy speaker is reachable via the daemon's `/audio/play` endpoint.**
   ```bash
   curl -X POST http://localhost:8000/api/v1/audio/play -H "Content-Type: audio/wav" --data-binary @a_small_test.wav
   ```
   If the robot plays the sound: TTS confirmations are unblocked.

### Phase 1 — Add device selection to existing Zero meeting code

Even without the Reachy-specific bits, the existing code has no device picker, which is the only real engineering gap.

**Files to modify:**

1. **[backend/app/services/meeting_audio_capture.py](backend/app/services/meeting_audio_capture.py)**
   - Extend `AudioCapture.__init__` to accept `mic_device_index: int | None = None` and `system_device_index: int | None = None`.
   - In `_start_mic_capture()` (line 159), pass `device=self._mic_device_index` to `sd.InputStream(...)`.
   - In `_start_system_capture()` (line 127), if `self._system_device_index is not None`, look up that device instead of searching WASAPI loopback.
   - Add module-level function `list_audio_devices() -> dict` that returns `{"mic": [...], "system_loopback": [...]}` using `sounddevice.query_devices()` and pyaudiowpatch loopback enumeration. Each entry: `{"index": int, "name": str, "max_input_channels": int, "default_samplerate": int, "is_reachy": bool}` where `is_reachy` is True if the name matches common Reachy-related strings.

2. **[backend/app/services/meeting_recording_service.py](backend/app/services/meeting_recording_service.py)**
   - Extend `start_recording()` signature with optional `mic_device_index: int | None = None`.
   - Pass through to `AudioCapture`. Persist the selected device on `MeetingRecordingModel` (add a `mic_device_name: str | None` column via Alembic migration — new file under `backend/alembic/versions/`).

3. **[backend/app/models/meeting.py](backend/app/models/meeting.py)**
   - Extend `RecordingStartRequest` schema with `mic_device_index: Optional[int] = None`.
   - Add `AudioDevicesResponse` schema.

4. **[backend/app/routers/meeting_recordings.py](backend/app/routers/meeting_recordings.py)**
   - Add `GET /api/meeting-recordings/devices` returning `list_audio_devices()` output.
   - Update `POST /start` to forward `mic_device_index`.

5. **Config for persistent default device** — in [backend/app/infrastructure/config.py](backend/app/infrastructure/config.py), add `preferred_mic_device_name: str | None = None` setting backed by env var `ZERO_PREFERRED_MIC_DEVICE`. If set and device present in enumeration, use as default when no explicit index passed.

### Phase 2 — Zero Host Audio Agent (new, small)

**New files:**

1. **`host_agent/__init__.py`** and **`host_agent/main.py`** at repo root (or `backend/host_agent/`).
   - ~150-line FastAPI app, binds to `127.0.0.1:18794`.
   - Endpoints:
     - `GET /health` → `{"ok": true}`
     - `GET /devices` → calls `list_audio_devices()` (reuses Zero code).
     - `POST /record/start` → accepts `{meeting_id, title, source, mic_device_index}`. Calls Zero's `start_recording()`.
     - `POST /record/stop` → calls `stop_recording()`.
     - `GET /record/status` → `get_recording_status()`.
     - `WS /record/live-transcript` → broadcasts segments from `live_transcription_service` (reuses if it exists in Zero, else trivially add it).
   - Uses Zero's DB (`postgresql://zero:zero_dev@localhost:5433/zero`) so meetings created here show up in Zero's UI immediately.

2. **`host_agent/requirements.txt`** — pins `pyaudiowpatch`, `sounddevice`, `soundfile`, `numpy`, `faster-whisper`, `fastapi`, `uvicorn`, `sqlalchemy[asyncio]`, `asyncpg`, `structlog`. Mirrors Zero's backend deps minus the heavy/unused ones.

3. **`host_agent/run.bat`** — creates venv if missing, pip installs, runs uvicorn on :18794.

4. **[frontend/nginx.conf](frontend/nginx.conf)** — add upstream/proxy for `/api/host-agent/*` → `http://host.docker.internal:18794/`. Keep existing `/api/meeting*` routes on Zero (the Docker backend); the host-agent is only hit for recording start/stop/devices.

5. **Zero backend proxying** — inside Zero Docker, have `meeting_recordings.py` start/stop endpoints **forward to the host agent** when `ZERO_HOST_AGENT_URL` env is set. Fallback to the in-process code when not set (useful for devs running backend on host). [backend/app/routers/meeting_recordings.py](backend/app/routers/meeting_recordings.py) gains a `_forward_or_local()` helper.

### Phase 3 — Frontend: device picker + Reachy-aware UX

1. **[frontend/src/components/MeetingRecordingControls.tsx](frontend/src/components/MeetingRecordingControls.tsx)** (path TBD — may live under a different subdir; verify during execution).
   - Add a `<DevicePicker>` select populated from `GET /api/meeting-recordings/devices`.
   - Pre-select any device with `is_reachy: true`; otherwise fall back to system default.
   - Persist selection to localStorage so the user doesn't re-pick every meeting.

2. **New hook** `frontend/src/hooks/useAudioDevices.ts` — React Query wrapper over `/api/meeting-recordings/devices`.

3. **Reachy status indicator** — small badge ("Reachy: Connected" / "Reachy: Offline") in the meeting recording panel. Reuse existing `GET /api/reachy/status` — already works.

### Phase 4 — TTS confirmations via Reachy

Wire the Reachy's speaker into the start/stop recording lifecycle.

1. **[backend/app/services/meeting_recording_service.py](backend/app/services/meeting_recording_service.py)**
   - After successful `start_recording`: fire-and-forget `asyncio.create_task(get_reachy_service().say("Recording started"))`. Don't await — don't block on robot.
   - After successful `stop_recording`: `asyncio.create_task(get_reachy_service().say("Meeting saved"))`.
   - After the processing pipeline completes (in `_run_processing_pipeline`): `asyncio.create_task(get_reachy_service().say("Summary ready"))`.
   - Gate each behind a `settings.reachy_tts_confirmations: bool = True` so it can be disabled.

2. **Environment variable** for Zero Docker: `REACHY_API_URL=http://host.docker.internal:8000`. Add to [docker-compose.sprint.yml](docker-compose.sprint.yml) under `zero-api.environment`. Already has default, but explicit is safer.

### Phase 5 — Deployment + Verification (the user-facing test)

1. **Start the Reachy desktop app** (user does this manually — confirm it's running, check `curl http://localhost:8000/api/v1/status`).

2. **First-time setup of host agent** — run `host_agent/run.bat` to create venv and start on :18794. Confirm `curl http://localhost:18794/health`.

3. **Rebuild Zero backend** (per CLAUDE.md deployment rule) — nginx.conf change + router changes require:
   ```bash
   docker compose -f docker-compose.sprint.yml build --no-cache zero-api zero-ui
   docker compose -f docker-compose.sprint.yml up -d zero-api zero-ui
   docker ps --format "table {{.Names}}\t{{.Status}}" | grep zero
   ```

4. **End-to-end test via UI** (golden path):
   - Open `http://localhost:5173/meetings` (or wherever the meetings page lives; confirm path during execution).
   - Device picker should list audio inputs, with the Reachy mic flagged and pre-selected.
   - Click "Start Recording" → Reachy says "Recording started" → UI shows live transcript segments.
   - Speak for 30 seconds into the Reachy → live transcript should show words appearing.
   - Click "Stop Recording" → Reachy says "Meeting saved" → processing pipeline runs.
   - Within ~30s-2min (depending on audio length + Ollama speed), summary appears in the UI and Reachy says "Summary ready".

5. **Edge cases to verify explicitly:**
   - What happens if the user starts Zero but Reachy daemon is down? `reachy_service` should log a warning and the UI should show "Reachy: Offline" — recording should still work with the fallback system mic.
   - What happens if the host agent is down? Zero backend should return a clear error message on `POST /start` — not a 500 stacktrace.
   - What happens if Whisper fails mid-transcription? Meeting status should be set to "failed" (already handled in `_run_processing_pipeline` line 120-130) — verify log output.

---

## Key files to read/modify (summary)

### Read
- [backend/app/services/meeting_audio_capture.py](backend/app/services/meeting_audio_capture.py) (full)
- [backend/app/services/meeting_recording_service.py](backend/app/services/meeting_recording_service.py) (full)
- [backend/app/services/meeting_transcription_service.py](backend/app/services/meeting_transcription_service.py)
- [backend/app/services/meeting_processing_pipeline.py](backend/app/services/meeting_processing_pipeline.py)
- [backend/app/services/reachy_service.py](backend/app/services/reachy_service.py) (full)
- [backend/app/services/tts_service.py](backend/app/services/tts_service.py)
- [backend/app/routers/meeting_recordings.py](backend/app/routers/meeting_recordings.py) (full)
- [backend/app/routers/reachy.py](backend/app/routers/reachy.py) (full)
- [backend/app/routers/meeting_ws.py](backend/app/routers/meeting_ws.py)
- [frontend/nginx.conf](frontend/nginx.conf)
- [backend/app/models/meeting.py](backend/app/models/meeting.py)
- [docker-compose.sprint.yml](docker-compose.sprint.yml)
- `C:\code\DailyMeetings\app\services\live_transcription_service.py` — reference for live transcription broadcast pattern (not to copy wholesale, but understand the approach).

### Modify
- [backend/app/services/meeting_audio_capture.py](backend/app/services/meeting_audio_capture.py) — device selection + `list_audio_devices()`.
- [backend/app/services/meeting_recording_service.py](backend/app/services/meeting_recording_service.py) — pass through device + Reachy TTS hooks.
- [backend/app/routers/meeting_recordings.py](backend/app/routers/meeting_recordings.py) — new `/devices` endpoint + proxy-or-local forwarding.
- [backend/app/models/meeting.py](backend/app/models/meeting.py) — schemas.
- [backend/app/infrastructure/config.py](backend/app/infrastructure/config.py) — new settings.
- [backend/alembic/versions/](backend/alembic/versions/) — new migration for `mic_device_name` column.
- [frontend/nginx.conf](frontend/nginx.conf) — host agent proxy.
- [frontend/src/components/…/MeetingRecordingControls.tsx](frontend/src/components/) — device picker UI (verify path during execution).
- [docker-compose.sprint.yml](docker-compose.sprint.yml) — `REACHY_API_URL` env + optional `ZERO_HOST_AGENT_URL` env.

### Create
- `host_agent/main.py` + `host_agent/requirements.txt` + `host_agent/run.bat`.
- `frontend/src/hooks/useAudioDevices.ts`.

---

## Verification (end-to-end health checks)

**Services up:**
- `curl http://localhost:8000/api/v1/status` → 200 (Reachy daemon).
- `curl http://localhost:18794/health` → 200 (host agent).
- `docker ps | grep zero-api` → Up.
- `docker ps | grep zero-ui` → Up.

**Reachy reachable from Docker:**
- `docker exec zero-api curl -s http://host.docker.internal:8000/api/v1/status` → 200.

**Audio devices enumerated:**
- `curl http://localhost:5173/api/meeting-recordings/devices` → JSON list with `is_reachy: true` for at least one mic.

**TTS round-trip:**
- `curl -X POST http://localhost:5173/api/reachy/say -H "Content-Type: application/json" -d '{"text":"Hello from Zero"}'` → Reachy speaks.

**Full meeting pipeline:**
- Start recording via UI → 20 seconds of speech → Stop → Summary present in DB within 2 minutes.
- `docker exec zero-pg psql -U zero -d zero -c "select id, title, status, duration_seconds from meetings order by start_time desc limit 3;"` → newest row status = `summarized`.

**Logs clean:**
- `docker logs --tail 200 zero-api 2>&1 | grep -iE "error|traceback"` → no new errors.
- `tail -100 host_agent/logs/agent.log` (if logging to file) → no errors.

---

## Out of scope for Milestone 1 (note for future milestones)

- **Always-on / wake-word activated** meeting capture (Zero already has [wake_word_service.py](backend/app/services/wake_word_service.py) but it's not wired to meeting recording).
- **Head gestures / antenna expressions** during recording (e.g., look toward the speaker based on DoA). Reachy's DoA endpoint exists; orchestration service doesn't yet consume it.
- **WebRTC path** for Reachy mic access if direct USB enumeration fails — becomes a separate project to build a WebRTC pull-audio client.
- **Speaker diarization quality** — [meeting_diarization_service.py](backend/app/services/meeting_diarization_service.py) uses pyannote; tuning and speaker-mapping UI is its own effort.
- **Retiring DailyMeetings** — leave it in place until the host agent is proven; remove the nginx proxy entries later.

---

## Open risk — flag to user if it materializes during Phase 0

If the Reachy USB microphone does **not** enumerate as a standard Windows audio input device (i.e., Phase 0 step 2 comes back empty for Reachy-named devices), Milestone 1 cannot record through the Reachy mic directly. In that case, the recommended fallback is:
1. Proceed with Milestone 1 using the user's regular system microphone for now.
2. Open a Milestone 1.5: add a WebRTC pull-audio client to the host agent that consumes the Reachy desktop app's WebRTC stream on `:8443`.

This is a real risk worth explicitly surfacing, not hiding behind a smooth-sounding plan.
