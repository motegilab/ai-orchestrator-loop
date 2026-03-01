param(
  [string]$BindHost = "127.0.0.1",
  [int]$Port = 8765,
  [int]$TimeoutSeconds = 15
)

$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$orchestratorDir = Split-Path -Parent $scriptRoot
$workspaceRoot = (Resolve-Path (Join-Path $orchestratorDir "..\..")).Path
$serverScript = (Resolve-Path (Join-Path $orchestratorDir "server.py")).Path
$healthUrl = "http://$BindHost`:$Port/health"

$runtimeLogDir = Join-Path $workspaceRoot "tools\orchestrator_runtime\logs"
$runtimeStateDir = Join-Path $workspaceRoot "tools\orchestrator_runtime\state"
New-Item -ItemType Directory -Force -Path $runtimeLogDir | Out-Null
New-Item -ItemType Directory -Force -Path $runtimeStateDir | Out-Null
$serverLogPath = Join-Path $runtimeLogDir "server.log"
$pidPath = Join-Path $runtimeStateDir "server.pid"
$readyPath = Join-Path $runtimeStateDir "server.ready.json"

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

function Get-ReadyState {
  param(
    [string]$Path,
    [int]$ExpectedPort
  )

  if (-not (Test-Path -LiteralPath $Path)) {
    return $null
  }

  try {
    $raw = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
    if (-not $raw) {
      return $null
    }
    $json = $raw | ConvertFrom-Json -ErrorAction Stop
    if (-not $json) {
      return $null
    }

    $status = "$($json.status)".Trim().ToLowerInvariant()
    $portValue = 0
    [void][int]::TryParse("$($json.port)", [ref]$portValue)
    if ($status -ne "ok" -or $portValue -ne $ExpectedPort) {
      return $null
    }
    return $json
  }
  catch {
    return $null
  }
}

function Get-ListenerPid {
  param([int]$LocalPort)

  try {
    $rows = Get-NetTCPConnection -LocalPort $LocalPort -State Listen -ErrorAction Stop
    foreach ($row in $rows) {
      if ($row.OwningProcess -gt 0) {
        return [int]$row.OwningProcess
      }
    }
  }
  catch {
    try {
      $lines = netstat -ano -p tcp | Select-String -Pattern "LISTENING"
      foreach ($line in $lines) {
        $parts = (($line.ToString() -replace "\s+", " ").Trim()).Split(" ")
        if ($parts.Count -lt 5) {
          continue
        }
        $localAddress = $parts[1]
        $pidText = $parts[$parts.Count - 1]
        if ($localAddress -notmatch ":(\d+)$") {
          continue
        }
        if ([int]$Matches[1] -ne $LocalPort) {
          continue
        }
        $parsedPid = 0
        if ([int]::TryParse($pidText, [ref]$parsedPid) -and $parsedPid -gt 0) {
          return $parsedPid
        }
      }
    }
    catch {
    }
  }

  return 0
}

function Get-PidFromFile {
  param([string]$Path)

  if (-not (Test-Path -LiteralPath $Path)) {
    return 0
  }
  try {
    $raw = (Get-Content -LiteralPath $Path -Raw -Encoding UTF8).Trim()
    $parsed = 0
    if ([int]::TryParse($raw, [ref]$parsed) -and $parsed -gt 0) {
      return $parsed
    }
  }
  catch {
  }
  return 0
}

function Write-PidFile {
  param([string]$Path, [int]$ProcessId)
  Set-Content -LiteralPath $Path -Value "$ProcessId" -Encoding Ascii
}

function Escape-SingleQuoted {
  param([string]$Text)
  return ($Text -replace "'", "''")
}

if (Test-Health -Url $healthUrl) {
  $runningPid = Get-ListenerPid -LocalPort $Port
  if ($runningPid -gt 0) {
    Write-PidFile -Path $pidPath -ProcessId $runningPid
  }
  $readyState = Get-ReadyState -Path $readyPath -ExpectedPort $Port
  if ($readyState) {
    $bootId = "$($readyState.boot_id)"
    Write-Host "KIDOU_DETECTED: startup beacon detected (boot_id=$bootId, ready_file=$readyPath)"
  }
  else {
    Write-Host "KIDOU_DETECTED: health is OK but startup beacon not found yet (ready_file=$readyPath)"
  }
  Write-Host "KIDOU_SUCCESS (起動成功): Orchestrator already running (visible window): $healthUrl (PID=$runningPid)"
  exit 0
}

$stalePid = Get-PidFromFile -Path $pidPath
if ($stalePid -gt 0) {
  try {
    Get-Process -Id $stalePid -ErrorAction Stop | Out-Null
  }
  catch {
    Remove-Item -LiteralPath $pidPath -Force -ErrorAction SilentlyContinue
  }
}

$python = Get-Command python -ErrorAction Stop
$hostShell = ""
try {
  $hostShell = (Get-Process -Id $PID -ErrorAction Stop).Path
}
catch {
}
if (-not $hostShell -or -not (Test-Path -LiteralPath $hostShell)) {
  $pwsh = Get-Command pwsh -ErrorAction SilentlyContinue
  if ($pwsh) {
    $hostShell = $pwsh.Source
  }
  else {
    $hostShell = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
  }
}

$workspaceEsc = Escape-SingleQuoted -Text $workspaceRoot
$pythonEsc = Escape-SingleQuoted -Text $python.Source
$serverEsc = Escape-SingleQuoted -Text $serverScript
$inlineCommand = "Set-Location -LiteralPath '$workspaceEsc'; try { `$host.UI.RawUI.WindowTitle = 'AI Orchestrator Server' } catch {}; `$env:PYTHONUNBUFFERED='1'; & '$pythonEsc' '$serverEsc'"

$process = Start-Process `
  -FilePath $hostShell `
  -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $inlineCommand) `
  -WorkingDirectory $workspaceRoot `
  -WindowStyle Normal `
  -PassThru

$deadline = (Get-Date).AddSeconds([Math]::Max(1, $TimeoutSeconds))
$lastBeaconError = ""
while ((Get-Date) -lt $deadline) {
  if (Test-Health -Url $healthUrl) {
    $readyState = Get-ReadyState -Path $readyPath -ExpectedPort $Port
    if ($readyState) {
      $listenerPid = Get-ListenerPid -LocalPort $Port
      $pidToStore = if ($listenerPid -gt 0) { $listenerPid } else { [int]$process.Id }
      Write-PidFile -Path $pidPath -ProcessId $pidToStore
      $bootId = "$($readyState.boot_id)"
      Write-Host "KIDOU_SUCCESS (起動成功): Orchestrator started (visible window): $healthUrl (PID=$pidToStore)"
      Write-Host "KIDOU_DETECTED: startup beacon detected (boot_id=$bootId, ready_file=$readyPath)"
      exit 0
    }
    $lastBeaconError = "health_ok_but_startup_beacon_missing_or_invalid"
  }
  Start-Sleep -Milliseconds 300
}

if ($process -and -not $process.HasExited) {
  Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
}
Remove-Item -LiteralPath $pidPath -Force -ErrorAction SilentlyContinue
if ($lastBeaconError) {
  Write-Error "Orchestrator health became OK, but startup beacon verification failed ($lastBeaconError): $readyPath"
}
else {
  Write-Error "Orchestrator did not become healthy within $TimeoutSeconds seconds."
}
exit 1
