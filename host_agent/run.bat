@echo off
REM Start the Zero Host Audio Agent. Creates .venv if missing, installs deps,
REM then runs uvicorn on HOST_AGENT_HOST:HOST_AGENT_PORT.

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [host_agent] creating venv...
    python -m venv .venv
)

echo [host_agent] installing/updating deps...
".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt

if "%HOST_AGENT_HOST%"=="" set "HOST_AGENT_HOST=0.0.0.0"
if "%HOST_AGENT_PORT%"=="" set "HOST_AGENT_PORT=18796"

echo [host_agent] starting on %HOST_AGENT_HOST%:%HOST_AGENT_PORT% ...
".venv\Scripts\python.exe" -m uvicorn main:app --host %HOST_AGENT_HOST% --port %HOST_AGENT_PORT%
