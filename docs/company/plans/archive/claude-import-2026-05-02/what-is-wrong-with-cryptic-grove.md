# What's wrong with connecting to Reachy

## Context

The UI says **"host_agent unreachable"** because the host_agent process on `127.0.0.1:18794` is dead. The "Restart daemon" button proxies through host_agent, so it fails too. There are three nested problems, only one of which is "connecting to Reachy" in the obvious sense:

### 1. host_agent is down (the immediate cause of the UI error)

- `netstat -ano | grep 18794` → nothing listening.
- `Get-Process python` → no uvicorn/host_agent process. Only cozempic + MCP servers.
- Scheduled task `ZeroHostAgent`: `LastRunTime = 11:43:17 AM`, `LastTaskResult = 3221225786`. That code is `0xC000013A` = `STATUS_CONTROL_C_EXIT`. The wrapper got Ctrl-C / window-close.
- [host_agent/logs/auto-restart.log](c:\code\zero\host_agent\logs\auto-restart.log) tail confirms: at 11:46:33 the spawned Reachy daemon hit `forrtl: error (200): program aborting due to window-CLOSE event` (Fortran runtime fatal abort from numpy/scipy/MKL when the console receives `CTRL_CLOSE_EVENT`), followed by `^C` killing the auto-restart loop.

### 2. This is the third recurrence of the same crash in three days

Same `forrtl ... window-CLOSE event` signature appears at:
- 2026-04-25 16:14 → host_agent down for ~25 hours (until 04-26 17:40)
- 2026-04-26 19:37 → host_agent down overnight
- 2026-04-27 11:46 → still down right now

The "three-layer self-heal" in [CLAUDE.md](c:\code\zero\CLAUDE.md) is not actually self-healing this failure mode. Reasons:
- **Layer 2 (auto-restart.bat)** runs uvicorn in the **foreground of the same console** as the wrapper. When Windows sends `CTRL_CLOSE_EVENT` to the console, both the child (host_agent) and the parent (cmd.exe running the bat) die simultaneously, so `goto loop` never executes.
- [host_agent/supervisor.py:204-220](c:\code\zero\host_agent\supervisor.py#L204-L220) does set `CREATE_NEW_PROCESS_GROUP` for the spawned Reachy daemon, but that only blocks `CTRL_BREAK_EVENT`, **not** `CTRL_CLOSE_EVENT`. Without `DETACHED_PROCESS` (or stdio redirection + `CREATE_NO_WINDOW`), the daemon is still attached to the wrapper's console and dies with it.
- **Layer 3 (Scheduled Task)** is registered as `AT LOGON` only with retries on "failure". `STATUS_CONTROL_C_EXIT` (3221225786) is interpreted by Task Scheduler as a clean user-initiated exit, so it does **not** retry. `NumberOfMissedRuns = 0` confirms it never re-fired.

### 3. The Reachy hardware itself was already in a bad state when host_agent was up

[host_agent/logs/reachy-daemon-20260427.log:46](c:\code\zero\host_agent\logs\reachy-daemon-20260427.log#L46) at 11:45:29 — `ERROR Failed to start daemon: No motors detected. Check if the power supply is connected and turned on!` And the wrapper log shows `reachy_watchdog_failure consecutive=1..6` repeating before the crash. So even if host_agent comes back, Reachy will still be offline until the user power-cycles or replugs the robot. The dangling `LISTENING 11440` on `:8000` from `netstat` is a stale daemon process that survived the close (it was launched manually, on a different console, before today's session).

### Bonus: log rotation is broken

`reachy-daemon-20260425.log` is **132 MB** in a single day. The supervisor's `log_writer` is appending without size-based rotation. Won't break Reachy, but flagging because daily logs at this size will fill the disk in weeks.

---

## Recommended approach

Fix in three layers, in order. The first two layers get you talking to Reachy again today; layer three is the durable fix.

### Layer A — Immediate recovery (manual, ~30 seconds)

1. Kill the stale daemon hanging onto `:8000` (PID 11440 from a previous manual launch — predates today's failed host_agent run; will collide with the fresh daemon host_agent will spawn):
   ```powershell
   Stop-Process -Id 11440 -Force
   ```
   Verify nothing on `:8000`: `netstat -ano | grep ":8000\s"` returns empty.

2. Start host_agent via the scheduled task (preferred over launching the bat directly so it stays under Task Scheduler supervision):
   ```powershell
   Start-ScheduledTask -TaskName ZeroHostAgent
   ```
   Within ~10s, `:18794` should listen. Confirm: `curl http://127.0.0.1:18794/health` returns `200`.

3. Re-arm the daemon watchdog (it self-disables when host_agent restarts):
   ```bash
   curl -X POST http://127.0.0.1:18794/daemon/watchdog -H "Content-Type: application/json" -d '{"enabled":true}'
   ```

4. **Power-cycle Reachy** (the user has to do this — it's the "no motors detected" half). Unplug the robot's USB-C and PSU, wait 5s, replug both. Within 60s the watchdog will spawn a healthy daemon and the UI badge flips green.

### Layer B — Stop console close-events from killing the stack

Two surgical changes to [host_agent/auto-restart.bat](c:\code\zero\host_agent\auto-restart.bat) and [host_agent/register-autostart.ps1](c:\code\zero\host_agent\register-autostart.ps1):

1. **Run uvicorn in a detached subprocess from the wrapper.** Replace line 21 of `auto-restart.bat`:
   ```bat
   REM Old (foreground, dies on console close):
   ".venv\Scripts\python.exe" -m uvicorn main:app --host 127.0.0.1 --port 18794 >> "%LOGFILE%" 2>&1

   REM New (detached, survives parent console close):
   start "host_agent" /B /WAIT ".venv\Scripts\pythonw.exe" -m uvicorn main:app --host 127.0.0.1 --port 18794 >> "%LOGFILE%" 2>&1
   ```
   `pythonw.exe` (no console) + `start /B` decouples from the parent's console handle, so a `CTRL_CLOSE_EVENT` on the parent cmd.exe does not propagate. `/WAIT` keeps the wrapper blocking until uvicorn exits, preserving the restart loop.

2. **Make the scheduled task hidden (no console window) and resilient to user-cancel exit codes.** In [host_agent/register-autostart.ps1](c:\code\zero\host_agent\register-autostart.ps1):
   - Add `-WindowStyle Hidden` to the action's argument list (or wrap in `powershell.exe -WindowStyle Hidden`).
   - Set `RestartCount = 999`, `RestartInterval = (New-TimeSpan -Minutes 1)` — already there, but also flip `Settings.AllowDemandStart = $true` and add a second trigger: `New-ScheduledTaskTrigger -AtStartup` (so it survives a logoff/logon round-trip, not only the first user logon).
   - Add `Settings.RestartOnIdle = $true` and `Settings.MultipleInstances = IgnoreNew` to dedupe.

3. **Belt-and-braces in supervisor.py.** [host_agent/supervisor.py:208](c:\code\zero\host_agent\supervisor.py#L208) currently uses `CREATE_NEW_PROCESS_GROUP`. Switch to:
   ```python
   creationflags = (
       subprocess.CREATE_NEW_PROCESS_GROUP
       | subprocess.DETACHED_PROCESS
       | subprocess.CREATE_NO_WINDOW
   )
   ```
   And keep `stdout=PIPE`/`stderr=STDOUT` — the pipe doesn't require a console.

### Layer C — Fix log rotation (low priority but real)

In [host_agent/supervisor.py](c:\code\zero\host_agent\supervisor.py), the `_open_log_for_today` helper (search for it; it's where `_log_fh` is assigned) opens a daily file in append mode with no size cap. Wrap with `logging.handlers.RotatingFileHandler` — `maxBytes=10_000_000`, `backupCount=5`. Or simpler: add a `_LOG_MAX_BYTES = 50_000_000` check before every write in `_reader_loop` and rotate to `<name>.1` when exceeded.

---

## Critical files

- [host_agent/auto-restart.bat](c:\code\zero\host_agent\auto-restart.bat) — line 21, the uvicorn launch.
- [host_agent/register-autostart.ps1](c:\code\zero\host_agent\register-autostart.ps1) — task definition.
- [host_agent/supervisor.py:208](c:\code\zero\host_agent\supervisor.py#L208) — daemon Popen creationflags.
- [host_agent/supervisor.py](c:\code\zero\host_agent\supervisor.py) — log writer for rotation (Layer C).
- [CLAUDE.md](c:\code\zero\CLAUDE.md) "Reachy Self-Heal" section — update to reflect the new launch model after Layer B.

## Verification

After Layer A:
- `netstat -ano | grep 18794` shows a `LISTENING` row.
- `curl http://127.0.0.1:18794/health` → 200 with `{"status":"ok"}`.
- UI Reachy panel: red "host_agent unreachable" pill clears within ~5s.
- `curl http://127.0.0.1:18794/daemon/status` returns `running:true` after Reachy is power-cycled.

After Layer B (stress test):
1. Start host_agent via the scheduled task.
2. Find the cmd.exe PID hosting `auto-restart.bat`: `Get-Process cmd | Where-Object {$_.MainWindowTitle -like "*auto-restart*"}`.
3. `Stop-Process -Id <cmd-pid> -Force` (simulates window close).
4. Within 60s, `:18794` should still be listening (because uvicorn is detached) **or** Task Scheduler relaunches the wrapper (because the new `AtStartup` trigger + `RestartCount` fires on the actual exit code, not user-cancel).
5. Re-run 2-3 of times to confirm it's stable.

After Layer C:
- Spam-write 100 MB to a fake daemon log; confirm rotation creates `<name>.1` and live writes go to a fresh file.
