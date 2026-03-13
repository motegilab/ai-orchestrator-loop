param(
  [int]$Port = 0,
  [int]$WaitSeconds = 5
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

function Get-ListenerPids {
  param([int]$LocalPort)

  $pidList = New-Object System.Collections.Generic.List[int]

  try {
    $tcpRows = Get-NetTCPConnection -LocalPort $LocalPort -State Listen -ErrorAction Stop
    foreach ($row in $tcpRows) {
      if ($row.OwningProcess -gt 0) {
        [void]$pidList.Add([int]$row.OwningProcess)
      }
    }
  }
  catch {
    # Fallback to netstat parsing on environments where Get-NetTCPConnection is unavailable.
  }

  if ($pidList.Count -eq 0) {
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

        $parsedProcId = 0
        if ([int]::TryParse($pidText, [ref]$parsedProcId) -and $parsedProcId -gt 0) {
          [void]$pidList.Add($parsedProcId)
        }
      }
    }
    catch {
      # If both methods fail, we behave as "no process found".
    }
  }

  return $pidList | Select-Object -Unique
}

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$orchestratorDir = Split-Path -Parent $scriptRoot
$workspaceRoot = (Resolve-Path (Join-Path $orchestratorDir "..\..")).Path
$stateDir = Join-Path $workspaceRoot "tools\orchestrator_runtime\state"
$pidPath = Join-Path $stateDir "server.pid"

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

$attemptedStops = New-Object 'System.Collections.Generic.HashSet[int]'

function Test-PidExists {
  param([int]$ProcId)

  if ($ProcId -le 0) {
    return $false
  }

  try {
    $output = tasklist /FI "PID eq $ProcId" 2>$null
    if (-not $output) {
      return $false
    }
    foreach ($line in $output) {
      if ($line -match "^\s*\S+\s+$ProcId\s+") {
        return $true
      }
    }
    return $false
  }
  catch {
    return $false
  }
}

function Try-StopPid {
  param([int]$ProcId, [string]$Context)

  if ($ProcId -le 0) {
    return $false
  }

  try {
    $proc = Get-Process -Id $ProcId -ErrorAction Stop
  }
  catch {
    return $true
  }

  try {
    Stop-Process -Id $ProcId -Force -ErrorAction Stop
  }
  catch {
    # Keep going and verify actual process state below.
  }

  Start-Sleep -Milliseconds 150

  if (-not (Test-PidExists -ProcId $ProcId)) {
    Write-Host "Stopped PID=$ProcId ($($proc.ProcessName)) $Context."
    return $true
  }

  try {
    $taskkillOutput = taskkill /PID $ProcId /F /T 2>&1
    Start-Sleep -Milliseconds 150
    if (-not (Test-PidExists -ProcId $ProcId)) {
      Write-Host "Stopped PID=$ProcId ($($proc.ProcessName)) $Context."
      return $true
    }
    Write-Warning "Failed to stop PID=${ProcId} $Context. taskkill output: $($taskkillOutput -join ' ')"
    return $false
  }
  catch {
    if (-not (Test-PidExists -ProcId $ProcId)) {
      Write-Host "Stopped PID=$ProcId ($($proc.ProcessName)) $Context."
      return $true
    }
    Write-Warning "Failed to stop PID=${ProcId} $Context."
    return $false
  }
}

function Test-ProcessAlive {
  param([int]$ProcId)

  if ($ProcId -le 0) {
    return $false
  }
  return Test-PidExists -ProcId $ProcId
}

$targetPid = Get-PidFromFile -Path $pidPath
$remaining = Get-ListenerPids -LocalPort $Port

if ($targetPid -le 0 -and (-not $remaining -or $remaining.Count -eq 0)) {
  Remove-Item -LiteralPath $pidPath -Force -ErrorAction SilentlyContinue
  Write-Host "No running orchestrator detected. Nothing to stop."
  exit 0
}

if ($targetPid -gt 0) {
  [void]$attemptedStops.Add([int]$targetPid)
  $stopped = Try-StopPid -ProcId $targetPid -Context "from pid file"
  if (-not $stopped) {
    Write-Warning "PID from pid file could not be stopped (PID=$targetPid)."
  }
}

$deadline = (Get-Date).AddSeconds([Math]::Max(1, $WaitSeconds))
while ((Get-Date) -lt $deadline) {
  $remaining = Get-ListenerPids -LocalPort $Port
  if ($remaining -and $remaining.Count -gt 0) {
    foreach ($procId in $remaining) {
      if ($attemptedStops.Contains([int]$procId)) {
        continue
      }
      [void]$attemptedStops.Add([int]$procId)
      [void](Try-StopPid -ProcId $procId -Context "on port $Port")
    }
  }

  $targetStillRunning = $false
  if ($targetPid -gt 0) {
    $targetStillRunning = Test-ProcessAlive -ProcId $targetPid
  }

  if ((-not $remaining -or $remaining.Count -eq 0) -and -not $targetStillRunning) {
    Remove-Item -LiteralPath $pidPath -Force -ErrorAction SilentlyContinue
    Write-Host "Port $Port is free."
    exit 0
  }

  Start-Sleep -Milliseconds 250
}

Remove-Item -LiteralPath $pidPath -Force -ErrorAction SilentlyContinue
$remaining = Get-ListenerPids -LocalPort $Port
if (-not $remaining -or $remaining.Count -eq 0) {
  Write-Host "Port $Port is free."
  exit 0
}

Write-Error "Failed to free port $Port within $WaitSeconds seconds. Remaining PID(s): $($remaining -join ', ')"
exit 1
