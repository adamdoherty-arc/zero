# Installs GStreamer 1.26.x runtime by downloading the official MSI from
# gstreamer.freedesktop.org and running msiexec. Uses curl.exe (bundled
# with Windows 10/11) for download because gstreamer.freedesktop.org
# blocks PowerShell's default User-Agent with HTTP 418/403. Bypasses
# Chocolatey entirely. Idempotent.
#
# Run from an elevated PowerShell:
#   cd C:\code\zero\host_agent
#   .\install-gstreamer.ps1

[CmdletBinding()]
param(
    [string]$Version = "1.26.9",
    [string]$Arch = "x86_64",
    [string]$Toolchain = "msvc"
)

$ErrorActionPreference = "Stop"

# Self-elevate: if not admin, relaunch this script as admin via UAC.
$wp = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $wp.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "Not elevated. Relaunching with UAC prompt..."
    $arg = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    Start-Process powershell.exe -Verb RunAs -ArgumentList $arg -Wait
    Write-Host "Elevated process finished. (Output is in the elevated window.)"
    exit
}

# Clean up any stale GStreamer install records so msiexec doesn't refuse
# to "downgrade" over a registry entry whose files are gone (this is the
# classic 1603 cause).
Write-Host "Checking for stale GStreamer registry entries..."
$staleProducts = Get-Package -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -match "GStreamer 1.0" }
foreach ($p in $staleProducts) {
    $productCode = $p.TagId
    if (-not $productCode) {
        # Find ProductCode from the registry uninstall string
        $entries = Get-ItemProperty -Path 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*' -ErrorAction SilentlyContinue
        $entries += Get-ItemProperty -Path 'HKLM:\Software\Wow6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*' -ErrorAction SilentlyContinue
        foreach ($e in $entries) {
            if ($e.DisplayName -eq $p.Name -and $e.DisplayVersion -eq $p.Version) {
                if ($e.UninstallString -match '\{[A-F0-9-]+\}') {
                    $productCode = $matches[0]
                }
                break
            }
        }
    }
    if ($productCode) {
        Write-Host ("  Removing stale " + $p.Name + " " + $p.Version + " (" + $productCode + ")")
        $uninstallArgs = @('/x', $productCode, '/qn', '/norestart')
        $rm = Start-Process -FilePath 'msiexec.exe' -ArgumentList $uninstallArgs -Wait -PassThru -NoNewWindow
        Write-Host ("  uninstall exit: " + $rm.ExitCode)
    }
}

$curl = (Get-Command curl.exe -ErrorAction SilentlyContinue).Source
if (-not $curl) {
    throw 'curl.exe not found on PATH. Windows 10/11 ships it at C:\Windows\System32\curl.exe; check your install.'
}
Write-Host ("Using curl at " + $curl)

function Test-MsiUrlCurl {
    param([string]$Url)
    # -s silent, -L follow redirects, -I HEAD, -o NUL discard body, -w status
    $code = & $curl -s -L -I -o NUL -w "%{http_code}" $Url 2>$null
    if ($null -eq $code) { return $false }
    return ($code -eq "200")
}

function Build-MsiUrl {
    param([string]$Ver, [string]$Tc, [string]$Ar)
    $name = "gstreamer-1.0-$Tc-$Ar-$Ver.msi"
    return @{
        Name = $name
        Url  = "https://gstreamer.freedesktop.org/data/pkg/windows/$Ver/$Tc/$name"
    }
}

# 1.24.x is no longer hosted; only 1.26.x is live. Probe newest first.
$candidates = @($Version, "1.26.6", "1.26.5", "1.26.4", "1.26.3", "1.26.2", "1.26.1", "1.26.0") |
              Select-Object -Unique

$selected = $null
foreach ($v in $candidates) {
    $info = Build-MsiUrl -Ver $v -Tc $Toolchain -Ar $Arch
    Write-Host ("Probing " + $info.Url)
    if (Test-MsiUrlCurl -Url $info.Url) {
        Write-Host "  -> 200 OK"
        $selected = @{ Version = $v; Url = $info.Url; Name = $info.Name }
        break
    } else {
        Write-Host "  -> not available, trying next" -ForegroundColor Yellow
    }
}

if ($null -eq $selected) {
    throw 'No working GStreamer MSI URL found. Visit https://gstreamer.freedesktop.org/download/ manually.'
}

Write-Host ("Selected GStreamer " + $selected.Version)
$msiPath = Join-Path $env:TEMP $selected.Name

if (Test-Path $msiPath) {
    $existingSize = (Get-Item $msiPath).Length
    if ($existingSize -gt 100MB) {
        Write-Host ("MSI already cached at " + $msiPath + " (" + [math]::Round($existingSize/1MB, 1) + " MB), skipping download.")
    } else {
        Write-Host ("Cached MSI looks truncated ($existingSize bytes), redownloading.")
        Remove-Item $msiPath -Force
    }
}

if (-not (Test-Path $msiPath)) {
    Write-Host ("Downloading " + $selected.Name + " via curl.exe ...")
    & $curl -L --fail --progress-bar -o $msiPath $selected.Url
    if ($LASTEXITCODE -ne 0) {
        throw ("curl download failed with exit " + $LASTEXITCODE)
    }
    $sz = (Get-Item $msiPath).Length
    Write-Host ("Downloaded " + [math]::Round($sz/1MB, 1) + " MB")
}

Write-Host 'Running msiexec (silent, complete feature set, verbose log)...'
$msiLog = Join-Path $env:TEMP 'gstreamer-install.log'
$msiArgs = @('/i', "`"$msiPath`"", '/qn', '/norestart', 'ADDLOCAL=ALL', '/L*v', "`"$msiLog`"")
$proc = Start-Process -FilePath 'msiexec.exe' -ArgumentList $msiArgs -Wait -PassThru -NoNewWindow
$ec = $proc.ExitCode
Write-Host ("msiexec exit code: " + $ec + "  log: " + $msiLog)
if ($ec -ne 0 -and $ec -ne 3010) {
    Write-Host ""
    Write-Host "Last 30 lines of MSI log around 'Return value 3' (the actual failure):"
    if (Test-Path $msiLog) {
        $lines = Get-Content $msiLog
        $idx = ($lines | Select-String -Pattern 'Return value 3').LineNumber | Select-Object -First 1
        if ($idx) {
            $start = [math]::Max(0, $idx - 25)
            $lines[$start..($idx - 1)] | ForEach-Object { Write-Host ("  " + $_) }
        } else {
            $lines | Select-Object -Last 30 | ForEach-Object { Write-Host ("  " + $_) }
        }
    }
    throw "msiexec failed with exit $ec (0 success, 3010 success-needs-reboot)."
}

# Find the install dir
$gstRoot = "C:\gstreamer\1.0\${Toolchain}_${Arch}"
if (-not (Test-Path "$gstRoot\bin\gst-launch-1.0.exe")) {
    $alt = Get-ChildItem 'C:\gstreamer\1.0\' -Directory -ErrorAction SilentlyContinue |
           Where-Object { Test-Path (Join-Path $_.FullName 'bin\gst-launch-1.0.exe') } |
           Select-Object -First 1
    if ($alt) { $gstRoot = $alt.FullName }
    else { throw "GStreamer install not found at C:\gstreamer\1.0\* after msiexec." }
}
Write-Host ("GStreamer detected at " + $gstRoot)

$gstBin = Join-Path $gstRoot 'bin'
$gstPlugins = Join-Path $gstRoot 'lib\gstreamer-1.0'

# Promote to user-level env vars so the scheduled task / NSSM service
# pick them up next launch.
$existing = [Environment]::GetEnvironmentVariable('Path', 'User')
$pathParts = @()
if ($existing) {
    $pathParts = $existing -split ';' | Where-Object { $_ -and ($_ -notlike '*gstreamer*') }
}
$pathParts = @($gstBin) + @($pathParts)
$newPath = ($pathParts -join ';')
[Environment]::SetEnvironmentVariable('Path', $newPath, 'User')
[Environment]::SetEnvironmentVariable('GST_PLUGIN_PATH', $gstPlugins, 'User')
[Environment]::SetEnvironmentVariable('GSTREAMER_1_0_ROOT_MSVC_X86_64', $gstRoot, 'User')

# Make the env visible in this process too
$env:Path = "$gstBin;" + $env:Path
$env:GST_PLUGIN_PATH = $gstPlugins
$env:GSTREAMER_1_0_ROOT_MSVC_X86_64 = $gstRoot

Write-Host ''
Write-Host 'User env vars set:'
Write-Host ("  Path += " + $gstBin)
Write-Host ("  GST_PLUGIN_PATH = " + $gstPlugins)
Write-Host ("  GSTREAMER_1_0_ROOT_MSVC_X86_64 = " + $gstRoot)

Write-Host ''
Write-Host 'gst-launch-1.0 --version:'
& (Join-Path $gstBin 'gst-launch-1.0.exe') --version

Write-Host ''
Write-Host 'wasapi2src element check:'
$inspectOut = & (Join-Path $gstBin 'gst-inspect-1.0.exe') wasapi2src 2>&1
$inspectOut | Select-String -Pattern 'Factory Details|Long-name|Klass|Description' -SimpleMatch |
    Select-Object -First 4 |
    ForEach-Object { Write-Host ("  " + $_.Line) }

Write-Host ''
Write-Host 'Audio sources visible to GStreamer (looking for Reachy):'
$devOut = & (Join-Path $gstBin 'gst-device-monitor-1.0.exe') 'Audio/Source' 2>&1
$devOut | Select-String -Pattern '(?i)reachy|node\.name|device\.api|name ' |
    Select-Object -First 30 |
    ForEach-Object { Write-Host ("  " + $_.Line) }

Write-Host ''
Write-Host 'Done.'
Write-Host ''
Write-Host 'Next: in a new (non-admin) PowerShell, restart host_agent so it picks up the new PATH:'
Write-Host '  $owners = @(Get-NetTCPConnection -LocalPort 18796 -State Listen | Select-Object -ExpandProperty OwningProcess -Unique)'
Write-Host '  $owners | ForEach-Object { Stop-Process -Id $_ -Force }'
Write-Host '  Start-ScheduledTask -TaskName ZeroHostAgent'
