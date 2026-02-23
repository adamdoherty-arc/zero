# Install Zero Gateway Auto-Update as a Windows Task Scheduler job
# Run as Administrator: powershell -ExecutionPolicy Bypass -File scripts/install-gateway-updater.ps1

$taskName = "Zero Gateway Auto-Update"
$scriptPath = "C:\code\zero\scripts\update-gateway.ps1"
$workingDir = "C:\code\zero"

# Remove existing task if present
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

# Create trigger: daily at 4:30 AM
$trigger = New-ScheduledTaskTrigger -Daily -At "4:30AM"

# Create action: run PowerShell with the update script
$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-ExecutionPolicy Bypass -NonInteractive -File `"$scriptPath`"" `
    -WorkingDirectory $workingDir

# Settings: restart on failure, run whether user is logged in
$settings = New-ScheduledTaskSettingsSet `
    -RestartCount 2 `
    -RestartInterval (New-TimeSpan -Minutes 10) `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

# Register the task
Register-ScheduledTask `
    -TaskName $taskName `
    -Trigger $trigger `
    -Action $action `
    -Settings $settings `
    -RunLevel Highest `
    -Description "Checks for new OpenClaw releases and upgrades the Zero gateway container daily"

Write-Host "Task '$taskName' registered successfully."
Write-Host "The gateway will be checked for updates daily at 4:30 AM."
Write-Host ""
Write-Host "To run manually: powershell -ExecutionPolicy Bypass -File scripts/update-gateway.ps1"
Write-Host "To dry-run:      powershell -ExecutionPolicy Bypass -File scripts/update-gateway.ps1 -DryRun"
