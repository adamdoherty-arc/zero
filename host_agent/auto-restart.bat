@echo off
REM Thin shim: defer to auto-restart.ps1 (the primary supervisor wrapper).
REM Kept so legacy entry points (older docs, manual invocations, the
REM ZeroHostAgent scheduled task before NSSM migration) still work.
REM auto-restart.ps1 owns the supervisor loop, the optional Docker-readiness
REM gate (set ZERO_WAIT_FOR_DOCKER=true to enable), and structured logging.
REM See host_agent/install-service.ps1 to migrate to a real Windows service.
setlocal
cd /d "%~dp0"
if not exist "logs" mkdir "logs"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0auto-restart.ps1" %*
exit /b %ERRORLEVEL%
