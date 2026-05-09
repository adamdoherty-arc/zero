# Standalone NSSM migration. Run from an elevated PowerShell:
#   cd C:\code\zero\host_agent
#   .\migrate-to-nssm.ps1
#
# The only interactive prompt is the Windows password (needed because WASAPI
# audio is per-session — the service must run as the logged-in user). If you
# want to avoid the prompt, pass -RunAsPassword (ConvertTo-SecureString -AsPlainText -Force "yourpw").

[CmdletBinding()]
param(
    [securestring]$RunAsPassword
)

$ErrorActionPreference = "Stop"

# --- Hardcoded paths (no $PSScriptRoot dependency) ---
$HostAgentDir = "C:\code\zero\host_agent"
$BinDir       = Join-Path $HostAgentDir "bin"
$LogDir       = Join-Path $HostAgentDir "logs"
$NssmPath     = Join-Path $BinDir "nssm.exe"
$Wrapper      = Join-Path $HostAgentDir "auto-restart.ps1"
$ServiceName  = "ZeroHostAgent"
$RunAsUser    = "$env:USERDOMAIN\$env:USERNAME"

# --- Sanity ---
if (-not (Test-Path -LiteralPath $Wrapper)) {
    throw "Wrapper script not found at $Wrapper"
}
foreach ($d in @($BinDir, $LogDir)) {
    if (-not (Test-Path -LiteralPath $d)) { New-Item -ItemType Directory -Path $d -Force | Out-Null }
}

# --- 1. Ensure NSSM binary is present ---
if (-not (Test-Path -LiteralPath $NssmPath)) {
    Write-Host "[migrate] Downloading NSSM 2.24..."
    $tmpZip = Join-Path $env:TEMP "nssm-2.24.zip"
    $tmpDir = Join-Path $env:TEMP "nssm-2.24-extract"
    Invoke-WebRequest -Uri "https://nssm.cc/release/nssm-2.24.zip" -OutFile $tmpZip -UseBasicParsing
    if (Test-Path -LiteralPath $tmpDir) { Remove-Item -LiteralPath $tmpDir -Recurse -Force }
    Expand-Archive -LiteralPath $tmpZip -DestinationPath $tmpDir -Force
    $arch = if ([Environment]::Is64BitOperatingSystem) { "win64" } else { "win32" }
    $src = Get-ChildItem -Path $tmpDir -Recurse -Filter "nssm.exe" | Where-Object { $_.FullName -match "\\$arch\\" } | Select-Object -First 1
    if (-not $src) { throw "Could not locate nssm.exe in extracted archive." }
    Copy-Item -LiteralPath $src.FullName -Destination $NssmPath -Force
    Remove-Item -LiteralPath $tmpZip -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $tmpDir -Recurse -Force -ErrorAction SilentlyContinue
}
Write-Host "[migrate] NSSM at $NssmPath"

# --- 2. Stop and remove the existing scheduled task ---
$task = Get-ScheduledTask -TaskName $ServiceName -ErrorAction SilentlyContinue
if ($task) {
    Write-Host "[migrate] Stopping scheduled task '$ServiceName'..."
    try { Stop-ScheduledTask -TaskName $ServiceName -ErrorAction SilentlyContinue } catch {}
    Write-Host "[migrate] Unregistering scheduled task '$ServiceName'..."
    Unregister-ScheduledTask -TaskName $ServiceName -Confirm:$false -ErrorAction SilentlyContinue
}

# --- 3. Stop the bare host_agent processes that the task left behind ---
Write-Host "[migrate] Stopping any host_agent processes still bound to :18796..."
$portOwners = (Get-NetTCPConnection -LocalPort 18796 -State Listen -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique) | Where-Object { $_ -gt 0 }
foreach ($pidValue in $portOwners) {
    try {
        Write-Host "[migrate]  - killing pid $pidValue"
        Stop-Process -Id $pidValue -Force -ErrorAction SilentlyContinue
    } catch {}
}

# --- 4. Remove any half-installed service from a previous attempt ---
$existing = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "[migrate] Existing service found; stopping and removing..."
    try { Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue } catch {}
    Start-Sleep -Seconds 2
    & $NssmPath remove $ServiceName confirm 2>&1 | Out-Host
}

# --- 5. Install the new service ---
Write-Host "[migrate] Installing service '$ServiceName' via NSSM..."
$psExe = (Get-Command powershell.exe).Source
$wrapperArgs = "-NoProfile -ExecutionPolicy Bypass -File `"$Wrapper`""
& $NssmPath install $ServiceName $psExe $wrapperArgs 2>&1 | Out-Host

& $NssmPath set $ServiceName AppDirectory $HostAgentDir 2>&1 | Out-Host
& $NssmPath set $ServiceName Description "Self-healing supervisor for Zero host_agent (port 18796) and Reachy daemon (port 8000). Replaces the ZeroHostAgent scheduled task." 2>&1 | Out-Host
& $NssmPath set $ServiceName DisplayName "Zero Host Agent (Reachy supervisor)" 2>&1 | Out-Host
& $NssmPath set $ServiceName Start SERVICE_DELAYED_AUTO_START 2>&1 | Out-Host

& $NssmPath set $ServiceName AppExit Default Restart 2>&1 | Out-Host
& $NssmPath set $ServiceName AppRestartDelay 3000 2>&1 | Out-Host
& $NssmPath set $ServiceName AppThrottle 5000 2>&1 | Out-Host

$stdoutLog = Join-Path $LogDir "service.out.log"
$stderrLog = Join-Path $LogDir "service.err.log"
& $NssmPath set $ServiceName AppStdout $stdoutLog 2>&1 | Out-Host
& $NssmPath set $ServiceName AppStderr $stderrLog 2>&1 | Out-Host
& $NssmPath set $ServiceName AppRotateFiles 1 2>&1 | Out-Host
& $NssmPath set $ServiceName AppRotateOnline 1 2>&1 | Out-Host
& $NssmPath set $ServiceName AppRotateBytes 10485760 2>&1 | Out-Host
& $NssmPath set $ServiceName AppRotateSeconds 86400 2>&1 | Out-Host

# --- 6. Configure user context (WASAPI requires it) ---
if ($null -eq $RunAsPassword) {
    Write-Host "[migrate] Need your Windows password so the service can run as $RunAsUser (WASAPI audio is per-session)."
    $RunAsPassword = Read-Host -AsSecureString -Prompt "Windows password for $RunAsUser"
}

if ($null -eq $RunAsPassword -or $RunAsPassword.Length -eq 0) {
    Write-Warning "[migrate] No password provided; service will run as LocalSystem (Reachy mic/speaker will NOT work). Re-run with -RunAsPassword to fix."
} else {
    $bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($RunAsPassword)
    try {
        $plain = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
        Write-Host "[migrate] Setting service ObjectName to $RunAsUser..."
        & $NssmPath set $ServiceName ObjectName $RunAsUser $plain 2>&1 | Out-Host
    } finally {
        [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
        $plain = $null
    }
}

# --- 7. Start and verify ---
Write-Host "[migrate] Starting service..."
Start-Service -Name $ServiceName
Start-Sleep -Seconds 4
$svc = Get-Service -Name $ServiceName
Write-Host ""
Write-Host "[migrate] === RESULT ==="
Write-Host "Service:    $($svc.Name)"
Write-Host "Status:     $($svc.Status)"
Write-Host "StartType:  $($svc.StartType)"
$wmi = Get-CimInstance Win32_Service -Filter "Name='$ServiceName'"
Write-Host "RunsAs:     $($wmi.StartName)"
$delayed = (Get-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Services\$ServiceName" -Name DelayedAutoStart -ErrorAction SilentlyContinue).DelayedAutoStart
Write-Host "DelayedAutoStart: $delayed"

# --- 8. Wait for host_agent /health to come up ---
Write-Host ""
Write-Host "[migrate] Waiting for host_agent /health on :18796..."
$attempts = 0
while ($attempts -lt 60) {
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:18796/health" -UseBasicParsing -TimeoutSec 2
        Write-Host "[migrate] host_agent up after $attempts seconds (status=$($r.StatusCode))"
        break
    } catch {
        Start-Sleep -Seconds 1
        $attempts++
    }
}
if ($attempts -ge 60) {
    Write-Warning "[migrate] host_agent did not respond within 60s. Check $LogDir\service.err.log"
}

Write-Host ""
Write-Host "[migrate] DONE. Operate the service with:"
Write-Host "  Get-Service $ServiceName"
Write-Host "  Restart-Service $ServiceName"
Write-Host "  Stop-Service $ServiceName"
Write-Host "  & '$NssmPath' dump $ServiceName"
Write-Host ""
Write-Host "[migrate] To revert (restore the scheduled task):"
Write-Host "  Stop-Service $ServiceName"
Write-Host "  & '$NssmPath' remove $ServiceName confirm"
Write-Host "  powershell.exe -ExecutionPolicy Bypass -File C:\code\zero\host_agent\register-autostart.ps1"
