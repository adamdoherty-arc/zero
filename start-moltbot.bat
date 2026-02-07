@echo off
REM Moltbot Startup Script
REM Add this to Windows Task Scheduler for auto-start on boot

cd /d c:\code\moltbot

REM Start Docker containers
docker-compose up -d

REM Enable Tailscale Funnel for public access
"C:\Program Files\Tailscale\tailscale.exe" funnel 18789
