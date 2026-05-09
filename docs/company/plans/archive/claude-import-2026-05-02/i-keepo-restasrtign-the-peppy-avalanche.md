# Reachy daemon restart loop — diagnosis and fix

## Context

User reports: "I keep restarting the robot and then it goes down."

The Reachy Mini daemon is supposed to come up at `:8000` after the host_agent supervisor spawns [host_agent/run_reachy_daemon.py](host_agent/run_reachy_daemon.py) via [host_agent/supervisor.py](host_agent/supervisor.py). It briefly looks like it's starting, then drops back offline within seconds. Watchdog notices, restarts. Fails the same way. Loop.

## Root cause

**Port 8000 is already in use when the launcher tries to bind.** Today's daemon log [host_agent/logs/reachy-daemon-20260425.log](host_agent/logs/reachy-daemon-20260425.log) shows the smoking gun at 07:08:20:

```
ERROR:    [Errno 10048] error while attempting to bind on address ('0.0.0.0', 8000):
          [winerror 10048] only one usage of each socket address (protocol/network address/port)
          is normally permitted
```

Plus the same error one second earlier on the WebRTC signaling socket:

```
Failed to start signalling server: Only one usage of each socket address ... (os error 10048)
```

Sequence per restart:
1. Launcher boots, motors check OK on COM3, datasets pre-cache fine.
2. uvicorn tries to bind 0.0.0.0:8000 → `[Errno 10048]`.
3. FastAPI lifespan calls "Application shutdown" — daemon goes through clean shutdown.
4. Process exits **code=1**.
5. `_probe_daemon_up()` in [supervisor.py:551](host_agent/supervisor.py#L551) keeps returning False.
6. `WATCHDOG_FAILURE_THRESHOLD = 6` × `WATCHDOG_POLL_INTERVAL_S = 10s` = 60s ([supervisor.py:63-64](host_agent/supervisor.py#L63-L64)).
7. Watchdog restarts. Same bind failure. Repeat.

`state/watchdog.json` confirms it: every restart event records `"was_running_before": false`. The daemon never finishes coming up. Today alone there are 3 manual restarts within 2 minutes (11:06, 11:07, 11:08), each with the same bind collision.

The launcher commit message itself flags this exact failure mode (cf06530):
> "Stop the desktop app before running this, or they will fight for :8000."

## What's holding port 8000

Most likely (in order):
1. **Pollen "Reachy Mini Control" desktop app is still running.** The supervisor falls back to that app's venv at [supervisor.py:45-50](host_agent/supervisor.py#L45-L50), so we know it's installed on this machine. If it auto-started and is sitting in the system tray, it's already serving the daemon on :8000 and the launcher can never bind.
2. **A previous launcher subprocess survived its parent.** On Windows, `subprocess.Popen` with `CREATE_NEW_PROCESS_GROUP` ([supervisor.py:208](host_agent/supervisor.py#L208)) means a force-killed host_agent leaves uvicorn children orphaned and still holding :8000. The python.exe count in the process list (20+ entries) hints at zombies.
3. **An mDNS reannounce race** — the log shows "mDNS service registered ... unregistered" within 3ms during the failed startup, but that's a symptom of shutdown, not the cause.

## Secondary issue (cosmetic, not the cause)

```
ERROR [reachy_mini.daemon.backend.robot.backend] Motor 'stewart_2' hardware errors: ['Overload Error']
```

stewart_2 needed a reboot at startup *and* threw Overload during shutdown. The Stewart platform (head pose) might be physically obstructed — antennas tangled, head jammed against something. Worth checking, but this happened *after* the bind failed during the daemon's clean shutdown, so it's not what's killing the process. It would, however, explain ungraceful exits if you ever do get past the bind issue.

## Fix (in order)

### Step 1 — kill whatever owns :8000

```bash
# From any shell:
netstat -ano | findstr :8000
# Note the PID in the last column. Then:
taskkill /F /PID <pid>
```

If it's the desktop app, also right-click its tray icon and Quit. Verify nothing answers `http://localhost:8000/api/daemon/status` before continuing.

### Step 2 — turn the watchdog off while we test

The watchdog currently masks the real error by spamming restarts every 60s. Hit `POST /daemon/watchdog?enabled=false` against host_agent (port 18794) or edit [host_agent/state/watchdog.json](host_agent/state/watchdog.json) and set `"enabled": false`. Restart host_agent so it picks that up.

### Step 3 — start the daemon by hand and watch it boot

```bash
cd c:/code/zero/host_agent
.venv/Scripts/python.exe run_reachy_daemon.py
```

You want to see, in order: motors check OK → datasets pre-loaded → "Daemon started successfully." → "Application startup complete." → no `[Errno 10048]`. If it reaches that state, the supervisor will be happy too.

### Step 4 — re-enable the watchdog

Once the daemon is healthy, flip the watchdog back on via the DaemonPanel or `POST /daemon/watchdog?enabled=true`.

### Step 5 (only if stewart_2 keeps overloading) — physically free the head

Power off, gently move antennas and head to neutral, check nothing is caught in the body rotation, then power back on. If the Overload Error persists, it's a hardware service item, not software.

## Files referenced

- [host_agent/run_reachy_daemon.py](host_agent/run_reachy_daemon.py) — launcher
- [host_agent/supervisor.py](host_agent/supervisor.py) — lifecycle + watchdog
- [host_agent/logs/reachy-daemon-20260425.log](host_agent/logs/reachy-daemon-20260425.log) — today's failure log
- [host_agent/state/watchdog.json](host_agent/state/watchdog.json) — restart history (every event `was_running_before: false`)

## Verification

After Step 3 succeeds:
1. `curl http://localhost:8000/api/daemon/status` returns 200 with `state: running`.
2. `curl http://localhost:18794/daemon/status` (host_agent) shows `running: true` with a stable `uptime_seconds` that climbs.
3. Open the DaemonPanel in the Motion Library UI — it should show green, no entries in `known_issues`, and the restart history stops growing.

## Optional hardening (separate, not required for this fix)

The supervisor restarts on a fixed cadence with no backoff. If you want to make this loop self-stop instead of pounding the port forever:

- In [supervisor.py:_watchdog_tick](host_agent/supervisor.py#L432), track consecutive *spawn* failures (not just probe failures) and disable the watchdog after N (e.g. 3) failed restarts in a row, so it surfaces the bind error instead of hiding it.
- In [supervisor.py:_start_locked](host_agent/supervisor.py#L180), preflight `socket.bind(('', 8000))` before spawning. If the port is in use, return a clean error to the DaemonPanel ("port 8000 already held by PID X") instead of letting uvicorn discover it 5 seconds later.

These are nice-to-haves; the immediate fix is Steps 1–3.
