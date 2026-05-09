# Re-prompts for the Windows password and re-applies it to the ZeroHostAgent
# service. Run from an elevated PowerShell:
#   cd C:\code\zero\host_agent
#   .\fix-service-credential.ps1
#
# The previous attempt got "ERROR_LOGON_FAILURE 1326" which means the password
# didn't authenticate. Either a typo or a special character that got mangled
# through the SecureString -> command-line round-trip.

[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$ServiceName = "ZeroHostAgent"
$NssmPath    = "C:\code\zero\host_agent\bin\nssm.exe"
$RunAsUser   = "$env:USERDOMAIN\$env:USERNAME"

if (-not (Test-Path -LiteralPath $NssmPath)) {
    throw "NSSM not found at $NssmPath"
}

$svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if (-not $svc) {
    throw "Service '$ServiceName' is not installed. Run migrate-to-nssm.ps1 first."
}

Write-Host "[fix] Service exists. Stopping if running..."
try { Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue } catch {}
Start-Sleep -Seconds 2

# --- Step 1: validate the password BEFORE handing it to NSSM ---
# We do this by attempting an in-process LogonUser call. If the password is
# wrong we get a clear failure here instead of a cryptic SCM 1326 later.
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class _Logon {
    [DllImport("advapi32.dll", SetLastError=true, CharSet=CharSet.Unicode)]
    public static extern bool LogonUser(
        string lpszUsername,
        string lpszDomain,
        string lpszPassword,
        int dwLogonType,
        int dwLogonProvider,
        out IntPtr phToken);
    [DllImport("kernel32.dll")]
    public static extern bool CloseHandle(IntPtr handle);
}
"@ -ErrorAction SilentlyContinue

function Test-Password {
    param([string]$User, [securestring]$SecurePassword)
    $domain = "."
    $name = $User
    if ($User -match "\\") {
        $parts = $User -split "\\", 2
        $domain = $parts[0]
        $name = $parts[1]
    }
    $bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecurePassword)
    try {
        $plain = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
        $token = [IntPtr]::Zero
        # LOGON32_LOGON_NETWORK = 3 (fastest, doesn't need full interactive logon)
        $ok = [_Logon]::LogonUser($name, $domain, $plain, 3, 0, [ref]$token)
        if ($ok) {
            [_Logon]::CloseHandle($token) | Out-Null
            return @{ ok = $true; error = $null }
        }
        $errCode = [System.Runtime.InteropServices.Marshal]::GetLastWin32Error()
        return @{ ok = $false; error = "Win32 error $errCode" }
    } finally {
        [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
}

$attempts = 0
$validatedPw = $null
while ($attempts -lt 3 -and $null -eq $validatedPw) {
    $attempts++
    $pw = Read-Host -AsSecureString -Prompt "Windows password for $RunAsUser (attempt $attempts/3)"
    if ($pw.Length -eq 0) {
        Write-Warning "[fix] Empty password; aborting."
        return
    }
    Write-Host "[fix] Validating password against $RunAsUser..."
    $check = Test-Password -User $RunAsUser -SecurePassword $pw
    if ($check.ok) {
        Write-Host "[fix] Password validates."
        $validatedPw = $pw
    } else {
        Write-Warning "[fix] Password did NOT validate ($($check.error)). Try again."
    }
}

if ($null -eq $validatedPw) {
    throw "Password did not validate after 3 attempts. Aborting."
}

# --- Step 2: re-apply to the service via NSSM ---
$bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($validatedPw)
try {
    $plain = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
    Write-Host "[fix] Setting ObjectName via NSSM..."
    & $NssmPath set $ServiceName ObjectName $RunAsUser $plain 2>&1 | Out-Host
} finally {
    [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    $plain = $null
}

# --- Step 3: start and verify ---
Write-Host "[fix] Starting service..."
try {
    Start-Service -Name $ServiceName -ErrorAction Stop
} catch {
    Write-Warning "[fix] Start-Service failed: $($_.Exception.Message)"
    Write-Host "[fix] Recent SCM eventlog for ZeroHostAgent:"
    Get-EventLog -LogName System -Source "Service Control Manager" -Newest 10 -ErrorAction SilentlyContinue |
        Where-Object { $_.Message -match "ZeroHostAgent" } |
        Select-Object -First 3 |
        ForEach-Object {
            "[$($_.TimeGenerated)] $($_.EntryType): $($_.Message.Substring(0, [math]::Min(280, $_.Message.Length)))"
        }
    throw
}

Start-Sleep -Seconds 4
$svc = Get-Service -Name $ServiceName
$wmi = Get-CimInstance Win32_Service -Filter "Name='$ServiceName'"
Write-Host ""
Write-Host "[fix] === RESULT ==="
Write-Host "Status:    $($svc.Status)"
Write-Host "StartType: $($svc.StartType)"
Write-Host "RunsAs:    $($wmi.StartName)"

# --- Step 4: wait for /health on :18796 ---
Write-Host ""
Write-Host "[fix] Waiting for host_agent /health on :18796..."
$attempts = 0
while ($attempts -lt 60) {
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:18796/health" -UseBasicParsing -TimeoutSec 2
        Write-Host "[fix] host_agent up after $attempts seconds (status=$($r.StatusCode))"
        break
    } catch {
        Start-Sleep -Seconds 1
        $attempts++
    }
}
if ($attempts -ge 60) {
    Write-Warning "[fix] host_agent did not respond within 60s."
    Write-Host "Tail of service.err.log:"
    Get-Content "C:\code\zero\host_agent\logs\service.err.log" -Tail 30 -ErrorAction SilentlyContinue
}

Write-Host ""
Write-Host "[fix] DONE."
