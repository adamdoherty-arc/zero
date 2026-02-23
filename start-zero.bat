@echo off
REM Zero Startup Script (OpenClaw.ai)
REM Add this to Windows Task Scheduler for auto-start on boot
REM Trigger: At Startup, Delay 60s. Action: Run this script.

cd /d c:\code\zero

echo ========================================
echo  ZERO AI - Starting Stack
echo  %date% %time%
echo ========================================

REM Wait for Docker Desktop to be ready
echo Waiting for Docker Desktop...
:docker_wait
docker info >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo   Docker not ready, retrying in 10s...
    timeout /t 10 /nobreak >nul
    goto docker_wait
)
echo Docker Desktop is ready.

REM Ensure the external network exists
docker network create zero-network 2>nul

REM Start SearXNG (web search engine)
echo [1/3] Starting SearXNG...
docker compose -f docker-compose.searxng.yml up -d
if %ERRORLEVEL% neq 0 echo WARNING: SearXNG failed to start

REM Start Sprint stack (API + UI + PostgreSQL)
echo [2/3] Starting Sprint stack (zero-api, zero-ui, zero-postgres)...
docker compose -f docker-compose.sprint.yml up -d
if %ERRORLEVEL% neq 0 echo WARNING: Sprint stack failed to start

REM Start Gateway (OpenClaw.ai bot)
echo [3/3] Starting Gateway...
docker compose -f docker-compose.yml up -d
if %ERRORLEVEL% neq 0 echo WARNING: Gateway failed to start

REM Wait for services to become healthy (up to 60s)
echo Waiting for services to be healthy...
set /a retries=0
:health_wait
set /a retries+=1
if %retries% gtr 12 (
    echo WARNING: Health check timeout after 60s. Some services may still be starting.
    goto show_status
)
timeout /t 5 /nobreak >nul

REM Check if zero-api is healthy
docker inspect --format="{{.State.Health.Status}}" zero-api 2>nul | findstr healthy >nul
if %ERRORLEVEL% neq 0 (
    echo   Waiting for zero-api to be healthy... (attempt %retries%/12)
    goto health_wait
)
echo zero-api is healthy!

:show_status
echo.
echo ========================================
echo  Container Status
echo ========================================
docker ps --format "table {{.Names}}\t{{.Status}}" | findstr zero

REM Enable Tailscale Funnel for public access
echo.
echo Starting Tailscale Funnel...
"C:\Program Files\Tailscale\tailscale.exe" funnel 18789

echo.
echo Zero is running.
