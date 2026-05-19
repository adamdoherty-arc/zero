# Autostart Legacy (quarantined 2026-05-17)

These scripts implemented the old "auto-start Zero at Windows logon" model. They were quarantined here because they aggressively self-healed the autostart machinery — every run of `start-zero-legacy.ps1` re-registered the `Zero AI Auto-Start` scheduled task, re-registered `ZeroHostAgent`, and enabled the Reachy daemon watchdog. That meant any cleanup got undone the next time the orchestrator fired.

The new model: Zero is **user-launched**. A single desktop shortcut (`Start Zero`) brings up the Docker stack (the personal assistant) and host_agent. The robot itself (Reachy daemon) stays off until the user clicks Start in DaemonPanel — robot toggle lives entirely in the UI. Nothing auto-starts at Windows boot.

## Files here

- **`install-task-scheduler.ps1`** — standalone installer that registered `Zero AI Auto-Start` (logon trigger, ran `start-zero.bat`). Replaced by user-launched shortcut.
- **`start-zero-legacy.ps1`** — the orchestrator. Did real work (Docker compose up, host_agent launch, browser open) AND dangerous work (registered scheduled tasks, enabled watchdog, started ZeroHostAgent task). The new `scripts\start-zero.ps1` keeps only the real work.

## Do NOT

- Re-install these scripts. They contradict the user-launched model documented in `CLAUDE.md` → "Reachy stack — user-launched (no autostart, no watchdog)".
- Copy `Register-ZeroAutoStartTask`, `Start-ZeroHostAgent` (the task-registration variant), or `POST /daemon/watchdog` calls back into the live tree.

## What to use instead

- `scripts\start-zero.ps1` — the new clean orchestrator.
- `host_agent\start-zero.bat` — host_agent-only launch (called by the new orchestrator).
- `host_agent\install-shortcut.ps1` — installs the desktop shortcut.
