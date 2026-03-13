param(
  [string]$BindHost = "127.0.0.1",
  [int]$Port = 0,
  [int]$TimeoutSeconds = 15
)

$ErrorActionPreference = "Stop"

if ($Port -le 0) {
  $envPort = 0
  if ($env:ORCH_PORT -and [int]::TryParse($env:ORCH_PORT, [ref]$envPort)) {
    $Port = $envPort
  }
  else {
    $Port = 8765
  }
}

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$stopScript = Join-Path $scriptRoot "stop.ps1"
$runScript = Join-Path $scriptRoot "run.ps1"

if (-not (Test-Path -LiteralPath $stopScript)) {
  Write-Error "stop.ps1 not found: $stopScript"
  exit 1
}
if (-not (Test-Path -LiteralPath $runScript)) {
  Write-Error "run.ps1 not found: $runScript"
  exit 1
}

& $stopScript -Port $Port -WaitSeconds $TimeoutSeconds
if ($LASTEXITCODE -ne 0) {
  exit $LASTEXITCODE
}

$runFailed = $false
$runExitCode = 0
$runErrorMessage = ""
try {
  & $runScript -BindHost $BindHost -Port $Port -TimeoutSeconds $TimeoutSeconds
  $runExitCode = $LASTEXITCODE
  if ($runExitCode -ne 0) {
    $runFailed = $true
  }
}
catch {
  $runFailed = $true
  $runExitCode = if ($LASTEXITCODE -ne $null) { [int]$LASTEXITCODE } else { 1 }
  $runErrorMessage = $_.Exception.Message
}

if ($runFailed) {
  # Fallback: if run script reported failure but health is already OK, do not fail restart.
  try {
    $probe = Invoke-WebRequest -UseBasicParsing -Uri "http://$BindHost`:$Port/health" -Method Get -TimeoutSec 2
    if ($probe.StatusCode -eq 200) {
      Write-Warning "run.ps1 reported failure, but health is already OK. Continuing."
      Write-Host "Restart OK: http://$BindHost`:$Port/health"
      exit 0
    }
  }
  catch {
  }

  if ($runErrorMessage) {
    Write-Error $runErrorMessage
  }
  exit $(if ($runExitCode -ne 0) { $runExitCode } else { 1 })
}

$healthUrl = "http://$BindHost`:$Port/health"
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
while ((Get-Date) -lt $deadline) {
  try {
    $response = Invoke-WebRequest -UseBasicParsing -Uri $healthUrl -Method Get -TimeoutSec 2
    if ($response.StatusCode -eq 200) {
      Write-Host "Restart OK: $healthUrl"
      exit 0
    }
  }
  catch {
  }
  Start-Sleep -Milliseconds 300
}

Write-Error "Restart failed: health did not return 200 within $TimeoutSeconds seconds at $healthUrl"
exit 1
