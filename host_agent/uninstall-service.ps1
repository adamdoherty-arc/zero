# Removes the ZeroHostAgent NSSM service and optionally restores the
# scheduled-task fallback.

[CmdletBinding()]
param(
    [string]$ServiceName = "ZeroHostAgent",
    [string]$NssmPath = (Join-Path $PSScriptRoot "bin\nssm.exe"),
    [switch]$RestoreScheduledTask
)

$ErrorActionPreference = "Stop"

$svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($null -ne $svc) {
    Write-Host "[uninstall-service] Stopping service '$ServiceName'..."
    try { Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue } catch {}
    Start-Sleep -Seconds 2
    if (Test-Path -LiteralPath $NssmPath) {
        Write-Host "[uninstall-service] Removing service via NSSM..."
        & $NssmPath remove $ServiceName confirm 2>&1 | Out-Host
    } else {
        Write-Host "[uninstall-service] NSSM not found; using sc.exe delete..."
        & sc.exe delete $ServiceName 2>&1 | Out-Host
    }
} else {
    Write-Host "[uninstall-service] Service '$ServiceName' not installed; nothing to remove."
}

if ($RestoreScheduledTask) {
    $register = Join-Path $PSScriptRoot "register-autostart.ps1"
    if (Test-Path -LiteralPath $register) {
        Write-Host "[uninstall-service] Re-registering ZeroHostAgent scheduled task..."
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $register
    } else {
        Write-Warning "[uninstall-service] register-autostart.ps1 not found; skipping fallback restore."
    }
}

Write-Host "[uninstall-service] Done."
