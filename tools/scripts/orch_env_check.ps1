# orch_env_check.ps1
# Environment check for AI Orchestrator Loop (Claude-First)
# Safe to run multiple times. Non-destructive.

param(
    [switch]$Verbose
)

$RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Write-Host "[env-check] Repo root: $RepoRoot"
Write-Host ""

$Errors = @()
$Warnings = @()

# --- Required tools ---
Write-Host "=== Tools ==="

$claudeVersion = (claude --version 2>&1)
if ($LASTEXITCODE -eq 0) {
    Write-Host "  [OK] claude: $claudeVersion"
} else {
    $Errors += "claude CLI not found. Install from https://claude.ai/download"
    Write-Host "  [FAIL] claude not found"
}

$pyVersion = (python --version 2>&1)
if ($LASTEXITCODE -ne 0) {
    $pyVersion = (python3 --version 2>&1)
}
if ($LASTEXITCODE -eq 0) {
    Write-Host "  [OK] python: $pyVersion"
} else {
    $Errors += "Python not found. Install Python 3.9+"
    Write-Host "  [FAIL] python not found"
}

$makeVersion = (make --version 2>&1 | Select-Object -First 1)
if ($LASTEXITCODE -eq 0) {
    Write-Host "  [OK] make: $makeVersion"
} else {
    $Warnings += "make not found. Install GNU Make (via Git for Windows or Chocolatey)"
    Write-Host "  [WARN] make not found (required for loop-start)"
}

Write-Host ""

# --- Required files ---
Write-Host "=== Required Files ==="
$RequiredFiles = @(
    "SSOT.md",
    "CLAUDE.md",
    "Makefile",
    ".gitignore",
    ".claude/settings.json",
    "policy/policy.json",
    "policy/ssot_integrity.json"
)

foreach ($f in $RequiredFiles) {
    $fullPath = Join-Path $RepoRoot $f
    if (Test-Path $fullPath) {
        Write-Host "  [OK] $f"
    } else {
        $Errors += "Missing required file: $f"
        Write-Host "  [FAIL] $f not found"
    }
}

Write-Host ""

# --- Runtime directory ---
Write-Host "=== Runtime Directory ==="
$runtimePath = Join-Path $RepoRoot "runtime"
if (Test-Path $runtimePath) {
    Write-Host "  [OK] runtime/ exists"
} else {
    $Warnings += "runtime/ not found. Run 'make setup' to create it."
    Write-Host "  [WARN] runtime/ not found (run 'make setup')"
}

Write-Host ""

# --- SSOT integrity ---
Write-Host "=== SSOT Integrity ==="
$gateScript = Join-Path $RepoRoot ".claude/hooks/ssot_gate.py"
if (Test-Path $gateScript) {
    Push-Location $RepoRoot
    $gateResult = (python $gateScript 2>&1)
    $gateExit = $LASTEXITCODE
    Pop-Location
    if ($gateExit -eq 0) {
        Write-Host "  [OK] SSOT.md hash matches policy/ssot_integrity.json"
    } else {
        $Errors += "SSOT integrity check failed: $gateResult"
        Write-Host "  [FAIL] SSOT integrity mismatch"
        Write-Host "         Run: python .claude/hooks/ssot_gate.py --update-hash"
    }
} else {
    $Warnings += "ssot_gate.py not found — skipping integrity check"
    Write-Host "  [WARN] ssot_gate.py not found"
}

Write-Host ""

# --- Summary ---
Write-Host "=== Summary ==="
if ($Errors.Count -eq 0 -and $Warnings.Count -eq 0) {
    Write-Host "  All checks passed. Ready to run: make loop-start"
} else {
    foreach ($e in $Errors) { Write-Host "  [ERROR] $e" }
    foreach ($w in $Warnings) { Write-Host "  [WARN]  $w" }
    if ($Errors.Count -gt 0) {
        Write-Host ""
        Write-Host "  Fix errors above before running make loop-start."
    }
}
