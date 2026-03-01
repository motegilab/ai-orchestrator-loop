param(
  [string]$BindHost = "127.0.0.1",
  [int]$Port = 8765
)

$ErrorActionPreference = "Stop"
$url = "http://$BindHost`:$Port/health"

try {
  $response = Invoke-WebRequest -UseBasicParsing -Uri $url -Method Get -TimeoutSec 5
  if ($response.StatusCode -ne 200) {
    Write-Error "Health check failed: status=$($response.StatusCode), body=$($response.Content)"
    exit 1
  }

  Write-Host "Health OK: status=200"
  Write-Host $response.Content
  exit 0
}
catch {
  Write-Error "Health check request failed: $($_.Exception.Message)"
  exit 1
}
