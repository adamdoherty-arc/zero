param(
    [string]$HostAgentHost = $env:HOST_AGENT_HOST,
    [string]$HostAgentPort = $env:HOST_AGENT_PORT,
    [string]$PidFile = (Join-Path $PSScriptRoot "state\host-agent.pid")
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if ([string]::IsNullOrWhiteSpace($HostAgentHost)) {
    $HostAgentHost = "0.0.0.0"
}
if ([string]::IsNullOrWhiteSpace($HostAgentPort)) {
    $HostAgentPort = "18796"
}

$env:ZERO_WAKE_MODE = "off"
if ([string]::IsNullOrWhiteSpace($env:ZERO_REACHY_DAEMON_ARGS)) {
    $env:ZERO_REACHY_DAEMON_ARGS = "--no-preload --no-media"
}

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$pidDir = Split-Path -Parent $PidFile
if (-not (Test-Path -LiteralPath $pidDir)) {
    New-Item -ItemType Directory -Path $pidDir -Force | Out-Null
}
$args = @(
    "-m",
    "uvicorn",
    "main:app",
    "--host",
    $HostAgentHost,
    "--port",
    $HostAgentPort,
    "--lifespan",
    "on",
    "--no-access-log",
    "--log-level",
    "warning"
)

$proc = Start-Process -WindowStyle Hidden -FilePath $python -ArgumentList $args -WorkingDirectory $PSScriptRoot -PassThru
Set-Content -LiteralPath $PidFile -Value ([string]$proc.Id) -Encoding ASCII
