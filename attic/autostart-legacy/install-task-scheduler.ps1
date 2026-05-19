# Install Zero as a Windows Task Scheduler job for auto-start at user logon.
# This mirrors start-zero.ps1 so the task is repairable without admin rights.
# Run: powershell -ExecutionPolicy Bypass -File scripts\install-task-scheduler.ps1

$repoRoot = Split-Path -Parent $PSScriptRoot
$taskName = "Zero AI Auto-Start"
$scriptPath = Join-Path $repoRoot "start-zero.bat"

# Remove existing task if present
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

# Create trigger: at user logon. This avoids requiring an elevated principal
# while still making Zero available after every normal Windows boot/login.
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

# Create action
$action = New-ScheduledTaskAction -Execute $scriptPath -WorkingDirectory $repoRoot

# Settings: retry aggressively and do not kill the long-running startup helper.
$settings = New-ScheduledTaskSettingsSet `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
    -MultipleInstances IgnoreNew

$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

# Register the task
Register-ScheduledTask `
    -TaskName $taskName `
    -Trigger $trigger `
    -Action $action `
    -Settings $settings `
    -Principal $principal `
    -Description "Starts Zero AI stack, repairs host_agent, and prepares Reachy assistant at logon." | Out-Null

Enable-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue | Out-Null

Write-Host "Task '$taskName' registered successfully."
Write-Host "Zero will auto-start when $env:USERNAME logs in, with 999 retry attempts."
