# Reachy Motion Library — Offline Management + Sequence Builder

> **Status:** Original scope (offline management + sequence builder) shipped and
> verified end-to-end. This plan was re-opened to fix two follow-on gaps
> discovered during end-to-end testing:
> 1. Supervisor's daemon stdout reader captures nothing on Windows
> 2. reachy_mini daemon errors out on `ksvideosrc` (no/incompatible webcam)

## Context

User is on the Motion Library page at [frontend/src/pages/ReachyMotionLibraryPage.tsx](frontend/src/pages/ReachyMotionLibraryPage.tsx) seeing a "Reachy offline" badge with only Wake/Sleep/Stop buttons. Hitting Wake while the daemon is down doesn't help — there's nothing to wake. The user wants:

1. **Real offline management** — diagnose why it's offline and restart it from the UI. Today the only fix is to manually rerun [host_agent/run_reachy_daemon.bat](host_agent/run_reachy_daemon.bat) on the Windows host.
2. **Custom motion sequences** — chain emotion/dance clips into named sequences that behave like first-class clips (playable from the UI, invokable by the LLM via `[emotion:my_greeting]`).

The daemon is launched by [host_agent/run_reachy_daemon.py](host_agent/run_reachy_daemon.py) (commit `cf06530`) as a foreground process. Nothing supervises it. The natural supervisor is the `host_agent` service on `:18794`, which already runs on the Windows host.

The motion library is 100 in-memory clips from [backend/app/services/reachy_motion_library.py](backend/app/services/reachy_motion_library.py). The resolver `resolve_motion()` (lines 203–240) is the single choke point for turning names/aliases into clips — that's where sequence resolution plugs in.

## Architecture

```
                           ┌──────────────────────────┐
 Browser                   │ Windows host             │
 ReachyMotionLibraryPage   │                          │
        │                  │ ┌──────────────────────┐ │
        │ REST             │ │ host_agent :18794    │ │
        ▼                  │ │                      │ │
 zero-api (Docker)         │ │  + daemon supervisor │ │──spawns──► reachy-mini
        │  ─────────────►  │ │  + log tail          │ │              daemon :8000
        │                  │ │  + watchdog          │ │
        │                  │ └──────────────────────┘ │
        │                  └──────────────────────────┘
        │                                ▲
        │ existing HTTP calls            │ existing audio capture
        └────────────────────────────────┘
```

Two new surfaces:

- **host_agent supervisor** — manages the daemon process (start/stop/restart/logs/watchdog).
- **sequence layer** — DB-backed user sequences that plug into the existing `resolve_motion()` and `motion/play` endpoints, so LLM/voice paths inherit them for free.

## Phase 1 — Host-agent daemon supervisor

File: [host_agent/app.py](host_agent/app.py) (or whatever the current FastAPI entry is — confirm on first read).

Add a `DaemonSupervisor` class that owns the daemon subprocess lifecycle:

- `start()` — spawns `run_reachy_daemon.py` via `subprocess.Popen`, captures stdout/stderr into a rotating in-memory ring buffer (last 500 lines) plus a log file under `host_agent/logs/reachy-daemon-YYYYMMDD.log`.
- `stop()` — sends SIGTERM, waits up to 5s, then SIGKILL.
- `restart()` — stop then start.
- `status()` — returns `{running, pid, started_at, uptime_s, last_exit_code, log_path}`.
- `logs(tail=100)` — returns last N lines from the ring buffer.
- `watchdog_tick()` — every 10s polls `http://localhost:8000/api/daemon/status`; tracks consecutive failures; auto-restarts after 6 failures (60s). Records each restart event with timestamp + reason.
- `diagnostics()` — probes and returns `{daemon_status, motors, audio_devices, usb_devices, cpu_percent, mem_mb, preload_state}`. Reuses daemon's own `/api/daemon/status` for motor/preload; uses `pyaudiowpatch` and `wmic` on Windows for USB/audio enumeration.
- `reset_audio()` — re-enumerates USB audio devices and reconnects capture. Triggers a reimport of the audio capture class in host_agent.

New endpoints on host_agent:

```
POST /daemon/start
POST /daemon/stop
POST /daemon/restart
GET  /daemon/status
GET  /daemon/logs?tail=100
GET  /daemon/diagnostics
POST /daemon/audio/reset
POST /daemon/watchdog/enable
POST /daemon/watchdog/disable
GET  /daemon/watchdog
```

Watchdog state persisted to `host_agent/state/watchdog.json` so it survives host_agent restart.

## Phase 2 — Zero backend proxy

File: [backend/app/routers/reachy.py](backend/app/routers/reachy.py)

Add a pass-through layer to host_agent. Use the existing `HOST_AGENT_URL` constant from [backend/app/routers/reachy_intent.py](backend/app/routers/reachy_intent.py) (line 29) — promote it to `backend/app/infrastructure/config.py` so both routers share it.

New endpoints (all under `/api/reachy/`):

```
POST /daemon/restart          → host_agent /daemon/restart
POST /daemon/start            → host_agent /daemon/start
POST /daemon/stop             → host_agent /daemon/stop
GET  /daemon/logs?tail=100    → host_agent /daemon/logs
GET  /daemon/diagnostics      → host_agent /daemon/diagnostics
POST /daemon/audio/reset      → host_agent /daemon/audio/reset
GET  /daemon/watchdog         → host_agent /daemon/watchdog
POST /daemon/watchdog         → host_agent /daemon/watchdog/enable|disable
```

Extend `GET /api/reachy/status` (router line 89) to also include `{supervisor: {...}, watchdog: {...}}` from host_agent when available. Degrade gracefully if host_agent is unreachable — the page must still render.

## Phase 3 — Sequence model + service

### DB model

File: [backend/app/db/models.py](backend/app/db/models.py)

```python
class ReachySequence(Base):
    __tablename__ = "reachy_sequences"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    steps: Mapped[list] = mapped_column(JSONB)   # [{clip: "yes1", gap_ms: 200, kind: "emotion"}]
    aliases: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(default=datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(default=datetime.now(UTC), onupdate=datetime.now(UTC))
```

Alembic migration `backend/app/migrations/versions/XXX_reachy_sequences.py`.

### Service

New file: `backend/app/services/reachy_sequence_service.py`

- `list_sequences()` → rows + merged aliases
- `get_sequence(name_or_alias)`
- `create_sequence(name, description, steps, aliases)` — validates every `clip` against `reachy_motion_library.resolve_motion()`. Rejects unknown clips with the list of missing names.
- `update_sequence(id, ...)`
- `delete_sequence(id)`
- `play_sequence(name)` — iterates steps, calls `reachy_service.play_emotion()` or `play_dance()` based on `kind`, sleeps `gap_ms / 1000` between steps, cancelable via the existing `/move/stop` flow. Returns a playback summary.

### Resolver integration

In [backend/app/services/reachy_motion_library.py](backend/app/services/reachy_motion_library.py):

- Add `resolve_motion_with_sequences(query, session, kind=None)` that tries DB sequences first, then falls back to the hardcoded library. Preserve the existing `resolve_motion()` for callers that don't have a session.
- In [backend/app/routers/reachy.py](backend/app/routers/reachy.py), `motion/play` (line 192), `motion/resolve` (line 201), and the emotion-parser path in [backend/app/services/reachy_emotion_parser.py](backend/app/services/reachy_emotion_parser.py) call the new variant. Sequences become LLM-invokable for free.

### Router

In [backend/app/routers/reachy.py](backend/app/routers/reachy.py):

```
GET    /sequences                → list
POST   /sequences                → create
GET    /sequences/{id_or_name}   → get
PATCH  /sequences/{id}           → update
DELETE /sequences/{id}           → delete
POST   /sequences/{id_or_name}/play → play now
```

Pydantic models in `backend/app/models/reachy_sequence.py`: `SequenceStep`, `SequenceCreate`, `SequenceUpdate`, `SequenceRead`, `SequencePlayResult`.

## Phase 4 — Frontend UI

### New hooks

File: [frontend/src/hooks/useReachyApi.ts](frontend/src/hooks/useReachyApi.ts)

Add alongside the existing hooks:

- `useDaemonStatus()` — wraps `/daemon/status`, polls every 5s while page is open
- `useDaemonLogs(tail)` — `/daemon/logs`, polls every 3s when the logs drawer is open, else disabled
- `useDaemonDiagnostics()` — `/daemon/diagnostics`, manual refetch + on-open
- `useRestartDaemon()` / `useStopDaemon()` / `useStartDaemon()`
- `useResetAudio()`
- `useWatchdog()` / `useSetWatchdog()`
- `useSequences()` / `useSequence(id)` / `useCreateSequence()` / `useUpdateSequence()` / `useDeleteSequence()` / `usePlaySequence()`

Query keys live in the existing key factory pattern.

### DaemonPanel component

New file: `frontend/src/components/reachy/DaemonPanel.tsx`

Rendered at the top of the Motion Library page, collapsed by default, auto-expanded when `connected === false`. Contents:

- Status row: `running` pill, PID, uptime, last-exit-code
- Big `Restart daemon` button; secondary `Stop`, `Start`
- Watchdog toggle + last-restart timeline (5 most recent)
- `Audio reset` button
- Diagnostics grid (motor states, USB devices, audio devices, CPU, mem, dataset preload)
- Logs drawer — tail -f style, auto-scroll, pause on scroll-up, copy button

### SequenceBuilder component

New file: `frontend/src/components/reachy/SequenceBuilder.tsx`

New section on [ReachyMotionLibraryPage.tsx](frontend/src/pages/ReachyMotionLibraryPage.tsx) titled **My Sequences**, rendered above the existing categorized-clip grid.

- Row of saved sequences as cards (same visual language as existing clip cards, purple accent to distinguish). Each card has Play, Edit, Delete.
- `+ New sequence` button opens a modal with the builder:
  - Name + description + aliases inputs
  - Steps list. Each step: clip-picker combobox (searches `useMotionLibrary()` results), gap-ms numeric input, drag handle to reorder, delete button
  - `+ Add step` appends a blank row
  - Live preview: sum of clip durations (approximated — see note below) + gaps
  - `Test play` button plays without saving
  - `Save` validates server-side; error state highlights the specific bad step
- Clip cards in the main grid get a small `+` button that adds them to an in-progress sequence if the builder is open. Keeps the flow "browse → drop into sequence".

Approximate clip duration: the motion library doesn't expose per-clip duration today. For the preview, use a constant 2s per emotion, 4s per dance as a rough estimate; refine later if the SDK exposes a real value. Document this limitation in the UI with a subtle "approx" label.

## Files touched

Create:
- `host_agent/supervisor.py`
- `host_agent/logs/` (gitignore)
- `host_agent/state/` (gitignore)
- `backend/app/services/reachy_sequence_service.py`
- `backend/app/models/reachy_sequence.py`
- `backend/app/migrations/versions/XXX_reachy_sequences.py`
- `frontend/src/components/reachy/DaemonPanel.tsx`
- `frontend/src/components/reachy/SequenceBuilder.tsx`

Modify:
- `host_agent/app.py` — mount supervisor routes, start watchdog task
- [backend/app/routers/reachy.py](backend/app/routers/reachy.py) — add daemon proxy + sequence routes, extend `/status`
- [backend/app/routers/reachy_intent.py](backend/app/routers/reachy_intent.py) — move `HOST_AGENT_URL` to shared config
- [backend/app/infrastructure/config.py](backend/app/infrastructure/config.py) — add `ZERO_HOST_AGENT_URL` setting
- [backend/app/db/models.py](backend/app/db/models.py) — `ReachySequence` model
- [backend/app/services/reachy_motion_library.py](backend/app/services/reachy_motion_library.py) — add `resolve_motion_with_sequences()`
- [backend/app/services/reachy_emotion_parser.py](backend/app/services/reachy_emotion_parser.py) — route lookups through the new resolver
- [frontend/src/hooks/useReachyApi.ts](frontend/src/hooks/useReachyApi.ts) — new hooks
- [frontend/src/pages/ReachyMotionLibraryPage.tsx](frontend/src/pages/ReachyMotionLibraryPage.tsx) — mount `DaemonPanel` at top, `SequenceBuilder` section above clip grid

## Build order

1. Host_agent supervisor + endpoints. Test each endpoint with curl against the Windows host.
2. Backend proxy + extended `/status`. Rebuild `zero-api`.
3. DB model + migration. Run alembic upgrade inside `zero-api`.
4. Sequence service + router endpoints, then resolver integration.
5. Frontend hooks.
6. `DaemonPanel`. Verify offline flow (stop daemon, confirm panel appears, click Restart).
7. `SequenceBuilder`. Verify create → play → LLM invocation path.

## Verification

**Offline management**
- With daemon running: `curl http://host:18794/daemon/status` returns `running: true`.
- Stop daemon: `curl -X POST http://host:18794/daemon/stop` — motion library page auto-expands DaemonPanel within 5s.
- Click Restart: daemon PID changes, status returns `running: true`, `connected` badge flips to online within ~15s (next poll of `/api/reachy/status`).
- Enable watchdog, kill daemon externally (`taskkill /F /PID ...`); watchdog auto-restarts within 60s; last-restart timeline updates.
- `/daemon/logs?tail=50` shows tail of `run_reachy_daemon.py` stdout.
- `/daemon/diagnostics` returns motor + USB + audio info.

**Sequence builder**
- Create sequence "happy_greeting" = [wave1 (gap 200ms), yes1 (gap 500ms), cheerful1].
- Click Play on the card — observe Reachy execute each clip with gaps.
- LLM path: from Hold-to-talk, get LLM to emit `[emotion:happy_greeting]` (e.g. ask "say hi happily"). The emotion parser resolves it via the new resolver and plays the sequence.
- Alias test: add alias "hi" → sequence plays when LLM emits `[emotion:hi]`.
- Edit sequence → change gap → re-play, observe new timing.
- Delete sequence → card disappears, LLM invocation of the old name falls through to the default library.

**Regression**
- Existing 100-clip cards still play (resolver falls through).
- Wake/Sleep/Stop still function.
- Persona selector still switches personas.
- `/api/reachy/status` remains backward compatible (new `supervisor`/`watchdog` fields are additive).

## Deployment

Per CLAUDE.md: `zero-api` is COPY'd, so rebuild after backend changes:
```
docker compose -f docker-compose.sprint.yml build --no-cache zero-api && docker compose -f docker-compose.sprint.yml up -d zero-api
```
Frontend `src/` is volume-mounted, so edits are live (no new npm packages here). host_agent runs on the host — user restarts it manually after `supervisor.py` lands.

## Out of scope

- Full-timeline tracks (head/antenna/sound on separate lanes) — can be added later without touching the DB schema since `steps` is JSONB.
- Per-clip duration API from the reachy-mini SDK — preview uses constants for now.
- Exporting sequences as shareable files — add later if needed.

---

# Follow-on fixes (2026-04-23)

## Context

Everything from the original plan shipped and was verified via curl. Two gaps
surfaced when trying to run the reachy_mini daemon end-to-end on this machine:

1. **Supervisor log capture is silent.** The daemon writes plenty of stdout
   (proven by launching `python run_reachy_daemon.py --mockup-sim` directly —
   we see `Starting Reachy Mini daemon port=8000`, kinematics init, etc). But
   when the supervisor spawns the same script via `subprocess.Popen(stdout=PIPE,
   text=True, bufsize=1)` with a `for line in proc.stdout:` reader thread, the
   ring buffer stays empty except for our `--- daemon spawned ---` banner.
   That's a Windows text-mode pipe + CPython read-ahead issue; the iterator
   doesn't yield lines until the pipe closes or the buffer is huge.

2. **GStreamer webcam error kills the media server.** Once we see the daemon
   output, it surfaces:
   ```
   ** WARNING **: "ksvideosrc" is deprecated and will be removed
   ERROR [reachy_mini.media.media_server] Error: gst-stream-error-quark:
     Internal data stream error. streaming stopped, reason not-negotiated (-4)
   ```
   The daemon tries to open a webcam via the deprecated Windows `ksvideosrc`
   element for WebRTC video. On a machine with no compatible webcam, the
   pipeline fails. Motion/emotion/dance still work, but the error spams logs
   and the video stream panel would be broken. reachy_mini's `Args` dataclass
   has a `no_media: bool = False` field that skips the media server entirely —
   exactly what we want for dev/headless use.

## Fix 1 — supervisor stdout capture

File: [host_agent/supervisor.py](host_agent/supervisor.py) lines 210–242.

Change the Popen kwargs and the reader loop:

- Drop `text=True`, `encoding="utf-8"`, `errors="replace"`, and `bufsize=1`.
- Set `bufsize=0` for raw unbuffered byte pipe.
- In `_reader_loop`, use `proc.stdout.readline()` in a `while True:` loop (not
  `for line in proc.stdout:`), decode each bytes result with
  `line.decode("utf-8", errors="replace").rstrip("\r\n")`, and append via the
  existing `_append_line` helper.

Why readline over iteration: CPython's text-mode iterator on a PIPE pre-reads
a chunk before yielding, so lines don't surface until the chunk fills. Raw
`readline()` returns as soon as a newline is seen by the OS, which matches the
daemon's actual flush cadence since we already pass `-u` to force unbuffered
child Python output.

No test changes needed; existing `/daemon/logs?tail=N` endpoint returns the
ring buffer unchanged from the caller's perspective.

## Fix 2 — disable video when no webcam

### 2a. Add `--no-media` flag to the launcher

File: [host_agent/run_reachy_daemon.py](host_agent/run_reachy_daemon.py) around
lines 47–86.

- Add CLI flag `--no-media` (argparse bool flag) alongside the existing
  `--mockup-sim` and `--no-preload` flags.
- Pass it through to the `Args(...)` call as `no_media=args.no_media`.

Rationale: the `Args` dataclass already has `no_media: bool = False`. We just
need to surface it as a launcher flag so dev/mockup runs can skip the media
server that fails on machines without a suitable webcam.

### 2b. Default dev scripts to `--no-media`

Files:
- [host_agent/run-supervisor.bat](host_agent/run-supervisor.bat)
- [host_agent/run-mockup.bat](host_agent/run-mockup.bat)

Change:
```
set "ZERO_REACHY_DAEMON_ARGS=--mockup-sim --no-preload"
```
to:
```
set "ZERO_REACHY_DAEMON_ARGS=--mockup-sim --no-preload --no-media"
```

Effect: when the supervisor spawns the daemon via `ZERO_REACHY_DAEMON_ARGS`
env var, it'll include `--no-media` so the WebRTC/ksvideosrc pipeline never
starts and the gstreamer error stops appearing. Production deployments with a
real Reachy can override by setting `ZERO_REACHY_DAEMON_ARGS` explicitly
without `--no-media`.

### 2c. Surface known daemon failure patterns in diagnostics

File: [host_agent/supervisor.py](host_agent/supervisor.py) `diagnostics()` method.

Add a lightweight pattern-scanner over the ring buffer that reports:

- `media_server_error: bool` — true if we saw
  `gst-stream-error-quark: Internal data stream error` in the buffer.
- `missing_reachy_mini: bool` — true if we saw
  `No module named 'reachy_mini'`.
- `hardware_missing: bool` — true if we saw a serialport enumeration error.

Return these under a new `known_issues` dict in the diagnostics payload.

DaemonPanel ([frontend/src/components/reachy/DaemonPanel.tsx](frontend/src/components/reachy/DaemonPanel.tsx))
`DiagnosticsGrid`: add one more card showing known issues as a colored list.
Each entry gets a one-line hint: "media server failed — daemon still usable
for motion. Launch with --no-media to silence."

## Files touched

Modify (all follow-on fixes):
- [host_agent/supervisor.py](host_agent/supervisor.py) — byte-mode reader,
  known-issue scanner in `diagnostics()`.
- [host_agent/run_reachy_daemon.py](host_agent/run_reachy_daemon.py) — new
  `--no-media` CLI flag wired to `Args(no_media=...)`.
- [host_agent/run-supervisor.bat](host_agent/run-supervisor.bat) — default
  `--no-media`.
- [host_agent/run-mockup.bat](host_agent/run-mockup.bat) — default `--no-media`.
- [frontend/src/components/reachy/DaemonPanel.tsx](frontend/src/components/reachy/DaemonPanel.tsx)
  — render `known_issues` card in `DiagnosticsGrid`.
- [frontend/src/hooks/useReachyApi.ts](frontend/src/hooks/useReachyApi.ts) —
  extend `DaemonDiagnostics` type with `known_issues`.

## Verification

1. **Reader fix:**
   - Launch host_agent (run-supervisor.bat or run-mockup.bat).
   - `curl -s http://127.0.0.1:18794/daemon/logs?tail=10` before start → only
     spawn banner (baseline).
   - `curl -X POST http://127.0.0.1:18794/daemon/start` → spawns daemon.
   - Within ~5s: `curl -s http://127.0.0.1:18794/daemon/logs?tail=20` should
     show `Starting Reachy Mini daemon port=8000 mockup=True preload=False`
     and subsequent lines. Before the fix this was empty for minutes.

2. **No-media fix:**
   - With `--no-media` in `ZERO_REACHY_DAEMON_ARGS`, daemon logs should NOT
     contain `gst-stream-error-quark` or `ksvideosrc` lines.
   - Daemon bound on `:8000` with `/api/daemon/status` responding within ~15s.

3. **Known-issues diagnostics:**
   - Set `ZERO_REACHY_DAEMON_ARGS` back to `--mockup-sim --no-preload` (no
     `--no-media`) to reproduce the gstreamer error.
   - `curl -s http://127.0.0.1:18794/daemon/diagnostics` includes
     `known_issues.media_server_error: true`.
   - In the browser: open Motion Library → DaemonPanel → click Diagnostics →
     see the red "media server error" card with the hint.

## Rebuild

- host_agent: restart via `run-supervisor.bat` or `run-mockup.bat` to pick up
  supervisor.py changes.
- zero-api: no changes, no rebuild needed.
- zero-ui: rebuild after DaemonPanel edits:
  `docker compose -f docker-compose.sprint.yml build zero-ui && docker compose -f docker-compose.sprint.yml up -d zero-ui`.
