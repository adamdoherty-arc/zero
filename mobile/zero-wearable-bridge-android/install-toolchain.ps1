# One-shot installer for the Android build toolchain (JDK 17 + Android SDK).
# Run from an elevated PowerShell the first time. Subsequent `gradlew`
# invocations don't need admin.
#
#   powershell -ExecutionPolicy Bypass -File install-toolchain.ps1
#
# What it does:
#   1. Installs Microsoft OpenJDK 17 via Chocolatey if `java -version` says < 17.
#   2. Installs the Android command-line tools under %LOCALAPPDATA%\Android\Sdk
#      (no admin needed after choco is on the path).
#   3. Accepts SDK licenses + pulls `platform-tools`, `platforms;android-34`,
#      `build-tools;34.0.0`.
#   4. Writes ANDROID_HOME + updates PATH for the current user.
#   5. Persists `sdk.dir=...` into local.properties so Gradle picks it up.
#
# After this finishes, `./gradlew :app:installDebug` works from a
# fresh terminal.

$ErrorActionPreference = "Stop"

function Require-Choco {
    if (-not (Get-Command choco -ErrorAction SilentlyContinue)) {
        Write-Error "Chocolatey not found. Install from https://chocolatey.org/install first."
    }
}

function Install-Jdk17 {
    $javaOk = $false
    try {
        $v = (& java -version 2>&1 | Out-String)
        if ($v -match 'version "?(17|21|22|23)') { $javaOk = $true }
    } catch { }
    if ($javaOk) {
        Write-Host "[toolchain] JDK 17+ already present"
        return
    }
    Write-Host "[toolchain] Installing Microsoft OpenJDK 17 via choco..."
    choco install -y microsoft-openjdk17
}

function Install-AndroidSdk {
    $sdkRoot = "$env:LOCALAPPDATA\Android\Sdk"
    $cmdlineDir = "$sdkRoot\cmdline-tools\latest"
    if (Test-Path "$cmdlineDir\bin\sdkmanager.bat") {
        Write-Host "[toolchain] Android cmdline-tools already present at $sdkRoot"
    } else {
        Write-Host "[toolchain] Downloading Android cmdline-tools..."
        $tmpZip = Join-Path $env:TEMP "android-cmdline.zip"
        $url = "https://dl.google.com/android/repository/commandlinetools-win-11076708_latest.zip"
        Invoke-WebRequest -Uri $url -OutFile $tmpZip
        $stage = Join-Path $env:TEMP "android-cmdline-stage"
        if (Test-Path $stage) { Remove-Item -Recurse -Force $stage }
        Expand-Archive -Path $tmpZip -DestinationPath $stage -Force
        New-Item -ItemType Directory -Force -Path $cmdlineDir | Out-Null
        # Zip extracts to a `cmdline-tools` folder; move its contents to `latest`.
        $inner = Join-Path $stage "cmdline-tools"
        Get-ChildItem -Path $inner | Move-Item -Destination $cmdlineDir -Force
        Remove-Item -Recurse -Force $stage, $tmpZip
    }

    $env:ANDROID_HOME = $sdkRoot
    $env:ANDROID_SDK_ROOT = $sdkRoot
    [Environment]::SetEnvironmentVariable("ANDROID_HOME", $sdkRoot, [EnvironmentVariableTarget]::User)
    [Environment]::SetEnvironmentVariable("ANDROID_SDK_ROOT", $sdkRoot, [EnvironmentVariableTarget]::User)

    $sdkmanager = Join-Path $cmdlineDir "bin\sdkmanager.bat"
    Write-Host "[toolchain] Accepting SDK licenses..."
    'y','y','y','y','y','y','y','y' | & $sdkmanager --licenses | Out-Null
    Write-Host "[toolchain] Installing platform-tools + android-34 + build-tools;34.0.0..."
    & $sdkmanager "platform-tools" "platforms;android-34" "build-tools;34.0.0"
}

function Write-LocalProps {
    $root = Split-Path -Parent $PSCommandPath
    $local = Join-Path $root "local.properties"
    $sdkRoot = "$env:LOCALAPPDATA\Android\Sdk"
    $esc = $sdkRoot -replace '\\','\\' -replace ':', '\:'
    if (Test-Path $local) {
        $existing = Get-Content $local -Raw
        if ($existing -notmatch "sdk\.dir=") {
            Add-Content -Path $local -Value "`nsdk.dir=$esc"
            Write-Host "[toolchain] Appended sdk.dir to local.properties"
        } else {
            Write-Host "[toolchain] local.properties already has sdk.dir"
        }
    } else {
        Write-Error "local.properties missing. Copy local.properties.example first and fill in github_token/meta.* values."
    }
}

Require-Choco
Install-Jdk17
Install-AndroidSdk
Write-LocalProps

Write-Host ""
Write-Host "[toolchain] Done. Open a new terminal, then:"
Write-Host "  cd $(Split-Path -Parent $PSCommandPath)"
Write-Host "  .\gradlew.bat :app:assembleDebug"
Write-Host "  adb install app/build/outputs/apk/debug/app-debug.apk"
