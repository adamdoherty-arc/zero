# Zero Gateway Auto-Update Script
# Reads pending.json from workspace/gateway-update/, performs Docker build + restart.
# Scheduled via Windows Task Scheduler (daily at 4:30 AM).
#
# Usage: powershell -ExecutionPolicy Bypass -File scripts/update-gateway.ps1
# Optional: -DryRun to check without applying

param(
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$ProjectRoot = "C:\code\zero"
$UpdateDir = Join-Path $ProjectRoot "workspace\gateway-update"
$PendingFile = Join-Path $UpdateDir "pending.json"
$LastUpdateFile = Join-Path $UpdateDir "last-update.json"
$HistoryFile = Join-Path $UpdateDir "history.json"
$ConfigFile = Join-Path $ProjectRoot "config\zero.json"
$ComposeFile = Join-Path $ProjectRoot "docker-compose.yml"
$LogFile = Join-Path $UpdateDir "update.log"
$BuildDir = Join-Path $env:TEMP "openclaw-build"
$GatewayUrl = "http://localhost:18789/"
$HealthTimeout = 60  # seconds

# Discord webhook (optional, reads from .env)
$EnvFile = Join-Path $ProjectRoot ".env"

function Write-Log {
    param([string]$Message, [string]$Level = "INFO")
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$ts] [$Level] $Message"
    Write-Host $line
    Add-Content -Path $LogFile -Value $line
}

function Send-DiscordNotification {
    param(
        [string]$Title,
        [string]$Description,
        [int]$Color = 5793266  # blurple
    )
    try {
        # Read Discord bot token and channel from .env
        if (Test-Path $EnvFile) {
            $envContent = Get-Content $EnvFile -Raw
            $botToken = if ($envContent -match 'DISCORD_BOT_TOKEN=(.+)') { $Matches[1].Trim() } else { "" }
            $channelId = if ($envContent -match 'DISCORD_NOTIFICATION_CHANNEL_ID=(.+)') { $Matches[1].Trim() } else { "" }

            if ($botToken -and $channelId) {
                $body = @{
                    embeds = @(@{
                        title       = $Title
                        description = $Description.Substring(0, [Math]::Min($Description.Length, 4096))
                        color       = $Color
                        timestamp   = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
                    })
                } | ConvertTo-Json -Depth 5

                $headers = @{
                    "Authorization" = "Bot $botToken"
                    "Content-Type"  = "application/json"
                }

                Invoke-RestMethod -Uri "https://discord.com/api/v10/channels/$channelId/messages" `
                    -Method Post -Body $body -Headers $headers | Out-Null

                Write-Log "Discord notification sent: $Title"
            }
        }
    }
    catch {
        Write-Log "Discord notification failed: $_" "WARN"
    }
}

function Test-GatewayHealth {
    param([int]$TimeoutSeconds = 60)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $resp = Invoke-WebRequest -Uri $GatewayUrl -UseBasicParsing -TimeoutSec 5
            if ($resp.StatusCode -lt 400) {
                return $true
            }
        }
        catch { }
        Start-Sleep -Seconds 5
    }
    return $false
}

# ============================================
# MAIN
# ============================================

Write-Log "=== Gateway Auto-Update Started ==="

# Ensure update directory exists
if (-not (Test-Path $UpdateDir)) {
    New-Item -ItemType Directory -Path $UpdateDir -Force | Out-Null
}

# Check for pending update
if (-not (Test-Path $PendingFile)) {
    Write-Log "No pending update found. Checking GitHub directly..."

    # Self-check: query GitHub for latest release
    try {
        $headers = @{
            "Accept"     = "application/vnd.github.v3+json"
            "User-Agent" = "Zero-Gateway-Updater"
        }
        # Add GH_TOKEN if available in .env
        if (Test-Path $EnvFile) {
            $envContent = Get-Content $EnvFile -Raw
            if ($envContent -match 'GH_TOKEN=(.+)') {
                $ghToken = $Matches[1].Trim()
                if ($ghToken) {
                    $headers["Authorization"] = "Bearer $ghToken"
                }
            }
        }

        $release = Invoke-RestMethod -Uri "https://api.github.com/repos/openclaw/openclaw/releases/latest" `
            -Headers $headers -TimeoutSec 15

        $latestTag = $release.tag_name
        $latestVersion = $latestTag.TrimStart("v")

        # Read current version
        $config = Get-Content $ConfigFile -Raw | ConvertFrom-Json
        $currentVersion = if ($config.meta.lastTouchedVersion) { $config.meta.lastTouchedVersion } else { $config.lastTouchedVersion }

        if ($latestVersion -eq $currentVersion) {
            Write-Log "Gateway is up to date (v$currentVersion)"
            exit 0
        }

        # Parse CalVer for comparison
        $latestParts = $latestVersion.Split(".") | ForEach-Object { [int]$_ }
        $currentParts = $currentVersion.Split(".") | ForEach-Object { [int]$_ }

        $isNewer = $false
        for ($i = 0; $i -lt [Math]::Min($latestParts.Count, $currentParts.Count); $i++) {
            if ($latestParts[$i] -gt $currentParts[$i]) { $isNewer = $true; break }
            if ($latestParts[$i] -lt $currentParts[$i]) { break }
        }

        if (-not $isNewer) {
            Write-Log "Current v$currentVersion is not behind latest v$latestVersion"
            exit 0
        }

        Write-Log "Update available: v$currentVersion -> v$latestVersion"

        # Create pending.json
        $pending = @{
            version         = $latestVersion
            tag             = $latestTag
            current_version = $currentVersion
            changelog       = $release.body
            url             = $release.html_url
            name            = $release.name
            published_at    = $release.published_at
            detected_at     = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
        }
        $pending | ConvertTo-Json -Depth 5 | Set-Content $PendingFile -Encoding UTF8
    }
    catch {
        Write-Log "GitHub check failed: $_" "ERROR"
        exit 1
    }
}

# Read pending update
$pending = Get-Content $PendingFile -Raw | ConvertFrom-Json
$newVersion = $pending.version
$newTag = $pending.tag
$currentVersion = $pending.current_version
$legionTaskId = $pending.legion_task_id  # Track Legion task for status sync

Write-Log "Upgrading gateway: v$currentVersion -> v$newVersion"

if ($DryRun) {
    Write-Log "[DRY RUN] Would upgrade to v$newVersion. Exiting."
    exit 0
}

$startTime = Get-Date
$success = $false
$errorMsg = ""

try {
    # Step 1: Backup current image
    Write-Log "Step 1/6: Backing up current image as zero:pre-upgrade-$currentVersion"
    docker tag zero:latest "zero:pre-upgrade-$currentVersion" 2>&1 | Out-Null

    # Step 2: Clone openclaw-docker build repo
    Write-Log "Step 2/6: Cloning openclaw-docker build repo"
    if (Test-Path $BuildDir) {
        Remove-Item -Recurse -Force $BuildDir
    }
    git clone --depth 1 https://github.com/phioranex/openclaw-docker.git $BuildDir 2>&1 | ForEach-Object { Write-Log "  git: $_" }

    # Step 3: Build new image
    Write-Log "Step 3/6: Building zero:latest with OPENCLAW_VERSION=$newTag"
    $buildOutput = docker build --build-arg "OPENCLAW_VERSION=$newTag" -t zero:latest $BuildDir 2>&1
    $buildOutput | Select-Object -Last 5 | ForEach-Object { Write-Log "  build: $_" }
    if ($LASTEXITCODE -ne 0) {
        throw "Docker build failed with exit code $LASTEXITCODE"
    }

    # Step 4: Stop gateway
    Write-Log "Step 4/6: Stopping zero-gateway"
    docker compose -f $ComposeFile stop zero-gateway 2>&1 | ForEach-Object { Write-Log "  compose: $_" }

    # Step 5: Start gateway with new image
    Write-Log "Step 5/6: Starting zero-gateway with new image"
    docker compose -f $ComposeFile up -d zero-gateway 2>&1 | ForEach-Object { Write-Log "  compose: $_" }

    # Step 6: Verify health
    Write-Log "Step 6/6: Waiting for gateway health check (up to ${HealthTimeout}s)..."
    if (Test-GatewayHealth -TimeoutSeconds $HealthTimeout) {
        Write-Log "Gateway is healthy on v$newVersion"
        $success = $true
    }
    else {
        throw "Gateway health check failed after ${HealthTimeout}s"
    }
}
catch {
    $errorMsg = $_.Exception.Message
    Write-Log "Upgrade FAILED: $errorMsg" "ERROR"

    # Rollback
    Write-Log "Rolling back to zero:pre-upgrade-$currentVersion"
    try {
        docker tag "zero:pre-upgrade-$currentVersion" zero:latest 2>&1 | Out-Null
        docker compose -f $ComposeFile stop zero-gateway 2>&1 | Out-Null
        docker compose -f $ComposeFile up -d zero-gateway 2>&1 | Out-Null

        if (Test-GatewayHealth -TimeoutSeconds 60) {
            Write-Log "Rollback successful - gateway restored to v$currentVersion"
        }
        else {
            Write-Log "Rollback health check failed!" "ERROR"
        }
    }
    catch {
        Write-Log "Rollback failed: $_" "ERROR"
    }
}
finally {
    # Cleanup build directory
    if (Test-Path $BuildDir) {
        Remove-Item -Recurse -Force $BuildDir -ErrorAction SilentlyContinue
    }
}

$endTime = Get-Date
$duration = ($endTime - $startTime).TotalSeconds

# Write last-update result
$updateResult = @{
    success          = $success
    from_version     = $currentVersion
    to_version       = $newVersion
    tag              = $newTag
    started_at       = $startTime.ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    completed_at     = $endTime.ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    duration_seconds = [Math]::Round($duration, 1)
    error            = $errorMsg
    legion_task_id   = $legionTaskId
}
$updateResult | ConvertTo-Json -Depth 3 | Set-Content $LastUpdateFile -Encoding UTF8

# Append to history
$history = @()
if (Test-Path $HistoryFile) {
    try { $history = Get-Content $HistoryFile -Raw | ConvertFrom-Json } catch { $history = @() }
}
# Ensure history is an array
if ($history -isnot [System.Array]) { $history = @($history) }
$history += $updateResult
# Keep last 50 entries
if ($history.Count -gt 50) { $history = $history[-50..-1] }
ConvertTo-Json $history -Depth 3 | Set-Content $HistoryFile -Encoding UTF8

if ($success) {
    # Update config/zero.json with new version
    try {
        $config = Get-Content $ConfigFile -Raw | ConvertFrom-Json
        if ($config.meta) {
            $config.meta.lastTouchedVersion = $newVersion
            $config.meta.lastTouchedAt = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
        }
        $config | ConvertTo-Json -Depth 10 | Set-Content $ConfigFile -Encoding UTF8
        Write-Log "Updated config/zero.json to v$newVersion"
    }
    catch {
        Write-Log "Failed to update config: $_" "WARN"
    }

    # Remove pending file
    Remove-Item $PendingFile -Force -ErrorAction SilentlyContinue

    Write-Log "=== Upgrade COMPLETE: v$currentVersion -> v$newVersion (${duration}s) ==="

    Send-DiscordNotification `
        -Title "Gateway Updated Successfully" `
        -Description "OpenClaw gateway upgraded from **v$currentVersion** to **v$newVersion** in $([Math]::Round($duration, 0))s.`n`n[Release notes]($($pending.url))" `
        -Color 5763719  # green
}
else {
    Write-Log "=== Upgrade FAILED: v$currentVersion -> v$newVersion ($errorMsg) ==="

    Send-DiscordNotification `
        -Title "Gateway Update Failed" `
        -Description "Failed to upgrade from **v$currentVersion** to **v$newVersion**.`n`nError: $errorMsg`n`nRollback attempted." `
        -Color 15548997  # red
}
