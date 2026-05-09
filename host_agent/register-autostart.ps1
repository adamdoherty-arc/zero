# Registers a Windows Scheduled Task that launches host_agent at user logon.
# Idempotent: re-running replaces the existing task.

$TaskName = "ZeroHostAgent"
$ScriptPath = Join-Path $PSScriptRoot "auto-restart.ps1"
$ForegroundLauncherPath = Join-Path $PSScriptRoot "run-host-agent-foreground.cmd"

if (-not (Test-Path $ForegroundLauncherPath)) {
    throw "run-host-agent-foreground.cmd not found at $ForegroundLauncherPath"
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
        [void]$proc.WaitForExit(2000)
    } catch {
        Write-Warning "[register-autostart] Kill() failed for process $($ProcessId): $($_.Exception.Message)"
    } finally {
        try { $proc.Dispose() } catch {}
    }
}

function Invoke-TaskkillTree {
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

function Stop-ZeroHostAgentOrphans {
    $patterns = @(
        [regex]::Escape("host_agent\auto-restart.bat"),
        [regex]::Escape("host_agent\auto-restart.ps1"),
        [regex]::Escape("host_agent\run-host-agent-foreground.cmd"),
        [regex]::Escape("host_agent\run-hidden-uvicorn.ps1"),
        "-m\s+uvicorn\s+main:app\b.*--port\s+`"?18796`"?",
        "run_reachy_daemon\.py"
    )
    $self = $PID
    for ($attempt = 1; $attempt -le 5; $attempt++) {
        $matches = Get-CimInstance Win32_Process |
            Where-Object {
                $cmd = $_.CommandLine
                if (-not $cmd) { return $false }
                if ([int]$_.ProcessId -eq [int]$self) { return $false }
                foreach ($pattern in $patterns) {
                    if ($cmd -match $pattern) { return $true }
                }
                return $false
            }

        if (-not $matches) {
            return
        }

        foreach ($proc in $matches) {
            try {
                Invoke-TaskkillTree -ProcessId ([int]$proc.ProcessId)
                Write-Host "[register-autostart] Stopped stale host_agent process $($proc.ProcessId) ($($proc.Name))."
            } catch {
                Write-Warning "[register-autostart] Could not stop stale host_agent process $($proc.ProcessId): $($_.Exception.Message)"
            }
        }

        Start-Sleep -Milliseconds 700
    }
}

# Re-registering a scheduled task does not terminate action processes it
# launched previously. Clean up old wrappers first so one uvicorn owns the host-agent port
# and realtime mic websockets do not get cut by competing relaunchers.
Stop-ZeroHostAgentOrphans

# Remove any existing task with this name
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

# Run host_agent in the foreground under a hidden scheduled task. Windows'
# task restart policy relaunches it if the process exits; host_agent's own
# watchdog keeps the Reachy daemon alive.
$action = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument "/d /s /c `"`"$ForegroundLauncherPath`"`"" `
    -WorkingDirectory $PSScriptRoot

# AtLogOn trigger only — adding AtStartup requires admin/RunLevel Highest.
# AtLogOn fires on every interactive logon (which is what we have anyway,
# since LogonType is Interactive), so this is the practical equivalent.
#
# 90s logon delay: Docker Desktop's WSL2 daemon takes 60-180 s to be reachable
# after a Windows cold boot. Without the delay, host_agent fires at logon and
# the Reachy daemon supervisor races Docker. The application-layer Docker
# readiness probe (host_agent/docker_readiness.py) handles this gracefully
# anyway, but the delay turns a "boot-race window we can survive" into "boot
# race that mostly doesn't happen." Defense in depth.
$logonTrigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$logonTrigger.Delay = "PT90S"  # ISO 8601 duration: 90 seconds
$triggers = @($logonTrigger)

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
    -MultipleInstances IgnoreNew `
    -Hidden
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $triggers `
    -Settings $settings `
    -Principal $principal `
    -Description "Self-healing supervisor for Zero host_agent (port 18796) and Reachy daemon (port 8000)." | Out-Null

Enable-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue | Out-Null
Start-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue | Out-Null

Write-Host "[register-autostart] Scheduled Task '$TaskName' registered."
Write-Host "[register-autostart] Scheduled Task '$TaskName' started."
Write-Host "[register-autostart] Trigger: at logon ($env:USERNAME)"
Write-Host "[register-autostart] Action:  $ForegroundLauncherPath"
Write-Host "[register-autostart] Restart: every 1 min on failure, up to 999 times"
Write-Host ""
Write-Host "Verify: Get-ScheduledTask -TaskName $TaskName"
Write-Host "Run now: Start-ScheduledTask -TaskName $TaskName"
Write-Host "Remove: Unregister-ScheduledTask -TaskName $TaskName -Confirm:`$false"
