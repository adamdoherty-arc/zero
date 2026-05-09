# Diagnose what kind of Windows account you have so we can pick the right
# path forward for the ZeroHostAgent service. Run from any PowerShell (no
# elevation needed).

$user = "$env:USERDOMAIN\$env:USERNAME"
Write-Host "=== whoami ==="
"User: $user"
$sid = (whoami /user /fo csv | ConvertFrom-Csv | Select-Object -First 1).SID
"SID:  $sid"

Write-Host ""
Write-Host "=== Account type ==="
# Microsoft Account (MSA) SIDs start with S-1-12-1-...
# Local accounts start with S-1-5-21-...
if ($sid -like "S-1-12-1-*") {
    "TYPE: Microsoft Account (cloud-linked)"
    "  -> Your sign-in password is your Microsoft Account password (the one"
    "     you'd use at https://account.microsoft.com)."
    "  -> Windows Hello PIN is a SEPARATE local credential and will NOT"
    "     authenticate via LogonUser the way a real password does."
} elseif ($sid -like "S-1-5-21-*") {
    "TYPE: Local account"
    "  -> Your sign-in password is the local Windows password for $user."
} else {
    "TYPE: Other (SID prefix unrecognized: $sid)"
}

Write-Host ""
Write-Host "=== Local user record (if any) ==="
try {
    $lu = Get-LocalUser -Name $env:USERNAME -ErrorAction Stop
    "Name:               $($lu.Name)"
    "Enabled:            $($lu.Enabled)"
    "PasswordLastSet:    $($lu.PasswordLastSet)"
    "PasswordRequired:   $($lu.PasswordRequired)"
    "LastLogon:          $($lu.LastLogon)"
} catch {
    "No local user record found for '$env:USERNAME' (consistent with MSA-only login)."
}

Write-Host ""
Write-Host "=== Windows Hello / PIN check ==="
$ngc = "$env:LOCALAPPDATA\Microsoft\Ngc"
if (Test-Path $ngc) {
    "Windows Hello/PIN appears configured (found $ngc)."
    "If you sign in with PIN, your underlying password is something else."
} else {
    "No Windows Hello config detected."
}

Write-Host ""
Write-Host "=== net user details ==="
$null = (net user $env:USERNAME 2>&1) | ForEach-Object { $_ }

Write-Host ""
Write-Host "=== Recommendation based on findings ==="
if ($sid -like "S-1-12-1-*") {
    "You have a Microsoft Account. NSSM cannot reliably store an MSA password"
    "for service authentication (MSA goes through a different auth flow)."
    ""
    "RECOMMENDED PATH: revert to the scheduled task with a logon delay."
    "  - No password storage needed (uses your existing logon session)."
    "  - WASAPI audio still works (Interactive logon = your session)."
    "  - 90s delay covers the Docker boot race."
    "  - Layers 1-6 of the application-layer fix already handle Docker"
    "    readiness inside host_agent, so this is purely defense-in-depth."
} else {
    "You have a local account. The password should work — but it didn't."
    "Most likely cause: special characters in your password (especially &"
    "double-quotes, ampersands, or non-ASCII characters) get mangled when"
    "routed through Read-Host -> BSTR -> nssm.exe argv."
    ""
    "OPTIONS:"
    "  A. Change your Windows password to one with only A-Z, a-z, 0-9, and"
    "     simple punctuation (-, _, .). Then re-run fix-service-credential.ps1."
    "  B. Revert to the scheduled task with a logon delay (no password needed)."
}
