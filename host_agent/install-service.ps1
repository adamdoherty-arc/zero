# Installs ZeroHostAgent as a real Windows service via NSSM.
#
# Why NSSM and not a native pywin32 service?
#   - pywin32 services are fragile around stdin/stdout redirection and Python
#     subprocess management on Windows. NSSM wraps any executable cleanly.
#   - NSSM gives us native restart-on-exit, log redirection, AppRotate, and
#     SERVICE_DELAYED_AUTO_START in one tool.
#
# Why user-context (not SYSTEM)?
#   - host_agent uses WASAPI (per-session) to capture from the Reachy USB mic
#     and play through the Reachy speaker. SYSTEM context can't see those
#     devices. NSSM supports running as the logged-in user via ObjectName.
#
# Why SERVICE_DELAYED_AUTO_START?
#   - Windows starts delayed-auto services ~120s after boot, by which time
#     Docker Desktop's WSL2 daemon is usually up. host_agent's in-process
#     docker_readiness module handles any remaining lag gracefully.
#
# Idempotent: running twice replaces the existing service in place.

[CmdletBinding()]
param(
    [string]$ServiceName = "ZeroHostAgent",
    [string]$NssmPath = (Join-Path $PSScriptRoot "bin\nssm.exe"),
    [string]$WrapperScript = (Join-Path $PSScriptRoot "auto-restart.ps1"),
    [string]$LogDir = (Join-Path $PSScriptRoot "logs"),
    [string]$RunAsUser = "$env:USERDOMAIN\$env:USERNAME",
    [securestring]$RunAsPassword,
    [switch]$RemoveScheduledTask
)

$ErrorActionPreference = "Stop"

function Test-NssmAvailable {
    if (-not (Test-Path -LiteralPath $NssmPath)) {
        return $false
    }
    try {
        $null = & $NssmPath version 2>&1
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    }
}

function Install-NssmBinary {
    $binDir = Split-Path -Parent $NssmPath
    if (-not (Test-Path -LiteralPath $binDir)) {
        New-Item -ItemType Directory -Path $binDir -Force | Out-Null
    }
    $tmpZip = Join-Path $env:TEMP "nssm-2.24.zip"
    $tmpDir = Join-Path $env:TEMP "nssm-2.24-extract"
    Write-Host "[install-service] Downloading NSSM 2.24..."
    Invoke-WebRequest -Uri "https://nssm.cc/release/nssm-2.24.zip" -OutFile $tmpZip -UseBasicParsing
    if (Test-Path -LiteralPath $tmpDir) { Remove-Item -LiteralPath $tmpDir -Recurse -Force }
    Expand-Archive -LiteralPath $tmpZip -DestinationPath $tmpDir -Force
    $arch = if ([Environment]::Is64BitOperatingSystem) { "win64" } else { "win32" }
    $src = Get-ChildItem -Path $tmpDir -Recurse -Filter "nssm.exe" |
        Where-Object { $_.FullName -match "\\$arch\\" } |
        Select-Object -First 1
    if (-not $src) {
        throw "Could not locate nssm.exe in extracted archive."
    }
    Copy-Item -LiteralPath $src.FullName -Destination $NssmPath -Force
    Remove-Item -LiteralPath $tmpZip -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $tmpDir -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "[install-service] NSSM installed at $NssmPath"
}

function Stop-AndRemoveScheduledTask {
    param([string]$TaskName = "ZeroHostAgent")
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($null -eq $task) { return }
    Write-Host "[install-service] Stopping existing scheduled task '$TaskName'..."
    try { Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue } catch {}
    Write-Host "[install-service] Unregistering scheduled task '$TaskName'..."
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
}

function Stop-AndRemoveExistingService {
    $svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if ($null -eq $svc) { return }
    Write-Host "[install-service] Existing service '$ServiceName' found; stopping..."
    try { Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue } catch {}
    Start-Sleep -Seconds 2
    & $NssmPath remove $ServiceName confirm 2>&1 | Out-Host
}

function Configure-Service {
    param([System.Management.Automation.PSCredential]$Credential)

    if (-not (Test-Path -LiteralPath $WrapperScript)) {
        throw "Wrapper script not found at $WrapperScript"
    }
    if (-not (Test-Path -LiteralPath $LogDir)) {
        New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
    }

    $psExe = (Get-Command powershell.exe).Source
    $args = "-NoProfile -ExecutionPolicy Bypass -File `"$WrapperScript`""

    Write-Host "[install-service] Installing service '$ServiceName'..."
    & $NssmPath install $ServiceName $psExe $args 2>&1 | Out-Host

    & $NssmPath set $ServiceName AppDirectory $PSScriptRoot
    & $NssmPath set $ServiceName Description "Self-healing supervisor for Zero host_agent (port 18796) and Reachy daemon (port 8000). Replaces the ZeroHostAgent scheduled task."
    & $NssmPath set $ServiceName DisplayName "Zero Host Agent (Reachy supervisor)"
    & $NssmPath set $ServiceName Start SERVICE_DELAYED_AUTO_START

    # Restart-on-exit policy: throttle 5s, retry every 3s, no max attempts.
    & $NssmPath set $ServiceName AppExit Default Restart
    & $NssmPath set $ServiceName AppRestartDelay 3000
    & $NssmPath set $ServiceName AppThrottle 5000

    # Per-day rotated stdout/stderr.
    $stdoutLog = Join-Path $LogDir "service.out.log"
    $stderrLog = Join-Path $LogDir "service.err.log"
    & $NssmPath set $ServiceName AppStdout $stdoutLog
    & $NssmPath set $ServiceName AppStderr $stderrLog
    & $NssmPath set $ServiceName AppRotateFiles 1
    & $NssmPath set $ServiceName AppRotateOnline 1
    # Rotate at 10 MB or once per day (NSSM uses bytes / seconds).
    & $NssmPath set $ServiceName AppRotateBytes 10485760
    & $NssmPath set $ServiceName AppRotateSeconds 86400

    if ($null -ne $Credential) {
        $plain = $Credential.GetNetworkCredential().Password
        Write-Host "[install-service] Configuring user context: $($Credential.UserName)"
        & $NssmPath set $ServiceName ObjectName $Credential.UserName $plain
        $plain = $null
    } else {
        Write-Host "[install-service] No credentials provided; service will run as LocalSystem."
        Write-Warning "[install-service] WASAPI audio (Reachy mic/speaker) requires a per-session user context. Re-run with -RunAsUser and -RunAsPassword to enable audio."
    }
}

function Verify-Service {
    Start-Sleep -Seconds 2
    Write-Host "[install-service] Starting service..."
    Start-Service -Name $ServiceName
    Start-Sleep -Seconds 3
    $svc = Get-Service -Name $ServiceName
    Write-Host "[install-service] Service '$ServiceName' status: $($svc.Status), startType: $($svc.StartType)"
    if ($svc.Status -ne "Running") {
        Write-Warning "[install-service] Service did not reach Running state. Check logs at $LogDir\service.err.log"
    }
}

# ---------------------------------------------------------------------------
# Main flow
# ---------------------------------------------------------------------------

if (-not (Test-NssmAvailable)) {
    Install-NssmBinary
}

if ($RemoveScheduledTask -or (Get-ScheduledTask -TaskName "ZeroHostAgent" -ErrorAction SilentlyContinue)) {
    Stop-AndRemoveScheduledTask -TaskName "ZeroHostAgent"
}

Stop-AndRemoveExistingService

$cred = $null
if ($RunAsUser -and $RunAsUser -ne "\\") {
    if ($null -eq $RunAsPassword) {
        $RunAsPassword = Read-Host -AsSecureString -Prompt "Password for $RunAsUser (required for WASAPI audio context)"
    }
    if ($null -ne $RunAsPassword -and $RunAsPassword.Length -gt 0) {
        $cred = New-Object System.Management.Automation.PSCredential($RunAsUser, $RunAsPassword)
    }
}

Configure-Service -Credential $cred
Verify-Service

Write-Host ""
Write-Host "[install-service] Done. Operate the service with:"
Write-Host "  Get-Service $ServiceName"
Write-Host "  Restart-Service $ServiceName"
Write-Host "  Stop-Service $ServiceName"
Write-Host "  & '$NssmPath' dump $ServiceName"
Write-Host ""
Write-Host "[install-service] To remove and revert to the scheduled task:"
Write-Host "  & '$PSScriptRoot\uninstall-service.ps1'"
