# DevLens Install Script
# This script will automatically prompt for Administrator privileges if needed.

# --- Self-Elevation Logic ---
if (-Not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "Elevating privileges to Administrator..." -ForegroundColor Yellow
    Start-Process PowerShell -Verb RunAs -ArgumentList "-NoProfile -ExecutionPolicy Bypass -WindowStyle Normal -File `"$PSCommandPath`""
    exit
}
# --------------------------

$ErrorActionPreference = "Stop"
$SRC  = "C:\Users\user\Desktop\Web Agency\devlens"
$DEST = "C:\Program Files\Splunk\etc\apps\devlens"
$SPLUNK_BIN = "C:\Program Files\Splunk\bin\splunk.exe"

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  DevLens Splunk App Installer" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""

# 1. Check Splunk is installed
if (-not (Test-Path $SPLUNK_BIN)) {
    Write-Host "[ERROR] Splunk not found at $SPLUNK_BIN" -ForegroundColor Red
    Write-Host "        Please install Splunk Enterprise first: https://www.splunk.com/en_us/download/splunk-enterprise.html"
    exit 1
}

Write-Host "[OK] Splunk found: $SPLUNK_BIN" -ForegroundColor Green

# 2. Check source app exists
if (-not (Test-Path "$SRC\app.conf")) {
    Write-Host "[ERROR] DevLens source not found at $SRC" -ForegroundColor Red
    Write-Host "        Make sure you are running this from the correct directory."
    exit 1
}

Write-Host "[OK] DevLens source found: $SRC" -ForegroundColor Green

# 3. Remove old install if present
if (Test-Path $DEST) {
    Write-Host "[*] Removing previous DevLens installation..." -ForegroundColor Yellow
    Remove-Item $DEST -Recurse -Force
}

# 4. Copy app to Splunk apps directory
Write-Host "[*] Installing DevLens to: $DEST" -ForegroundColor Yellow
Copy-Item $SRC $DEST -Recurse -Force

# 5. Copy the data files directly into Splunk's lookups folder so they work immediately!
$lookupsDir = "$DEST\lookups"
if (-not (Test-Path $lookupsDir)) {
    New-Item -ItemType Directory -Path $lookupsDir | Out-Null
}

$DATA_DIR = "$SRC\data"
Write-Host "[*] Copying demo data into Splunk lookups..." -ForegroundColor Yellow
if (Test-Path "$DATA_DIR\access_logs.csv") {
    Copy-Item "$DATA_DIR\access_logs.csv" "$lookupsDir\devlens_access_logs.csv" -Force
}
if (Test-Path "$DATA_DIR\deployment_events.csv") {
    Copy-Item "$DATA_DIR\deployment_events.csv" "$lookupsDir\devlens_deployments.csv" -Force
}
if (Test-Path "$DATA_DIR\infrastructure_metrics.csv") {
    Copy-Item "$DATA_DIR\infrastructure_metrics.csv" "$lookupsDir\devlens_metrics.csv" -Force
}

Write-Host "[OK] App and data files copied successfully" -ForegroundColor Green

# 5. Restart Splunk to load the new app
Write-Host ""
Write-Host "[*] Restarting Splunk to load DevLens..." -ForegroundColor Yellow
Write-Host "    This may take 30-60 seconds..."

& $SPLUNK_BIN restart

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "[OK] Splunk restarted successfully!" -ForegroundColor Green
    Write-Host ""
    Write-Host "==================================================" -ForegroundColor Cyan
    Write-Host "  DevLens installed! Next steps:" -ForegroundColor Cyan
    Write-Host "==================================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  1. Open Splunk Web: http://localhost:8000" -ForegroundColor White
    Write-Host "  2. Go to: Apps > DevLens AI" -ForegroundColor White
    Write-Host "  3. Load demo data: run load_demo_data.ps1" -ForegroundColor White
    Write-Host ""
} else {
    Write-Host "[ERROR] Splunk restart failed (exit code $LASTEXITCODE)" -ForegroundColor Red
    Write-Host "        Try manually: & '$SPLUNK_BIN' restart"
}

Write-Host ""
Write-Host "Press Enter to close this window..." -ForegroundColor Yellow
Read-Host
