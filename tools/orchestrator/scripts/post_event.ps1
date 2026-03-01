param(
  [string]$HookName = "",
  [string]$Message = "",
  [string]$Json = "",
  [string]$JsonFile = "",
  [string]$Url = "http://127.0.0.1:8765/webhook"
)

$ErrorActionPreference = "Stop"

function Get-GitBranch {
  try {
    $branch = (& git rev-parse --abbrev-ref HEAD 2>$null).Trim()
    if ($branch) {
      return $branch
    }
  }
  catch {
  }
  return "unknown"
}

if (-not $HookName) {
  if ($env:CURSOR_HOOK_NAME) {
    $HookName = $env:CURSOR_HOOK_NAME
  }
  elseif ($env:HOOK_NAME) {
    $HookName = $env:HOOK_NAME
  }
  else {
    $HookName = "manual"
  }
}

$rawInput = $null
if ($JsonFile) {
  if (-not (Test-Path -LiteralPath $JsonFile)) {
    Write-Error "Json file not found: $JsonFile"
    exit 1
  }
  $rawInput = Get-Content -LiteralPath $JsonFile -Raw -Encoding UTF8
}
elseif ($Json) {
  $rawInput = $Json
}
elseif ($Message) {
  $rawInput = $Message
}

$rawPayload = $null
if ($null -ne $rawInput -and $rawInput -ne "") {
  try {
    $rawPayload = $rawInput | ConvertFrom-Json -ErrorAction Stop
  }
  catch {
    $rawPayload = $rawInput
  }
}

if (-not $Message -and $rawInput -is [string]) {
  $Message = $rawInput
}

$payload = [ordered]@{
  hook_name  = $HookName
  timestamp  = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
  cwd        = (Get-Location).Path
  git_branch = Get-GitBranch
  message    = $Message
  raw        = $rawPayload
}

$body = $payload | ConvertTo-Json -Depth 20

try {
  $response = Invoke-RestMethod `
    -Uri $Url `
    -Method Post `
    -ContentType "application/json; charset=utf-8" `
    -Body $body `
    -TimeoutSec 10

  Write-Host "Event posted to $Url"
  $response | ConvertTo-Json -Depth 20
  exit 0
}
catch {
  Write-Error "POST failed: $($_.Exception.Message)"
  exit 1
}
