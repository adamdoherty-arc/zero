@echo off
REM Minimal host_agent that only serves /daemon/* endpoints (supervisor).
REM Skips the audio/whisper imports so the DaemonPanel works even if the
REM full host_agent hangs on sounddevice/pyaudio device enumeration.
REM
REM Uses the Reachy Mini Control desktop app's bundled Python 3.12 venv,
REM which already has fastapi + uvicorn + reachy-mini installed.

set "VENV_PY=%LOCALAPPDATA%\Reachy Mini Control\.venv\Scripts\python.exe"
if not exist "%VENV_PY%" (
  echo [supervisor] Reachy Mini Control venv not found at %VENV_PY%
  echo Install the Pollen Robotics Reachy Mini Control desktop app first.
  exit /b 1
)

REM Default to real hardware. Set ZERO_REACHY_DAEMON_ARGS manually before
REM invoking this bat (or pass args via POST /daemon/start body) to use
REM --mockup-sim for development without a connected Reachy.
set "ZERO_REACHY_DAEMON_ARGS=--no-preload --no-media"

cd /d "%~dp0"
if "%HOST_AGENT_HOST%"=="" set "HOST_AGENT_HOST=0.0.0.0"
if "%HOST_AGENT_PORT%"=="" set "HOST_AGENT_PORT=18796"

echo [supervisor] starting on %HOST_AGENT_HOST%:%HOST_AGENT_PORT% (daemon supervisor only, mockup-sim)
"%VENV_PY%" -u -m uvicorn supervisor_only:app --host %HOST_AGENT_HOST% --port %HOST_AGENT_PORT%
