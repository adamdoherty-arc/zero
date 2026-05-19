param(
    [switch]$NoOpenBrowser,
    [switch]$NoHostAgent
)

# Zero personal-assistant bootstrap (user-launched, NOT autostart).
#
# Brings up the Docker stack (the personal assistant) and host_agent
# (the Reachy supervisor, idle until the user starts the daemon from the UI).
# Does NOT register any scheduled task, install any service, or enable any
# watchdog. The Reachy daemon itself stays OFF; the user toggles it from
# DaemonPanel in the UI.
#
# Legacy autostart-self-healing orchestrator lives in attic/autostart-legacy/.

$ErrorActionPreference = "Continue"
$RepoRoot       = Split-Path -Parent $PSScriptRoot
$HostAgentHealth = "http://127.0.0.1:18796/health"
$ApiHealth       = "http://127.0.0.1:18792/health"
$Dashboard       = "http://localhost:5173/"

Set-Location $RepoRoot

function Write-ZeroStep {
    param([string]$Message)
    Write-Host ""
    Write-Host "== $Message =="
}

function Invoke-ZeroJson {
    param(
        [Parameter(Mandatory=$true)][string]$Method,
        [Parameter(Mandatory=$true)][string]$Uri,
        [int]$TimeoutSec = 5
    )
    try {
        return Invoke-RestMethod -Method $Method -Uri $Uri -TimeoutSec $TimeoutSec -ErrorAction Stop
    } catch {
        return $null
    }
}

function Wait-ZeroHttp {
    param(
        [Parameter(Mandatory=$true)][string]$Uri,
        [int]$Attempts = 30,
        [int]$DelaySec = 2,
        [string]$Label = $Uri
    )
    for ($i = 1; $i -le $Attempts; $i++) {
        $r = Invoke-ZeroJson -Method GET -Uri $Uri -TimeoutSec 3
        if ($null -ne $r) {
            Write-Host "OK: $Label"
            return $r
        }
        Write-Host "Waiting for $Label ($i/$Attempts)..."
        Start-Sleep -Seconds $DelaySec
    }
    Write-Warning "$Label did not become ready."
    return $null
}

function Wait-ZeroDocker {
    Write-ZeroStep "Waiting for Docker Desktop"
    for ($i = 1; $i -le 30; $i++) {
        docker info *> $null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "OK: Docker Desktop is ready."
            return $true
        }
        Write-Host "Docker is not ready yet; retrying in 5 seconds ($i/30)..."
        Start-Sleep -Seconds 5
    }
    Write-Warning "Docker Desktop did not become ready within 150 seconds. Aborting."
    return $false
}

function Start-ZeroCompose {
    Write-ZeroStep "Starting Zero Docker stack"
    docker network create zero-network *> $null

    $sprintOutput = docker compose -f docker-compose.sprint.yml up -d --no-recreate 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Sprint compose start failed."
        $sprintOutput | Select-Object -Last 20 | ForEach-Object { Write-Warning $_.ToString() }
    }

    $searxCompose = Join-Path $RepoRoot "docker-compose.searxng.yml"
    if (Test-Path $searxCompose) {
        $searxOutput = docker compose -f docker-compose.searxng.yml up -d --no-recreate 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "SearXNG compose start failed."
            $searxOutput | Select-Object -Last 20 | ForEach-Object { Write-Warning $_.ToString() }
        }
    }

    $gatewayCompose = Join-Path $RepoRoot "docker-compose.yml"
    if (Test-Path $gatewayCompose) {
        $gatewayOutput = docker compose -f docker-compose.yml up -d --no-recreate 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "Gateway compose start failed."
            $gatewayOutput | Select-Object -Last 20 | ForEach-Object { Write-Warning $_.ToString() }
        }
    }

    Write-ZeroStep "Waiting for zero-api container health"
    for ($i = 1; $i -le 36; $i++) {
        $health = docker inspect --format="{{.State.Health.Status}}" zero-api 2>$null
        if ($health -match "healthy") {
            Write-Host "OK: zero-api container is healthy."
            break
        }
        Write-Host "Waiting for zero-api health ($i/36)..."
        Start-Sleep -Seconds 5
    }

    # Handle Docker Desktop's post-restart port-bind race: if any zero-*
    # containers got stuck in Created state (port not released by wslrelay
    # in time), re-issue compose up to wake them.
    $stuck = docker ps -a --filter "status=created" --format "{{.Names}}" 2>$null | Select-String "^zero-"
    if ($stuck) {
        Write-Host "Found $(($stuck | Measure-Object).Count) containers stuck in Created state. Retrying compose up..."
        Start-Sleep -Seconds 8
        docker compose -f docker-compose.sprint.yml up -d 2>&1 | Out-Null
    }
}

function Start-ZeroHostAgent {
    Write-ZeroStep "Starting host_agent (Reachy supervisor)"

    if (Wait-ZeroHttp -Uri $HostAgentHealth -Attempts 1 -DelaySec 1 -Label "host_agent (pre-check)") {
        Write-Host "host_agent already running; skipping launch."
        return
    }

    $batPath = Join-Path $RepoRoot "host_agent\start-zero.bat"
    if (-not (Test-Path $batPath)) {
        Write-Warning "host_agent\start-zero.bat missing; cannot launch supervisor."
        return
    }

    # Spawn in its own foreground console window so the user can see logs and
    # close it to stop host_agent (atexit hook in supervisor.py reaps the
    # Reachy daemon subprocess too).
    Start-Process -FilePath "cmd.exe" `
        -ArgumentList @('/c','start','"Zero host_agent"','/D',(Join-Path $RepoRoot 'host_agent'),'cmd','/k',$batPath) `
        -WorkingDirectory (Join-Path $RepoRoot 'host_agent') | Out-Null

    Wait-ZeroHttp -Uri $HostAgentHealth -Attempts 45 -DelaySec 2 -Label "host_agent" | Out-Null
}

# ---- Main ----

Write-Host "========================================"
Write-Host " ZERO - personal assistant bootstrap"
Write-Host " $(Get-Date)"
Write-Host "========================================"
Write-Host "Robot (Reachy daemon) will stay OFF; toggle it from the UI when needed."

if (-not (Wait-ZeroDocker)) {
    Read-Host "Press Enter to exit"
    exit 1
}

Start-ZeroCompose

Wait-ZeroHttp -Uri $ApiHealth -Attempts 36 -DelaySec 5 -Label "zero-api HTTP" | Out-Null

if (-not $NoHostAgent) {
    Start-ZeroHostAgent
} else {
    Write-Host "Skipping host_agent (-NoHostAgent). Robot controls in the UI will show offline."
}

if (-not $NoOpenBrowser) {
    Write-ZeroStep "Opening dashboard"
    Start-Process $Dashboard
}

Write-Host ""
Write-Host "Zero is up. Dashboard: $Dashboard"
Write-Host "  - Personal assistant is running (Docker stack)."
Write-Host "  - host_agent runs in its own console window; close it to stop the robot supervisor."
Write-Host "  - Robot is OFF. Open /reachy in the UI and click 'Start daemon' to bring up the Reachy hardware."
