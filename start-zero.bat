@echo off
REM Single-command Zero + Reachy assistant startup.
REM The PowerShell orchestrator repairs scheduled tasks, starts Docker,
REM starts host_agent, enables the Reachy watchdog, and opens /reachy.

cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-zero.ps1" %*
