param(
    [switch]$SkipFunnel,
    [switch]$EnableFunnel,
    [switch]$NoOpenBrowser
)

$ErrorActionPreference = "Continue"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$HostAgentTask = "ZeroHostAgent"
$ZeroTask = "Zero AI Auto-Start"
$HostAgentHealth = "http://127.0.0.1:18796/health"
$HostAgentBase = "http://127.0.0.1:18796"
$ReachyDaemonApi = "http://127.0.0.1:8000/api/daemon/status"
$AssistantApi = "http://127.0.0.1:18792/api/reachy/assistant"
$ApiHealth = "$AssistantApi/status"
$ReachyPage = "http://localhost:5173/reachy"

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
        [object]$Body = $null,
        [int]$TimeoutSec = 5
    )
    try {
        $params = @{
            Method = $Method
            Uri = $Uri
            TimeoutSec = $TimeoutSec
            ErrorAction = "Stop"
        }
        if ($null -ne $Body) {
            $params["ContentType"] = "application/json"
            $params["Body"] = ($Body | ConvertTo-Json -Depth 6)
        }
        return Invoke-RestMethod @params
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
        $result = Invoke-ZeroJson -Method GET -Uri $Uri -TimeoutSec 3
        if ($null -ne $result) {
            Write-Host "OK: $Label"
            return $result
        }
        Write-Host "Waiting for $Label ($i/$Attempts)..."
        Start-Sleep -Seconds $DelaySec
    }
    Write-Warning "$Label did not become ready."
    return $null
}

function Test-ZeroReachyDaemonApi {
    $daemon = Invoke-ZeroJson -Method GET -Uri $ReachyDaemonApi -TimeoutSec 4
    if ($null -eq $daemon) {
        return $null
    }

    if (($daemon.state -eq "running") -or ($daemon.type -eq "daemon_status")) {
        return $daemon
    }

    return $null
}

function Wait-ZeroReachyDaemonApi {
    param(
        [int]$Attempts = 20,
        [int]$DelaySec = 2
    )

    for ($i = 1; $i -le $Attempts; $i++) {
        $daemon = Test-ZeroReachyDaemonApi
        if ($null -ne $daemon) {
            Write-Host "OK: Reachy daemon API is reachable on :8000."
            return $daemon
        }

        Write-Host "Waiting for Reachy daemon API :8000 ($i/$Attempts)..."
        Start-Sleep -Seconds $DelaySec
    }

    Write-Warning "Reachy daemon API did not become ready on :8000."
    return $null
}

function Get-ZeroAssistantProblem {
    param([object]$Assistant)

    if ($null -eq $Assistant) {
        return "assistant status unavailable"
    }

    foreach ($step in $Assistant.steps) {
        if (($step.state -ne "ready") -and ($step.state -ne "skipped")) {
            return "$($step.label): $($step.detail)"
        }
    }

    if ($Assistant.body_activity -and ($Assistant.body_activity -ne "still")) {
        return "Body activity: $($Assistant.body_activity)"
    }

    return "unknown readiness issue"
}

function Wait-ZeroAssistantReady {
    param(
        [int]$Attempts = 12,
        [int]$DelaySec = 2,
        [int]$MinimumChecks = 5,
        [int]$ConsecutiveReady = 2,
        [switch]$SettleOnMotion
    )

    $last = $null
    $readyStreak = 0
    for ($i = 1; $i -le $Attempts; $i++) {
        $last = Invoke-ZeroJson -Method GET -Uri $ApiHealth -TimeoutSec 6
        if ($null -ne $last) {
            $bodyActivity = if ($last.body_activity) { $last.body_activity } else { "unknown" }
            $problem = Get-ZeroAssistantProblem -Assistant $last
            if (($last.state -eq "ready") -and (($bodyActivity -eq "still") -or ($bodyActivity -eq "unknown"))) {
                $readyStreak += 1
                if (($i -ge $MinimumChecks) -and ($readyStreak -ge $ConsecutiveReady)) {
                    Write-Host "OK: Reachy assistant is stable and ready; body activity is $bodyActivity."
                    return $last
                }
                Write-Host "Reachy assistant ready sample $readyStreak/$ConsecutiveReady; holding for stable startup ($i/$MinimumChecks)."
            } else {
                $readyStreak = 0
            }

            $needsSettle = $SettleOnMotion -and (
                ($bodyActivity -eq "moving") -or
                ($bodyActivity -eq "settling") -or
                ($bodyActivity -eq "shaky") -or
                ($problem -match "disabled/asleep") -or
                ($problem -match "jitter") -or
                ($problem -match "Settle") -or
                ($problem -match "motor")
            )

            if ($needsSettle) {
                Write-Host "Settling and enabling Reachy body before final readiness check ($bodyActivity): $problem"
                Invoke-ZeroJson -Method POST -Uri "$AssistantApi/settle" -Body @{
                    keep_motors_enabled = $true
                    neutral_pose = "default"
                } -TimeoutSec 20 | Out-Null
            } elseif ($last.state -ne "ready") {
                Write-Host "Reachy assistant reports '$($last.state)' while checks settle: $problem"
            }
        }

        Write-Host "Waiting for Reachy assistant ready state ($i/$Attempts)..."
        Start-Sleep -Seconds $DelaySec
    }

    if ($null -ne $last) {
        Write-Warning "Reachy assistant is not fully ready yet: $(Get-ZeroAssistantProblem -Assistant $last)"
    } else {
        Write-Warning "Reachy assistant status is unavailable."
    }
    return $last
}

function Wait-ZeroDocker {
    Write-ZeroStep "Waiting for Docker Desktop"
    while ($true) {
        docker info *> $null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "OK: Docker Desktop is ready."
            return
        }
        Write-Host "Docker is not ready yet; retrying in 10 seconds..."
        Start-Sleep -Seconds 10
    }
}

function Start-ZeroCompose {
    Write-ZeroStep "Starting Docker services"
    docker network create zero-network *> $null

    if (Test-Path (Join-Path $RepoRoot "docker-compose.searxng.yml")) {
        $searxOutput = docker compose -f docker-compose.searxng.yml up -d --no-recreate 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "SearXNG compose start failed."
            $searxOutput | Select-Object -Last 20 | ForEach-Object { Write-Warning $_.ToString() }
        }
    }

    $sprintOutput = docker compose -f docker-compose.sprint.yml up -d --no-recreate 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Sprint compose start failed."
        $sprintOutput | Select-Object -Last 20 | ForEach-Object { Write-Warning $_.ToString() }
    }

    $GatewayCompose = Join-Path $RepoRoot "docker-compose.yml"
    if (Test-Path $GatewayCompose) {
        $gatewayOutput = docker compose -f docker-compose.yml up -d --no-recreate 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "Gateway compose start failed."
            $gatewayOutput | Select-Object -Last 20 | ForEach-Object { Write-Warning $_.ToString() }
        }
    } else {
        Write-Host "Gateway compose file not present; skipping docker-compose.yml."
    }

    Write-ZeroStep "Waiting for zero-api"
    for ($i = 1; $i -le 24; $i++) {
        $health = docker inspect --format="{{.State.Health.Status}}" zero-api 2>$null
        if ($health -match "healthy") {
            Write-Host "OK: zero-api container is healthy."
            return
        }
        Write-Host "Waiting for zero-api health ($i/24)..."
        Start-Sleep -Seconds 5
    }
    Write-Warning "zero-api did not report healthy within 120 seconds."
}

function Register-ZeroAutoStartTask {
    Write-ZeroStep "Repairing Zero startup scheduled task"
    $ScriptPath = Join-Path $RepoRoot "start-zero.bat"
    $Action = New-ScheduledTaskAction -Execute $ScriptPath -WorkingDirectory $RepoRoot
    $Trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $Settings = New-ScheduledTaskSettingsSet `
        -RestartCount 999 `
        -RestartInterval (New-TimeSpan -Minutes 1) `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
        -MultipleInstances IgnoreNew
    $Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

    try {
        Unregister-ScheduledTask -TaskName $ZeroTask -Confirm:$false -ErrorAction SilentlyContinue
        Register-ScheduledTask `
            -TaskName $ZeroTask `
            -Action $Action `
            -Trigger $Trigger `
            -Settings $Settings `
            -Principal $Principal `
            -Description "Starts Zero AI stack and Reachy assistant services at user logon." | Out-Null
        Enable-ScheduledTask -TaskName $ZeroTask -ErrorAction SilentlyContinue | Out-Null
        Write-Host "OK: '$ZeroTask' registered and enabled."
    } catch {
        Write-Warning "Could not register '$ZeroTask': $($_.Exception.Message)"
    }
}

function Start-ZeroHostAgent {
    Write-ZeroStep "Starting host_agent and Reachy supervisor"
    $RegisterScript = Join-Path $RepoRoot "host_agent\register-autostart.ps1"
    if (Test-Path $RegisterScript) {
        powershell.exe -NoProfile -ExecutionPolicy Bypass -File $RegisterScript
    } else {
        Write-Warning "Missing host_agent register script at $RegisterScript"
    }

    try {
        Enable-ScheduledTask -TaskName $HostAgentTask -ErrorAction SilentlyContinue | Out-Null
        Start-ScheduledTask -TaskName $HostAgentTask -ErrorAction Stop
        Write-Host "OK: '$HostAgentTask' scheduled task started."
    } catch {
        Write-Warning "Scheduled task start failed: $($_.Exception.Message)"
        $Fallback = Join-Path $RepoRoot "host_agent\auto-restart.bat"
        if (Test-Path $Fallback) {
            Write-Host "Starting host_agent fallback wrapper directly."
            Start-Process -FilePath "cmd.exe" -ArgumentList "/c `"$Fallback`"" -WorkingDirectory (Join-Path $RepoRoot "host_agent") -WindowStyle Hidden | Out-Null
        }
    }

    $health = Wait-ZeroHttp -Uri $HostAgentHealth -Attempts 60 -DelaySec 2 -Label "host_agent"
    if ($null -eq $health) {
        Write-Warning "host_agent is still unreachable. Check host_agent\logs\auto-restart.log."
    }
    return $health
}

function Start-ZeroReachyDaemon {
    Write-ZeroStep "Starting Reachy daemon through host_agent"
    $health = Invoke-ZeroJson -Method GET -Uri $HostAgentHealth -TimeoutSec 3
    if ($null -eq $health) {
        Write-Warning "Skipping daemon startup because host_agent is unreachable."
        return
    }

    $watchdog = Invoke-ZeroJson -Method POST -Uri "$HostAgentBase/daemon/watchdog" -Body @{ enabled = $true } -TimeoutSec 5
    if ($null -eq $watchdog) {
        Write-Warning "Could not enable Reachy daemon watchdog."
    } else {
        Write-Host "OK: Reachy daemon watchdog enabled."
    }

    $status = Invoke-ZeroJson -Method GET -Uri "$HostAgentBase/daemon/status" -TimeoutSec 5
    if ($null -eq $status) {
        Write-Warning "Could not read Reachy daemon status."
        return
    }

    $daemonApi = Test-ZeroReachyDaemonApi
    if ($null -ne $daemonApi) {
        Write-Host "OK: Reachy daemon API is already serving on :8000."
        if ($status.running -ne $true) {
            Write-Host "Note: host_agent supervisor lost its child-process handle, but the daemon API is healthy."
        }
        return
    }

    if ($status.running -eq $true) {
        Write-Host "host_agent reports a daemon process; waiting for API readiness."
        Wait-ZeroReachyDaemonApi | Out-Null
        return
    }

    $started = Invoke-ZeroJson -Method POST -Uri "$HostAgentBase/daemon/start" -TimeoutSec 30
    if ($null -eq $started) {
        $daemonApi = Wait-ZeroReachyDaemonApi -Attempts 6 -DelaySec 2
        if ($null -eq $daemonApi) {
            Write-Warning "Reachy daemon start request failed and :8000 is not reachable."
        }
    } else {
        Write-Host "OK: Reachy daemon start requested."
        Wait-ZeroReachyDaemonApi | Out-Null
    }
}

function Activate-ZeroReachyAssistant {
    Write-ZeroStep "Activating Reachy assistant defaults"
    $body = @{
        persona = "assistant"
        voice_mode = "live"
        enable_ambient = $false
        start_daemon = $true
    }
    $assistant = Invoke-ZeroJson -Method POST -Uri "$AssistantApi/activate" -Body $body -TimeoutSec 20
    if ($null -eq $assistant) {
        Write-Warning "Could not activate Reachy assistant through zero-api."
        return
    }

    Write-Host "OK: Reachy assistant activation returned state '$($assistant.state)'."
    $final = Wait-ZeroAssistantReady -Attempts 12 -DelaySec 2 -SettleOnMotion
    if ($null -ne $final) {
        Write-Host "Final Reachy assistant state: $($final.state)"
        foreach ($step in $final.steps) {
            Write-Host " - $($step.id): $($step.state) $($step.detail)"
        }
    }
}

function Show-ZeroStatus {
    Write-ZeroStep "Current Zero status"
    docker ps --format "table {{.Names}}`t{{.Status}}" | Select-String "zero|shared-litellm|llama-cpp|vllm" | ForEach-Object { $_.Line }

    $hostTask = Get-ScheduledTask -TaskName $HostAgentTask -ErrorAction SilentlyContinue
    if ($hostTask) {
        Write-Host "$HostAgentTask task: $($hostTask.State)"
    } else {
        Write-Warning "$HostAgentTask task missing."
    }

    $zeroTaskObj = Get-ScheduledTask -TaskName $ZeroTask -ErrorAction SilentlyContinue
    if ($zeroTaskObj) {
        Write-Host "$ZeroTask task: $($zeroTaskObj.State)"
    } else {
        Write-Warning "$ZeroTask task missing."
    }

    $assistant = Invoke-ZeroJson -Method GET -Uri "http://127.0.0.1:18792/api/reachy/assistant/status" -TimeoutSec 5
    if ($null -ne $assistant) {
        Write-Host "Reachy assistant state: $($assistant.state)"
        if ($assistant.body_activity) {
            Write-Host "Reachy body activity: $($assistant.body_activity)"
        }
        foreach ($step in $assistant.steps) {
            Write-Host " - $($step.id): $($step.state) $($step.detail)"
        }
    }
}

Write-Host "========================================"
Write-Host " ZERO AI - Starting Stack + Reachy"
Write-Host " $(Get-Date)"
Write-Host "========================================"

Wait-ZeroDocker
Register-ZeroAutoStartTask
Start-ZeroCompose
Start-ZeroHostAgent | Out-Null
Start-ZeroReachyDaemon
$api = Wait-ZeroHttp -Uri $ApiHealth -Attempts 10 -DelaySec 2 -Label "Reachy assistant API"
if ($null -ne $api) {
    Activate-ZeroReachyAssistant
}
Show-ZeroStatus

if ($EnableFunnel -and -not $SkipFunnel) {
    $Tailscale = "C:\Program Files\Tailscale\tailscale.exe"
    if (Test-Path $Tailscale) {
        Write-ZeroStep "Starting Tailscale Funnel"
        Start-Process -FilePath $Tailscale -ArgumentList "funnel 18789" -WindowStyle Hidden | Out-Null
        Write-Host "OK: requested Tailscale Funnel for port 18789."
    }
} else {
    Write-Host "Tailscale Funnel skipped. Use -EnableFunnel only when you want external access."
}

if (-not $NoOpenBrowser) {
    Start-Process $ReachyPage
}

Write-Host ""
Write-Host "Zero is running. Reachy Assistant page: $ReachyPage"
