param(
    [string]$HostAgentHost = $env:HOST_AGENT_HOST,
    [string]$HostAgentPort = $env:HOST_AGENT_PORT,
    [string]$LogFile = (Join-Path $PSScriptRoot "logs\auto-restart.log")
)

$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot

$bootstrapLogDir = Join-Path $PSScriptRoot "logs"
if (-not (Test-Path -LiteralPath $bootstrapLogDir)) {
    New-Item -ItemType Directory -Path $bootstrapLogDir -Force | Out-Null
}
$bootstrapLog = Join-Path $bootstrapLogDir "auto-restart-bootstrap.log"
try {
    Add-Content -LiteralPath $bootstrapLog -Value "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] [auto-restart] bootstrap pid=$PID args=$($MyInvocation.Line)" -Encoding UTF8
} catch {
}

function Write-BootstrapTrace {
    param([string]$Message)
    try {
        Add-Content -LiteralPath $bootstrapLog -Value "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] [auto-restart] $Message" -Encoding UTF8
    } catch {
    }
}

if ([string]::IsNullOrWhiteSpace($HostAgentHost)) { $HostAgentHost = "0.0.0.0" }
if ([string]::IsNullOrWhiteSpace($HostAgentPort)) { $HostAgentPort = "18796" }
Write-BootstrapTrace "resolved host=$HostAgentHost port=$HostAgentPort log=$LogFile"

$env:HOST_AGENT_HOST = $HostAgentHost
$env:HOST_AGENT_PORT = $HostAgentPort
$env:ZERO_WAKE_MODE = "off"
if ([string]::IsNullOrWhiteSpace($env:ZERO_REACHY_DAEMON_ARGS)) {
    $env:ZERO_REACHY_DAEMON_ARGS = "--no-preload --no-media"
}

$logDir = Split-Path -Parent $LogFile
if (-not (Test-Path -LiteralPath $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}
$stateDir = Join-Path $PSScriptRoot "state"
if (-not (Test-Path -LiteralPath $stateDir)) {
    New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
}
$pidFile = Join-Path $stateDir "host-agent.pid"
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$healthUrl = "http://127.0.0.1:${HostAgentPort}/health"
Write-BootstrapTrace "initialized healthUrl=$healthUrl python=$python"

function Write-HostAgentLog {
    param([string]$Message)
    try {
        Add-Content -LiteralPath $LogFile -Value $Message -Encoding UTF8
    } catch {
        # Never let logging failure take down the supervisor loop.
    }
}

function Test-DockerReady {
    # Non-blocking Docker readiness probe. Returns $true if `docker info`
    # succeeds within ~5s. Used purely for observability — host_agent's
    # internal docker_readiness module owns the application-layer wait.
    try {
        $null = & docker.exe info --format '{{.ServerVersion}}' 2>$null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Write-DockerStateProbe {
    param([string]$Phase = "tick")
    $ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    $ready = Test-DockerReady
    $stateText = "waiting"
    if ($ready) { $stateText = "ready" }
    $payload = @{
        ts = $ts
        event = "docker_probe"
        phase = $Phase
        state = $stateText
    } | ConvertTo-Json -Compress
    Write-HostAgentLog "[$ts] [auto-restart] $payload"
    return $ready
}

function Wait-DockerReady {
    # Optional blocking wait. Off by default; enable with
    # ZERO_WAIT_FOR_DOCKER=true env var if you want the wrapper to gate
    # uvicorn startup on Docker readiness instead of relying on the
    # in-process readiness probe to handle the wait gracefully.
    if (-not ($env:ZERO_WAIT_FOR_DOCKER -eq "true" -or $env:ZERO_WAIT_FOR_DOCKER -eq "1")) {
        return
    }
    $delaySeconds = 5
    $maxDelaySeconds = 60
    $attempt = 0
    while (-not (Test-DockerReady)) {
        $attempt++
        $ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
        Write-HostAgentLog "[$ts] [auto-restart] {""event"":""docker_wait"",""attempt"":$attempt,""sleep_s"":$delaySeconds}"
        Start-Sleep -Seconds $delaySeconds
        if ($delaySeconds -lt $maxDelaySeconds) {
            $delaySeconds = [Math]::Min([int]($delaySeconds * 1.7), $maxDelaySeconds)
        }
    }
    $ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    Write-HostAgentLog "[$ts] [auto-restart] {""event"":""docker_ready"",""attempts"":$attempt}"
}

function Test-HostAgentHealth {
    try {
        $owners = @(Get-PortOwnerPids -Port ([int]$HostAgentPort))
        return ($owners.Count -gt 0)
    }
    catch {
        Write-BootstrapTrace "health check exception=$($_.Exception.Message)"
        return $false
    }
}

function Get-PortOwnerPids {
    param([int]$Port)
    try {
        $pattern = "[:\.]$Port\s+.*\s+LISTENING\s+(\d+)\s*$"
        return @(
            & netstat.exe -ano -p tcp 2>$null |
                Where-Object { $_ -match $pattern } |
                ForEach-Object { [int]$Matches[1] } |
                Sort-Object -Unique |
                Where-Object { $_ -gt 0 }
        )
    } catch {
        return @()
    }
}

function Get-ProcessTreePids {
    param([int]$RootProcessId)
    if ($RootProcessId -le 0) { return @() }
    $all = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Select-Object ProcessId, ParentProcessId)
    $childrenByParent = @{}
    foreach ($proc in $all) {
        $parent = [int]$proc.ParentProcessId
        if (-not $childrenByParent.ContainsKey($parent)) {
            $childrenByParent[$parent] = New-Object System.Collections.Generic.List[int]
        }
        $childrenByParent[$parent].Add([int]$proc.ProcessId)
    }
    $ordered = New-Object System.Collections.Generic.List[int]
    $stack = New-Object System.Collections.Generic.Stack[int]
    $stack.Push($RootProcessId)
    while ($stack.Count -gt 0) {
        $current = $stack.Pop()
        if ($ordered.Contains($current)) { continue }
        $ordered.Add($current)
        if ($childrenByParent.ContainsKey($current)) {
            foreach ($child in $childrenByParent[$current]) {
                $stack.Push($child)
            }
        }
    }
    $orderedArray = @($ordered.ToArray())
    [array]::Reverse($orderedArray)
    return @($orderedArray)
}

function Stop-ProcessIdFast {
    param([int]$ProcessId)
    if ($ProcessId -le 0) { return }
    try {
        $proc = [System.Diagnostics.Process]::GetProcessById($ProcessId)
    } catch {
        return
    }
    try {
        $proc.Kill()
        if (-not $proc.WaitForExit(2000)) {
            Write-HostAgentLog "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] [auto-restart] process $ProcessId did not exit after Kill()."
        }
    } catch {
        Write-HostAgentLog "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] [auto-restart] Kill() failed for pid ${ProcessId}: $($_.Exception.Message)"
    } finally {
        try { $proc.Dispose() } catch {}
    }
}

function Stop-HostAgentTree {
    param([int]$ProcessId)
    if ($ProcessId -le 0) { return }
    $tree = @(Get-ProcessTreePids -RootProcessId $ProcessId)
    if (-not $tree -or $tree.Count -eq 0) {
        $tree = @($ProcessId)
    }
    foreach ($treePid in $tree) {
        Stop-ProcessIdFast -ProcessId ([int]$treePid)
    }
}

function Start-HostAgent {
    $uvicornArgs = @(
        "-m", "uvicorn", "main:app",
        "--host", $HostAgentHost,
        "--port", $HostAgentPort,
        "--lifespan", "on",
        "--no-access-log",
        "--log-level", "warning"
    )
    $argLine = ($uvicornArgs | ForEach-Object {
        $item = [string]$_
        if ($item -match '[\s"]') {
            '"' + ($item -replace '"', '\"') + '"'
        } else {
            $item
        }
    }) -join " "
    $psi = [System.Diagnostics.ProcessStartInfo]::new()
    $psi.FileName = $python
    $psi.Arguments = $argLine
    $psi.WorkingDirectory = $PSScriptRoot
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $proc = [System.Diagnostics.Process]::Start($psi)
    Set-Content -LiteralPath $pidFile -Value ([string]$proc.Id) -Encoding ASCII
    return $proc
}

function Invoke-HostAgentForeground {
    $uvicornArgs = @(
        "-m", "uvicorn", "main:app",
        "--host", $HostAgentHost,
        "--port", $HostAgentPort,
        "--lifespan", "on",
        "--no-access-log",
        "--log-level", "warning"
    )
    $dateStamp = Get-Date -Format "yyyyMMdd"
    $stdoutLog = Join-Path $logDir "host-agent-$dateStamp.out.log"
    $stderrLog = Join-Path $logDir "host-agent-$dateStamp.err.log"
    Set-Content -LiteralPath $pidFile -Value ([string]$PID) -Encoding ASCII
    Write-BootstrapTrace "foreground exec python=$python"
    & $python @uvicornArgs >> $stdoutLog 2>> $stderrLog
    $exitCode = if ($null -eq $LASTEXITCODE) { 0 } else { $LASTEXITCODE }
    Write-HostAgentLog "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] [auto-restart] uvicorn exited with code $exitCode, restarting in 5s ..."
    Start-Sleep -Seconds 5
}

Write-DockerStateProbe -Phase "wrapper_boot" | Out-Null
Wait-DockerReady

while ($true) {
    try {
        Write-BootstrapTrace "loop start"
        $healthy = Test-HostAgentHealth
        Write-BootstrapTrace "health result=$healthy"
        if ($healthy) {
            Write-HostAgentLog "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] [auto-restart] host_agent health is healthy; monitoring ..."
        } else {
            Write-BootstrapTrace "scanning port owners"
            foreach ($owner in Get-PortOwnerPids -Port ([int]$HostAgentPort)) {
                Write-HostAgentLog "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] [auto-restart] stale host_agent port owner pid $owner; killing before launch ..."
                Stop-HostAgentTree -ProcessId $owner
            }
            Write-DockerStateProbe -Phase "before_launch" | Out-Null
            Write-BootstrapTrace "launch branch"
            Write-HostAgentLog "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] [auto-restart] launching host_agent ..."
            Invoke-HostAgentForeground
            continue
        }

        $failures = 0
        while ($true) {
            Start-Sleep -Seconds 10
            if (Test-HostAgentHealth) {
                $failures = 0
                continue
            }
            $failures++
            if ($failures -lt 3) {
                Write-HostAgentLog "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] [auto-restart] host_agent health check failed ($failures/3), retrying ..."
                continue
            }
            $pidText = if (Test-Path -LiteralPath $pidFile) { Get-Content -LiteralPath $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1 } else { "" }
            $hostAgentPid = 0
            [void][int]::TryParse([string]$pidText, [ref]$hostAgentPid)
            Write-HostAgentLog "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] [auto-restart] host_agent health check failed 3/3; killing pid $hostAgentPid and port owners ..."
            Stop-HostAgentTree -ProcessId $hostAgentPid
            foreach ($owner in Get-PortOwnerPids -Port ([int]$HostAgentPort)) {
                Stop-HostAgentTree -ProcessId $owner
            }
            Start-Sleep -Seconds 5
            break
        }
    } catch {
        Write-HostAgentLog "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] [auto-restart] supervisor loop error: $($_.Exception.Message)"
        Start-Sleep -Seconds 5
    }
}
