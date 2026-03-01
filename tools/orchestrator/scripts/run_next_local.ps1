param(
  [Parameter(ValueFromRemainingArguments = $true)]
  [string[]]$Args
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$workspaceRoot = Resolve-Path (Join-Path $scriptDir "..\..\..")
$pythonScript = Join-Path $scriptDir "run_next_local.py"

if (-not (Test-Path -LiteralPath $pythonScript)) {
  Write-Error "Script not found: $pythonScript"
  exit 1
}

Push-Location $workspaceRoot
try {
  & python $pythonScript @Args
  exit $LASTEXITCODE
}
finally {
  Pop-Location
}
