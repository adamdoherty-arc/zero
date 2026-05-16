# install-shortcut.ps1 — drop "Start Zero Robot" shortcuts on Desktop and Start Menu.
#
# Replaces the old register-autostart.ps1 / register-healthcheck.ps1 scheduled
# tasks. No elevation required: writes only to the current user's profile.

[CmdletBinding()]
param(
    [switch]$NoDesktop,
    [switch]$NoStartMenu
)

$ErrorActionPreference = 'Stop'

$here = Split-Path -Parent $MyInvocation.MyCommand.Definition
$target = Join-Path $here 'start-zero.bat'

if (-not (Test-Path $target)) {
    Write-Error "start-zero.bat not found at $target. Make sure you ran this from host_agent/."
    exit 1
}

$iconCandidates = @(
    (Join-Path $here 'assets\reachy.ico'),
    (Join-Path $here 'reachy.ico')
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
    $sc.TargetPath = $target
    $sc.WorkingDirectory = $here
    $sc.WindowStyle = 1   # normal window — keeps the console visible
    $sc.Description = 'Start the Zero Robot host_agent (Reachy stack).'
    if ($icon) {
        $sc.IconLocation = "$icon,0"
    }
    $sc.Save()

    Write-Host "[install-shortcut] Wrote $Path"
}

if (-not $NoDesktop) {
    $desktop = [Environment]::GetFolderPath('Desktop')
    New-ZeroShortcut -Path (Join-Path $desktop 'Start Zero Robot.lnk')
}

if (-not $NoStartMenu) {
    $startMenu = Join-Path ([Environment]::GetFolderPath('Programs')) 'Zero'
    New-ZeroShortcut -Path (Join-Path $startMenu 'Start Zero Robot.lnk')
}

Write-Host ''
Write-Host '[install-shortcut] Done. Double-click "Start Zero Robot" to launch the Reachy stack.'
