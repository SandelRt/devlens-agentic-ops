# DevLens Demo Data Loader
# Run AFTER install_devlens.ps1
# Loads the synthetic observability CSV files into Splunk
# Run as Administrator

$SPLUNK_BIN  = "C:\Program Files\Splunk\bin\splunk.exe"
$DATA_DIR    = "C:\Users\user\Desktop\Web Agency\devlens\data"
$SPLUNK_HOST = "localhost"
$SPLUNK_PORT = "8089"

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  DevLens Demo Data Loader" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""

# Prompt for credentials
$cred = Get-Credential -Message "Enter your Splunk admin credentials"
$user = $cred.UserName
$pass = $cred.GetNetworkCredential().Password

$baseUrl = "https://${SPLUNK_HOST}:${SPLUNK_PORT}"

# Helper: POST to Splunk REST API
function Invoke-SplunkRest {
    param($endpoint, $body)
    $uri = "${baseUrl}${endpoint}"
    try {
        $response = Invoke-RestMethod -Uri $uri -Method Post -Body $body `
            -Credential (New-Object PSCredential($user, (ConvertTo-SecureString $pass -AsPlainText -Force))) `
            -SkipCertificateCheck -ContentType "application/x-www-form-urlencoded"
        return $response
    } catch {
        Write-Host "  [WARN] REST call failed: $_" -ForegroundColor Yellow
        return $null
    }
}

Write-Host "[*] Loading demo data files into Splunk..." -ForegroundColor Yellow
Write-Host "    Note: This may take a few minutes for large files" -ForegroundColor Gray
Write-Host ""

# Load access_logs.csv
$accessLog = "$DATA_DIR\access_logs.csv"
if (Test-Path $accessLog) {
    $sizeMB = [math]::Round((Get-Item $accessLog).Length / 1MB, 1)
    Write-Host "[*] Loading access_logs.csv ($sizeMB MB)..." -ForegroundColor Yellow
    
    $body = @{
        search = "| inputcsv `"$accessLog`" | eval _time=strptime(_time, `"%Y-%m-%dT%H:%M:%S.%3NZ`") | outputlookup devlens_access_logs.csv"
        output_mode = "json"
        exec_mode = "oneshot"
        earliest_time = "0"
        latest_time = "now"
    }
    Invoke-SplunkRest "/services/search/jobs" $body | Out-Null
    Write-Host "[OK] access_logs.csv loaded" -ForegroundColor Green
}

# Load deployment_events.csv
$deployLog = "$DATA_DIR\deployment_events.csv"
if (Test-Path $deployLog) {
    Write-Host "[*] Loading deployment_events.csv..." -ForegroundColor Yellow
    $body = @{
        search = "| inputcsv `"$deployLog`" | eval _time=strptime(_time, `"%Y-%m-%dT%H:%M:%SZ`") | outputlookup devlens_deployments.csv"
        output_mode = "json"
        exec_mode = "oneshot"
        earliest_time = "0"
        latest_time = "now"
    }
    Invoke-SplunkRest "/services/search/jobs" $body | Out-Null
    Write-Host "[OK] deployment_events.csv loaded" -ForegroundColor Green
}

# Load infrastructure_metrics.csv
$metricsLog = "$DATA_DIR\infrastructure_metrics.csv"
if (Test-Path $metricsLog) {
    Write-Host "[*] Loading infrastructure_metrics.csv..." -ForegroundColor Yellow
    $body = @{
        search = "| inputcsv `"$metricsLog`" | eval _time=strptime(_time, `"%Y-%m-%dT%H:%M:%SZ`") | outputlookup devlens_metrics.csv"
        output_mode = "json"
        exec_mode = "oneshot"
        earliest_time = "0"
        latest_time = "now"
    }
    Invoke-SplunkRest "/services/search/jobs" $body | Out-Null
    Write-Host "[OK] infrastructure_metrics.csv loaded" -ForegroundColor Green
}

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  Demo data loaded!" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Test with these SPL queries in Splunk Search:" -ForegroundColor White
Write-Host "  | inputlookup devlens_access_logs.csv | head 5" -ForegroundColor Gray
Write-Host "  | inputlookup devlens_deployments.csv" -ForegroundColor Gray
Write-Host ""
Write-Host "  Then open Apps > DevLens AI and ask:" -ForegroundColor White
Write-Host "  'Why are my APIs returning 500s?'" -ForegroundColor Cyan
Write-Host ""
