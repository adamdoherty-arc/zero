@echo off
setlocal
cd /d "%~dp0"

if not exist "logs" mkdir "logs"
echo [%date% %time%] foreground launcher pid=%PROCESSID% cwd=%CD% >> "logs\host-agent-foreground.log"

set "ZERO_WAKE_MODE=off"
if "%ZERO_REACHY_DAEMON_ARGS%"=="" set "ZERO_REACHY_DAEMON_ARGS=--no-preload --no-media"
if "%ZERO_HOST_MIC_REJECT_DIGITAL_SILENCE%"=="" set "ZERO_HOST_MIC_REJECT_DIGITAL_SILENCE=true"
if "%HOST_AGENT_HOST%"=="" set "HOST_AGENT_HOST=0.0.0.0"
if "%HOST_AGENT_PORT%"=="" set "HOST_AGENT_PORT=18796"
if "%LOCALAPPDATA%"=="" set "LOCALAPPDATA=%USERPROFILE%\AppData\Local"
if exist "%LOCALAPPDATA%\Reachy Mini Control\.venv\Scripts\pythonw.exe" set "ZERO_REACHY_PYTHON=%LOCALAPPDATA%\Reachy Mini Control\.venv\Scripts\pythonw.exe"

echo [%date% %time%] starting uvicorn host=%HOST_AGENT_HOST% port=%HOST_AGENT_PORT% reachy_python=%ZERO_REACHY_PYTHON% >> "logs\host-agent-foreground.log"
".venv\Scripts\python.exe" -m uvicorn main:app --host "%HOST_AGENT_HOST%" --port "%HOST_AGENT_PORT%" --lifespan on --no-access-log --log-level warning >> "logs\host-agent-foreground.out.log" 2>> "logs\host-agent-foreground.err.log"
echo [%date% %time%] uvicorn exited code=%ERRORLEVEL% >> "logs\host-agent-foreground.log"
