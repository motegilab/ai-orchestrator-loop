# orch_health_check.ps1
# Placeholder: future health check for Claude Code loop state.
# In v1, there is no HTTP server — health is determined by runtime file state.
# Safe to run. Non-destructive.

$RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)

Write-Host "[health-check] Checking loop state..."
Write-Host ""

# Check latest run
$latestJson = Join-Path $RepoRoot "runtime/runs/latest.json"
if (Test-Path $latestJson) {
    $data = Get-Content $latestJson -Raw | ConvertFrom-Json
    Write-Host "  run_id  : $($data.run_id)"
    Write-Host "  status  : $($data.status)"
    Write-Host "  stopped : $($data.stopped_at)"
    Write-Host "  summary : $($data.summary)"
} else {
    Write-Host "  No runtime data yet. Run 'make loop-start' first."
}

Write-Host ""

# Check latest report
$latestReport = Join-Path $RepoRoot "runtime/reports/REPORT_LATEST.md"
if (Test-Path $latestReport) {
    Write-Host "  REPORT_LATEST.md: exists"
    $firstLines = Get-Content $latestReport | Select-Object -First 5
    foreach ($line in $firstLines) { Write-Host "    $line" }
} else {
    Write-Host "  REPORT_LATEST.md: not found"
}

Write-Host ""
Write-Host "[health-check] Done."
Write-Host ""
Write-Host "NOTE: In v1, there is no HTTP server. Health = runtime file state."
Write-Host "      Future v2 may add a lightweight status endpoint."
