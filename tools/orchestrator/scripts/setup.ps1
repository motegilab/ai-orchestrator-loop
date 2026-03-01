param(
  [string]$BindHost = "127.0.0.1",
  [int]$Port = 8765,
  [int]$TimeoutSeconds = 5
)

$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$orchestratorDir = Split-Path -Parent $scriptRoot
$workspaceRoot = Resolve-Path (Join-Path $orchestratorDir "..\..")
$cursorDir = Join-Path $workspaceRoot ".cursor"
$hooksPath = Join-Path $cursorDir "hooks.json"

$runtimeRoot = Join-Path $workspaceRoot "tools\orchestrator_runtime"
$runsDir = Join-Path $runtimeRoot "runs"
$webhooksDir = Join-Path $runtimeRoot "artifacts\webhooks"
$logsDir = Join-Path $runtimeRoot "logs"
$latestPath = Join-Path $runsDir "latest.json"
$nextPromptPath = Join-Path $logsDir "next_prompt.md"

$runScript = Join-Path $scriptRoot "run.ps1"
$postEventScript = Join-Path $scriptRoot "post_event.ps1"
$healthUrl = "http://$BindHost`:$Port/health"
$shellPath = (Get-Process -Id $PID).Path

function ConvertTo-NativeObject {
  param([Parameter(ValueFromPipeline = $true)]$InputObject)

  if ($null -eq $InputObject) {
    return $null
  }

  if ($InputObject -is [string] -or $InputObject.GetType().IsPrimitive) {
    return $InputObject
  }

  if ($InputObject -is [System.Collections.IDictionary]) {
    $result = @{}
    foreach ($key in $InputObject.Keys) {
      $result[$key] = ConvertTo-NativeObject $InputObject[$key]
    }
    return $result
  }

  if (($InputObject -is [System.Collections.IEnumerable]) -and -not ($InputObject -is [string])) {
    $list = @()
    foreach ($item in $InputObject) {
      $list += ,(ConvertTo-NativeObject $item)
    }
    return $list
  }

  $properties = $InputObject.PSObject.Properties
  if ($properties.Count -gt 0) {
    $result = @{}
    foreach ($prop in $properties) {
      $result[$prop.Name] = ConvertTo-NativeObject $prop.Value
    }
    return $result
  }

  return $InputObject
}

function Ensure-HookEntry {
  param(
    [hashtable]$Hooks,
    [string]$EventName,
    [string]$Command,
    [int]$Timeout = 10
  )

  $entries = @()
  if ($Hooks.ContainsKey($EventName) -and $null -ne $Hooks[$EventName]) {
    $entries = @($Hooks[$EventName])
  }

  $exists = $false
  foreach ($entry in $entries) {
    if ($entry -is [System.Collections.IDictionary]) {
      $entryCommand = "$($entry['command'])"
    }
    else {
      $entryCommand = "$($entry.command)"
    }
    if ($entryCommand -eq $Command) {
      $exists = $true
      break
    }
  }

  if (-not $exists) {
    $entries += ,([ordered]@{
        command = $Command
        timeout = $Timeout
      })
  }

  $Hooks[$EventName] = $entries
}

function Test-Health {
  param([string]$Url)

  try {
    $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -Method Get -TimeoutSec 2
    return $response.StatusCode -eq 200
  }
  catch {
    return $false
  }
}

function Invoke-ChildScript {
  param(
    [string]$ScriptPath,
    [string[]]$Args = @()
  )

  if (-not (Test-Path -LiteralPath $ScriptPath)) {
    throw "Script not found: $ScriptPath"
  }

  $arguments = @("-ExecutionPolicy", "Bypass", "-File", $ScriptPath) + $Args
  $process = Start-Process -FilePath $shellPath -ArgumentList $arguments -Wait -PassThru -NoNewWindow
  if ($process.ExitCode -ne 0) {
    throw "Script failed: $ScriptPath (exit=$($process.ExitCode))"
  }
}

# 1) Ensure .cursor directory
New-Item -ItemType Directory -Force -Path $cursorDir | Out-Null

# 2) Merge .cursor/hooks.json
$hooksRoot = @{}
if (Test-Path -LiteralPath $hooksPath) {
  try {
    $raw = Get-Content -LiteralPath $hooksPath -Raw -Encoding UTF8
    if ($raw.Trim()) {
      $parsed = $raw | ConvertFrom-Json
      $hooksRoot = ConvertTo-NativeObject $parsed
    }
  }
  catch {
    Write-Warning "hooks.json parse failed. Rebuilding with minimal structure."
    $hooksRoot = @{}
  }
}

if (-not ($hooksRoot -is [hashtable])) {
  $hooksRoot = @{}
}

$hooksRoot["version"] = 1

if (-not $hooksRoot.ContainsKey("hooks") -or -not ($hooksRoot["hooks"] -is [hashtable])) {
  if ($hooksRoot.ContainsKey("hooks")) {
    $hooksRoot["hooks"] = ConvertTo-NativeObject $hooksRoot["hooks"]
  }
  else {
    $hooksRoot["hooks"] = @{}
  }
}

if (-not ($hooksRoot["hooks"] -is [hashtable])) {
  $hooksRoot["hooks"] = @{}
}

$hooks = $hooksRoot["hooks"]

$afterFileEditCommand = "powershell -ExecutionPolicy Bypass -File tools/orchestrator/scripts/post_event.ps1 -HookName afterFileEdit -Message file_edited"
$sessionStartCommand = "powershell -ExecutionPolicy Bypass -File tools/orchestrator/scripts/post_event.ps1 -HookName sessionStart -Message session_started"

Ensure-HookEntry -Hooks $hooks -EventName "afterFileEdit" -Command $afterFileEditCommand -Timeout 10
Ensure-HookEntry -Hooks $hooks -EventName "sessionStart" -Command $sessionStartCommand -Timeout 10

$hooksRoot["hooks"] = $hooks
($hooksRoot | ConvertTo-Json -Depth 30) | Set-Content -LiteralPath $hooksPath -Encoding UTF8

# 3) Ensure runtime dirs
New-Item -ItemType Directory -Force -Path $runsDir | Out-Null
New-Item -ItemType Directory -Force -Path $webhooksDir | Out-Null
New-Item -ItemType Directory -Force -Path $logsDir | Out-Null

# 4) Run run.ps1 (child process)
Invoke-ChildScript -ScriptPath $runScript -Args @("-BindHost", $BindHost, "-Port", "$Port", "-TimeoutSeconds", "$TimeoutSeconds")

# 5) Poll health
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
$healthy = $false
while ((Get-Date) -lt $deadline) {
  if (Test-Health -Url $healthUrl) {
    $healthy = $true
    break
  }
  Start-Sleep -Milliseconds 300
}

if (-not $healthy) {
  throw "Setup failed: health check did not pass within $TimeoutSeconds seconds."
}
Write-Host "Setup OK"

# 6) Post setup test event
$beforeLatest = if (Test-Path -LiteralPath $latestPath) { (Get-Item -LiteralPath $latestPath).LastWriteTimeUtc } else { $null }
$beforePrompt = if (Test-Path -LiteralPath $nextPromptPath) { (Get-Item -LiteralPath $nextPromptPath).LastWriteTimeUtc } else { $null }

Invoke-ChildScript -ScriptPath $postEventScript -Args @("-HookName", "setup", "-Message", "setup_test")

# 7) Verify latest.json and next_prompt.md updated
if (-not (Test-Path -LiteralPath $latestPath)) {
  throw "Setup failed: runs/latest.json not found."
}
if (-not (Test-Path -LiteralPath $nextPromptPath)) {
  throw "Setup failed: logs/next_prompt.md not found."
}

$afterLatest = (Get-Item -LiteralPath $latestPath).LastWriteTimeUtc
$afterPrompt = (Get-Item -LiteralPath $nextPromptPath).LastWriteTimeUtc

$latestUpdated = ($null -eq $beforeLatest) -or ($afterLatest -gt $beforeLatest)
$promptUpdated = ($null -eq $beforePrompt) -or ($afterPrompt -gt $beforePrompt)

if (-not $latestUpdated -or -not $promptUpdated) {
  throw "Setup failed: hooks flow did not update runs/latest.json or logs/next_prompt.md."
}

Write-Host "Hooks flow OK"
