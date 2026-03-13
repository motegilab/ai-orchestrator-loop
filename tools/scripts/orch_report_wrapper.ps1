# orch_report_wrapper.ps1
# Placeholder: wrapper to trigger report generation outside of a loop session.
# In v1, reports are generated automatically by the Stop Hook.
# This script is for manual report regeneration or debugging.
# Safe to run. Non-destructive.

param(
    [string]$RunId = "",
    [switch]$ShowLatest
)

$RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)

if ($ShowLatest) {
    $reportPath = Join-Path $RepoRoot "runtime/reports/REPORT_LATEST.md"
    if (Test-Path $reportPath) {
        Write-Host "=== REPORT_LATEST.md ==="
        Get-Content $reportPath
    } else {
        Write-Host "No report found. Run 'make loop-start' to generate one."
    }
    exit 0
}

Write-Host "[report-wrapper] This script is a placeholder for v2 manual report triggering."
Write-Host ""
Write-Host "In v1, reports are generated automatically when a loop session ends."
Write-Host "The Stop Hook (on_stop.py) handles this."
Write-Host ""
Write-Host "To view the latest report:"
Write-Host "  .\tools\scripts\orch_report_wrapper.ps1 -ShowLatest"
Write-Host "  # or:"
Write-Host "  make loop-status"
Write-Host ""
Write-Host "To manually run the Stop Hook (for debugging):"
Write-Host "  python .claude/hooks/on_stop.py"
