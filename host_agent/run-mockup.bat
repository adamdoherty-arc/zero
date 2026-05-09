@echo off
REM Start host_agent pointing at the Reachy Mini Control venv (Python 3.12 +
REM reachy-mini already installed) and default daemon spawns to --mockup-sim
REM so users without attached hardware can still test the supervisor.

set "VENV_PY=%LOCALAPPDATA%\Reachy Mini Control\.venv\Scripts\python.exe"
if not exist "%VENV_PY%" (
  echo [host_agent] Reachy Mini Control venv not found at %VENV_PY%
  echo Install the Pollen Robotics Reachy Mini Control desktop app first.
  exit /b 1
)

REM Name says mockup because this launcher was originally for mockup-sim dev.
REM Now defaults to real hardware; add --mockup-sim below if you want to run
REM without a connected Reachy.
set "ZERO_REACHY_DAEMON_ARGS=--no-preload --no-media"

cd /d "%~dp0"
if "%HOST_AGENT_HOST%"=="" set "HOST_AGENT_HOST=0.0.0.0"
if "%HOST_AGENT_PORT%"=="" set "HOST_AGENT_PORT=18796"

echo [host_agent] starting uvicorn on %HOST_AGENT_HOST%:%HOST_AGENT_PORT% ^(mockup daemon mode^)
"%VENV_PY%" -u -m uvicorn main:app --host %HOST_AGENT_HOST% --port %HOST_AGENT_PORT%
