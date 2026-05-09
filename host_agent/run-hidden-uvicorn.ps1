param(
    [string]$PythonPath = (Join-Path $PSScriptRoot ".venv\Scripts\python.exe"),
    [string]$LogFile = (Join-Path $PSScriptRoot "logs\auto-restart.log"),
    [string]$HostAgentHost = $env:HOST_AGENT_HOST,
    [string]$HostAgentPort = $env:HOST_AGENT_PORT,
    [int]$StartupAttempts = 45,
    [int]$FailureThreshold = 3
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$logDir = Split-Path -Parent $LogFile
if (-not (Test-Path -LiteralPath $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}

function Write-HostAgentLog {
    param([string]$Message)
    $line = $Message + [Environment]::NewLine
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($line)
    for ($attempt = 0; $attempt -lt 10; $attempt++) {
        try {
            $stream = [System.IO.File]::Open(
                $LogFile,
                [System.IO.FileMode]::Append,
                [System.IO.FileAccess]::Write,
                [System.IO.FileShare]::ReadWrite
            )
            try {
                $stream.Write($bytes, 0, $bytes.Length)
            }
            finally {
                $stream.Dispose()
            }
            return
        }
        catch {
            if ($attempt -eq 9) {
                throw
            }
            Start-Sleep -Milliseconds 100
        }
    }
}

if (-not (Test-Path -LiteralPath $PythonPath)) {
    throw "python.exe not found at $PythonPath"
}
if ([string]::IsNullOrWhiteSpace($HostAgentHost)) {
    $HostAgentHost = "0.0.0.0"
}
if ([string]::IsNullOrWhiteSpace($HostAgentPort)) {
    $HostAgentPort = "18796"
}

$startInfo = [System.Diagnostics.ProcessStartInfo]::new()
$startInfo.FileName = $PythonPath
$startInfo.Arguments = "-m uvicorn main:app --host $HostAgentHost --port $HostAgentPort --lifespan on --no-access-log --log-level warning"
$startInfo.WorkingDirectory = $PSScriptRoot
$startInfo.UseShellExecute = $false
$startInfo.CreateNoWindow = $true
$startInfo.RedirectStandardOutput = $false
$startInfo.RedirectStandardError = $false
$startInfo.Environment["ZERO_WAKE_MODE"] = "off"
$startInfo.Environment["ZERO_HOST_AGENT_WARMUP"] = "false"
if ([string]::IsNullOrWhiteSpace($startInfo.Environment["ZERO_REACHY_DAEMON_ARGS"])) {
    $startInfo.Environment["ZERO_REACHY_DAEMON_ARGS"] = "--no-preload --no-media"
}

$process = [System.Diagnostics.Process]::new()
$process.StartInfo = $startInfo

$stdoutHandler = [System.Diagnostics.DataReceivedEventHandler]{
    param($sender, $eventArgs)
    if ($null -ne $eventArgs.Data) {
        Write-HostAgentLog $eventArgs.Data
    }
}
$stderrHandler = [System.Diagnostics.DataReceivedEventHandler]{
    param($sender, $eventArgs)
    if ($null -ne $eventArgs.Data) {
        Write-HostAgentLog $eventArgs.Data
    }
}

if ($startInfo.RedirectStandardOutput) {
    $process.add_OutputDataReceived($stdoutHandler)
}
if ($startInfo.RedirectStandardError) {
    $process.add_ErrorDataReceived($stderrHandler)
}

Write-HostAgentLog "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] [auto-restart] host_agent child starting via hidden runner on ${HostAgentHost}:${HostAgentPort} ..."
[void]$process.Start()
if ($startInfo.RedirectStandardOutput) {
    $process.BeginOutputReadLine()
}
if ($startInfo.RedirectStandardError) {
    $process.BeginErrorReadLine()
}

$healthUrl = "http://127.0.0.1:${HostAgentPort}/health"
function Test-HostAgentHealth {
    & curl.exe -fsS --max-time 5 $healthUrl *> $null
    return $LASTEXITCODE -eq 0
}

$isHealthy = $false
for ($attempt = 1; $attempt -le $StartupAttempts; $attempt++) {
    if ($process.HasExited) {
        $process.WaitForExit(2000) | Out-Null
        Write-HostAgentLog "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] [auto-restart] host_agent child exited during startup with code $($process.ExitCode)"
        exit $process.ExitCode
    }
    if (Test-HostAgentHealth) {
        $isHealthy = $true
        break
    }
    Start-Sleep -Seconds 2
}

if (-not $isHealthy) {
    Write-HostAgentLog "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] [auto-restart] host_agent failed startup health check; killing child ..."
    if (-not $process.HasExited) {
        $process.Kill()
        $process.WaitForExit(5000) | Out-Null
    }
    exit 1
}

Write-HostAgentLog "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] [auto-restart] host_agent health is healthy; monitoring child ..."
$failures = 0
while (-not $process.HasExited) {
    Start-Sleep -Seconds 10
    if (Test-HostAgentHealth) {
        $failures = 0
        continue
    }
    $failures++
    if ($failures -lt $FailureThreshold) {
        Write-HostAgentLog "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] [auto-restart] host_agent child health check failed ($failures/$FailureThreshold), retrying ..."
        continue
    }
    Write-HostAgentLog "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] [auto-restart] host_agent child health check failed $FailureThreshold/$FailureThreshold; killing child ..."
    if (-not $process.HasExited) {
        $process.Kill()
        $process.WaitForExit(5000) | Out-Null
    }
    exit 2
}

$process.WaitForExit(2000) | Out-Null
Write-HostAgentLog "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] [auto-restart] host_agent child exited with code $($process.ExitCode)"

exit $process.ExitCode
