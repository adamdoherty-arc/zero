@echo off
REM Start the Reachy Mini headless daemon on :8000.
REM This REPLACES the Pollen Robotics Reachy Mini Desktop App — stop the
REM desktop app first (or it will fight for the port) and run this instead.
REM
REM First run will install the reachy-mini SDK (~200 MB of wheels) into
REM host_agent/.venv. Subsequent runs skip the install.
REM
REM Flags:
REM    run_reachy_daemon.bat                start with dataset preload
REM    run_reachy_daemon.bat --no-preload   skip dataset preload
REM    run_reachy_daemon.bat --mockup-sim   fake hardware for dev
REM
REM Ctrl+C stops it cleanly.

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [reachy] creating venv...
    python -m venv .venv
)

echo [reachy] installing/updating deps (first run pulls reachy-mini + motor controller)...
".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt
if errorlevel 1 (
    echo [reachy] pip install failed. Inspect requirements.txt.
    exit /b 1
)

echo [reachy] launching headless daemon on :8000 (Ctrl+C to stop)...
".venv\Scripts\python.exe" run_reachy_daemon.py %*
