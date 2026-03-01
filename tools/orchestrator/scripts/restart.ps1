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

& $runScript -BindHost $BindHost -Port $Port -TimeoutSeconds $TimeoutSeconds
if ($LASTEXITCODE -ne 0) {
  exit $LASTEXITCODE
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
