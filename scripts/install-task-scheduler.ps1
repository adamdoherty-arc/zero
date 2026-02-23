# Install Zero as a Windows Task Scheduler job for auto-start on boot
# Run as Administrator: powershell -ExecutionPolicy Bypass -File install-task-scheduler.ps1

$taskName = "Zero AI Auto-Start"
$scriptPath = "C:\code\zero\start-zero.bat"

# Remove existing task if present
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

# Create trigger: at startup with 60s delay
$trigger = New-ScheduledTaskTrigger -AtStartup
$trigger.Delay = "PT60S"

# Create action
$action = New-ScheduledTaskAction -Execute $scriptPath -WorkingDirectory "C:\code\zero"

# Settings: restart on failure, run whether user is logged in or not
$settings = New-ScheduledTaskSettingsSet `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 5) `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0)

# Register the task
Register-ScheduledTask `
    -TaskName $taskName `
    -Trigger $trigger `
    -Action $action `
    -Settings $settings `
    -RunLevel Highest `
    -Description "Starts Zero AI stack (Docker containers) on boot"

Write-Host "Task '$taskName' registered successfully."
Write-Host "Zero will auto-start 60 seconds after boot with 3 retry attempts."
