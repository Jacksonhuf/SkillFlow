#Requires -Version 5.1
<#
.SYNOPSIS
  One-shot setup for universal-browser: chrome-use CLI + native bridge + Chrome Web Store extension.

.NOTES
  - Chrome extension cannot be silently installed on consumer Windows Chrome (Google policy).
    This script opens the official Web Store page; user clicks "Add to Chrome" once.
  - Bundled CLI: place chrome-use.exe next to this script under .\vendor\chrome-use\
    or set CHROME_USE_BIN before running.
#>
param(
    [string]$InstallDir = "$env:LOCALAPPDATA\UniversalBrowser\chrome-use",
    [switch]$SkipExtensionPage,
    [switch]$SkipDoctor
)

$ErrorActionPreference = "Stop"
$ExtensionId = "knfcmbamhjmaonkfnjhldjedeobeafmk"
$StoreUrl = "https://chromewebstore.google.com/detail/chrome-use/$ExtensionId"

function Write-Step([string]$Message) {
    Write-Host "==> $Message" -ForegroundColor Cyan
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BundledExe = Join-Path $ScriptDir "vendor\chrome-use\chrome-use.exe"

$SourceExe = $env:CHROME_USE_BIN
if (-not $SourceExe -and (Test-Path $BundledExe)) {
    $SourceExe = $BundledExe
}

if (-not $SourceExe -or -not (Test-Path $SourceExe)) {
    Write-Host @"

ERROR: chrome-use.exe not found.

Place chrome-use.exe at:
  $BundledExe

Or download sidecar from SkillFlow release universal-browser-chrome-use-sidecar-*.zip
and extract vendor\chrome-use\ here.

Or set CHROME_USE_BIN to an existing chrome-use.exe and re-run.

"@ -ForegroundColor Red
    exit 1
}

New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
$TargetExe = Join-Path $InstallDir "chrome-use.exe"
Write-Step "Installing CLI to $TargetExe"
Copy-Item -Force $SourceExe $TargetExe

# User PATH (no admin)
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($userPath -notlike "*$InstallDir*") {
    Write-Step "Adding install dir to user PATH"
    $newPath = if ($userPath) { "$userPath;$InstallDir" } else { $InstallDir }
    [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
    $env:Path = "$env:Path;$InstallDir"
}

$env:CHROME_USE_BIN = $TargetExe

Write-Step "Registering native-messaging bridge (chrome-use extension install)"
& $TargetExe extension install
if ($LASTEXITCODE -ne 0) {
    Write-Host "WARN: extension install exited $LASTEXITCODE (extension may still work after Store install)" -ForegroundColor Yellow
}

if (-not $SkipExtensionPage) {
    Write-Step "Opening Chrome Web Store (click Add to Chrome once)"
    Start-Process $StoreUrl
}

if (-not $SkipDoctor) {
    Write-Step "Running chrome-use doctor"
    & $TargetExe doctor
}

Write-Host @"

Done.

CLI: $TargetExe
Extension ID: $ExtensionId

After adding the extension in Chrome, run from your skill folder:
  py scripts\invoke.py start

"@ -ForegroundColor Green
