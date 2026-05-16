# unblock-hyperv-firewall.ps1
#
# Open Windows' Hyper-V Firewall so the Docker container (zero-api) can
# reach host_agent on port 18796 (and the Reachy daemon on :8000).
#
# Run from an ELEVATED PowerShell:
#   powershell -ExecutionPolicy Bypass -File C:\code\zero\host_agent\unblock-hyperv-firewall.ps1
#
# This is required once. Symptoms it fixes:
#   * "Reachy stack is not running" banner in the UI even though
#     host_agent is up locally.
#   * curl http://localhost:18796/health works on the host but
#     ReadTimeout from inside the zero-api container.

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

# --- Require admin ---------------------------------------------------------
$principal = New-Object System.Security.Principal.WindowsPrincipal(
    [System.Security.Principal.WindowsIdentity]::GetCurrent()
)
if (-not $principal.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "[unblock] This script needs an elevated PowerShell." -ForegroundColor Red
    Write-Host "          Right-click PowerShell -> 'Run as administrator', then re-run:"
    Write-Host "          powershell -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    exit 1
}

# The WSL Hyper-V VM creator GUID is fixed by Microsoft.
$WslVmCreatorId = '{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}'

# --- Helper: add or update a Hyper-V firewall rule -------------------------
function Set-ZeroHyperVRule {
    param(
        [Parameter(Mandatory = $true)] [string]$DisplayName,
        [Parameter(Mandatory = $true)] [int]$Port
    )

    $existing = Get-NetFirewallHyperVRule -ErrorAction SilentlyContinue |
        Where-Object { $_.DisplayName -eq $DisplayName }

    if ($existing) {
        Write-Host "[unblock] Rule '$DisplayName' already exists. Refreshing." -ForegroundColor Yellow
        Remove-NetFirewallHyperVRule -DisplayName $DisplayName -ErrorAction SilentlyContinue
    }

    New-NetFirewallHyperVRule `
        -DisplayName $DisplayName `
        -VMCreatorId $WslVmCreatorId `
        -Direction Inbound `
        -LocalPorts $Port `
        -Protocol TCP `
        -Action Allow | Out-Null

    Write-Host "[unblock] Allowed inbound TCP $Port to WSL ($DisplayName)" -ForegroundColor Green
}

# --- Add rules for host_agent (18796), Reachy daemon (8000), and the
#     shared LLM infra (Bifrost 4445, shared-litellm 4444, llama-cpp 18800) -
#     so zero-api can reach the providers via host.docker.internal. -----------
try {
    Set-ZeroHyperVRule -DisplayName 'Zero host_agent 18796' -Port 18796
    Set-ZeroHyperVRule -DisplayName 'Zero Reachy daemon 8000' -Port 8000
    Set-ZeroHyperVRule -DisplayName 'Zero shared-bifrost 4445' -Port 4445
    Set-ZeroHyperVRule -DisplayName 'Zero shared-litellm 4444' -Port 4444
    Set-ZeroHyperVRule -DisplayName 'Zero llama-cpp-chat 18800' -Port 18800
    Set-ZeroHyperVRule -DisplayName 'Zero vllm-embed 8001' -Port 8001
}
catch {
    Write-Host "[unblock] Adding Hyper-V rules failed: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "[unblock] Falling back to disabling the WSL Hyper-V firewall entirely."
    Write-Host "          (You can re-enable it with: Set-NetFirewallHyperVVMSetting -Name '$WslVmCreatorId' -Enabled True)"
    try {
        Set-NetFirewallHyperVVMSetting -Name $WslVmCreatorId -Enabled False
        Write-Host "[unblock] WSL Hyper-V firewall disabled." -ForegroundColor Green
    }
    catch {
        Write-Host "[unblock] Fallback also failed: $($_.Exception.Message)" -ForegroundColor Red
        exit 1
    }
}

# --- Verify from inside the zero-api container -----------------------------
Write-Host ''
Write-Host '[unblock] Verifying paths from zero-api -> host services...' -ForegroundColor Cyan

$probes = @(
    @{ Name = 'host_agent';      Url = 'http://host.docker.internal:18796/health' },
    @{ Name = 'shared-bifrost';  Url = 'http://host.docker.internal:4445/v1/models' },
    @{ Name = 'llama-cpp-chat';  Url = 'http://host.docker.internal:18800/v1/models' }
)

$allOk = $true
foreach ($p in $probes) {
    try {
        $code = docker exec zero-api curl -s -o /dev/null -w '%{http_code}' -m 5 $p.Url 2>$null
        if ($code -match '^(2|4)\d\d$') {
            Write-Host ("[unblock] OK    {0} -> HTTP {1}" -f $p.Name, $code) -ForegroundColor Green
        } else {
            Write-Host ("[unblock] FAIL  {0} -> HTTP {1}" -f $p.Name, ($code -or 'no-response')) -ForegroundColor Red
            $allOk = $false
        }
    }
    catch {
        Write-Host ("[unblock] ERROR {0} -> {1}" -f $p.Name, $_.Exception.Message) -ForegroundColor Yellow
        $allOk = $false
    }
}

if (-not $allOk) {
    Write-Host ''
    Write-Host '[unblock] One or more probes failed. Possible causes:' -ForegroundColor Yellow
    Write-Host '  * The target service is not actually running (check: docker ps)'
    Write-Host '  * Windows Defender Firewall (per-app) blocking the listener; check wf.msc'
    Write-Host '  * Docker Desktop port proxy is stale: wsl --shutdown; then docker compose restart'
}

Write-Host ''
Write-Host '[unblock] Done. Reload the Zero UI at http://localhost:5173/zero — the amber'
Write-Host '          "Reachy stack is not running" banner should clear within a few seconds.'
