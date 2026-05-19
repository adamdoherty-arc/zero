@echo off
REM host_agent foreground launcher - user-launched only.
REM
REM Launched by scripts\start-zero.ps1 as part of the Zero bootstrap, or
REM directly when the user only wants the Reachy supervisor without the
REM Docker stack. Closing this console stops host_agent; supervisor's
REM atexit hook reaps the Reachy daemon subprocess.
REM
REM Robot is OFF until the user clicks 'Start daemon' in the UI's DaemonPanel.

setlocal EnableDelayedExpansion
cd /d "%~dp0"
title Zero - host_agent

REM ---------------------------------------------------------------------------
REM Pre-check: is port 18796 already bound?
REM ---------------------------------------------------------------------------
netstat -ano | findstr ":18796 " | findstr "LISTENING" >nul 2>&1
if !ERRORLEVEL! EQU 0 (
    echo.
    echo [start-zero] Reachy host_agent is already running on :18796.
    echo              Open http://localhost:5173/zero to use it.
    echo.
    pause
    exit /b 0
)

REM ---------------------------------------------------------------------------
REM Bootstrap venv + deps on first run.
REM ---------------------------------------------------------------------------
if not exist ".venv\Scripts\python.exe" (
    echo [start-zero] Creating Python venv ^(first run^)...
    python -m venv .venv
    if !ERRORLEVEL! NEQ 0 (
        echo [start-zero] ERROR: python -m venv failed. Is Python on PATH?
        pause
        exit /b 1
    )
)

if not exist ".venv\Scripts\python.exe" (
    echo [start-zero] ERROR: venv python missing after create.
    pause
    exit /b 1
)

echo [start-zero] Refreshing dependencies...
".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt

REM ---------------------------------------------------------------------------
REM Launch uvicorn in the foreground. Closing this window stops the stack
REM (uvicorn's atexit hooks tear down the Reachy daemon subprocess too).
REM ---------------------------------------------------------------------------
if "%HOST_AGENT_HOST%"=="" set "HOST_AGENT_HOST=127.0.0.1"
if "%HOST_AGENT_PORT%"=="" set "HOST_AGENT_PORT=18796"

if not exist "logs" mkdir "logs"

echo.
echo ================================================================
echo  Zero Robot host_agent - listening on %HOST_AGENT_HOST%:%HOST_AGENT_PORT%
echo  Open http://localhost:5173/zero in your browser.
echo  Close this window to stop the Reachy stack.
echo ================================================================
echo.

".venv\Scripts\python.exe" -m uvicorn main:app --host %HOST_AGENT_HOST% --port %HOST_AGENT_PORT% --lifespan on --no-access-log --log-level info

echo.
echo [start-zero] host_agent exited with code %ERRORLEVEL%.
pause
endlocal
