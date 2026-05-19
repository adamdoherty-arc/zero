# install-shortcut.ps1 - drop "Start Zero" shortcuts on Desktop and Start Menu.
#
# The shortcut launches the personal-assistant bootstrap (Docker stack +
# host_agent). The robot (Reachy daemon) stays OFF until the user toggles it
# from the UI's DaemonPanel.
#
# Replaces the old register-autostart.ps1 / register-healthcheck.ps1 scheduled
# tasks. No elevation required: writes only to the current user's profile.
#
# Run from anywhere:
#   powershell -ExecutionPolicy Bypass -File host_agent\install-shortcut.ps1

[CmdletBinding()]
param(
    [switch]$NoDesktop,
    [switch]$NoStartMenu,
    [switch]$KeepLegacy
)

$ErrorActionPreference = 'Stop'

$hostAgentDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$repoRoot     = Split-Path -Parent $hostAgentDir
$target       = Join-Path $repoRoot 'start-zero.bat'

if (-not (Test-Path $target)) {
    Write-Error "start-zero.bat not found at $target."
    exit 1
}

$iconCandidates = @(
    (Join-Path $hostAgentDir 'assets\reachy.ico'),
    (Join-Path $hostAgentDir 'reachy.ico')
)
$icon = $iconCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1

$shell = New-Object -ComObject WScript.Shell

function New-ZeroShortcut {
    param([string]$Path)

    $dir = Split-Path -Parent $Path
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }

    $sc = $shell.CreateShortcut($Path)
    $sc.TargetPath       = $target
    $sc.WorkingDirectory = $repoRoot
    $sc.WindowStyle      = 1
    $sc.Description      = 'Start the Zero personal assistant (Docker stack + host_agent). Robot stays off until you start it from the UI.'
    if ($icon) {
        $sc.IconLocation = "$icon,0"
    }
    $sc.Save()

    Write-Host "[install-shortcut] Wrote $Path"
}

function Remove-LegacyShortcut {
    param([string]$Path)
    if (Test-Path $Path) {
        Remove-Item -Path $Path -Force -ErrorAction SilentlyContinue
        Write-Host "[install-shortcut] Removed legacy shortcut $Path"
    }
}

$desktop   = [Environment]::GetFolderPath('Desktop')
$startMenu = Join-Path ([Environment]::GetFolderPath('Programs')) 'Zero'

# Replace the legacy "Start Zero Robot" shortcuts with the new "Start Zero"
# bootstrap unless -KeepLegacy is passed.
if (-not $KeepLegacy) {
    Remove-LegacyShortcut (Join-Path $desktop   'Start Zero Robot.lnk')
    Remove-LegacyShortcut (Join-Path $startMenu 'Start Zero Robot.lnk')
}

if (-not $NoDesktop) {
    New-ZeroShortcut -Path (Join-Path $desktop 'Start Zero.lnk')
}

if (-not $NoStartMenu) {
    New-ZeroShortcut -Path (Join-Path $startMenu 'Start Zero.lnk')
}

Write-Host ''
Write-Host '[install-shortcut] Done. Double-click "Start Zero" to launch the personal assistant.'
Write-Host '  - Docker stack comes up and serves the UI on http://localhost:5173/'
Write-Host '  - host_agent comes up in its own console window'
Write-Host '  - Reachy daemon stays OFF; toggle from the UI''s DaemonPanel'
