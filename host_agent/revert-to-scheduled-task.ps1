# Reverts ZeroHostAgent from the NSSM service (broken auth) back to the
# scheduled task with a 90s logon delay. Run from the elevated PowerShell:
#   .\revert-to-scheduled-task.ps1
#
# After this:
#   - NSSM service is removed
#   - Scheduled task is re-registered with a 90s logon delay
#   - host_agent comes back up via the task
# Total cost of the Docker boot race is then handled by:
#   1. The 90s task delay (gives Docker Desktop time to come up)
#   2. The Docker readiness probe inside host_agent (Layers 1-2)
#   3. The Smart Re-link UI button (Layer 6)
# No Windows password is stored anywhere.

[CmdletBinding()]
param()

$ErrorActionPreference = "Continue"
$ServiceName = "ZeroHostAgent"
$NssmPath    = "C:\code\zero\host_agent\bin\nssm.exe"
$RegisterScript = "C:\code\zero\host_agent\register-autostart.ps1"

# --- 1. Stop and remove the NSSM service ---
$svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($svc) {
    Write-Host "[revert] Stopping NSSM service..."
    try { Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue } catch {}
    Start-Sleep -Seconds 2
    if (Test-Path -LiteralPath $NssmPath) {
        Write-Host "[revert] Removing NSSM service..."
        & $NssmPath remove $ServiceName confirm 2>&1 | Out-Host
    } else {
        Write-Host "[revert] NSSM not found; using sc.exe delete..."
        & sc.exe delete $ServiceName 2>&1 | Out-Host
    }
} else {
    Write-Host "[revert] No NSSM service to remove."
}

# --- 2. Kill any leftover host_agent processes on :18796 ---
Write-Host "[revert] Clearing any leftover processes on :18796..."
$portOwners = (Get-NetTCPConnection -LocalPort 18796 -State Listen -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique) | Where-Object { $_ -gt 0 }
foreach ($pidValue in $portOwners) {
    try {
        Write-Host "[revert]  - killing pid $pidValue"
        Stop-Process -Id $pidValue -Force -ErrorAction SilentlyContinue
    } catch {}
}
Start-Sleep -Seconds 1

# --- 3. Re-register the scheduled task with 90s logon delay ---
if (-not (Test-Path -LiteralPath $RegisterScript)) {
    throw "register-autostart.ps1 not found at $RegisterScript"
}
Write-Host "[revert] Re-registering scheduled task with 90s logon delay..."
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $RegisterScript

# --- 4. Verify ---
Start-Sleep -Seconds 2
$task = Get-ScheduledTask -TaskName $ServiceName -ErrorAction SilentlyContinue
if ($task) {
    Write-Host ""
    Write-Host "[revert] === RESULT ==="
    Write-Host "Task:    $($task.TaskName)"
    Write-Host "State:   $($task.State)"
    $trig = $task.Triggers[0]
    Write-Host "Trigger: AtLogOn (delay: $($trig.Delay))"
    $info = Get-ScheduledTaskInfo -TaskName $ServiceName
    Write-Host "LastRun:    $($info.LastRunTime)"
    Write-Host "LastResult: $($info.LastTaskResult)"
} else {
    Write-Warning "[revert] Scheduled task did not register."
}

# --- 5. Wait for host_agent /health (started by the task we just registered) ---
Write-Host ""
Write-Host "[revert] Waiting for host_agent /health on :18796..."
$attempts = 0
while ($attempts -lt 60) {
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:18796/health" -UseBasicParsing -TimeoutSec 2
        Write-Host "[revert] host_agent up after $attempts seconds (status=$($r.StatusCode))"
        break
    } catch {
        Start-Sleep -Seconds 1
        $attempts++
    }
}
if ($attempts -ge 60) {
    Write-Warning "[revert] host_agent did not respond within 60s. Try Start-ScheduledTask -TaskName $ServiceName"
}

Write-Host ""
Write-Host "[revert] DONE. Going forward:"
Write-Host "  Get-ScheduledTask -TaskName $ServiceName"
Write-Host "  Start-ScheduledTask -TaskName $ServiceName"
Write-Host "  Get-Content C:\code\zero\host_agent\logs\auto-restart.log -Tail 20 -Wait"
