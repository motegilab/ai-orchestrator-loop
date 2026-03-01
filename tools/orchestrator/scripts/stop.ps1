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

$targetPid = Get-PidFromFile -Path $pidPath
$remaining = Get-ListenerPids -LocalPort $Port

if ($targetPid -le 0 -and (-not $remaining -or $remaining.Count -eq 0)) {
  Remove-Item -LiteralPath $pidPath -Force -ErrorAction SilentlyContinue
  Write-Host "No running orchestrator detected. Nothing to stop."
  exit 0
}

if ($targetPid -gt 0) {
  try {
    $proc = Get-Process -Id $targetPid -ErrorAction Stop
    Stop-Process -Id $targetPid -Force -ErrorAction Stop
    Write-Host "Stopped PID=$targetPid ($($proc.ProcessName)) from pid file."
  }
  catch {
    Write-Warning "PID from pid file could not be stopped (PID=$targetPid): $($_.Exception.Message)"
  }
}

$deadline = (Get-Date).AddSeconds([Math]::Max(1, $WaitSeconds))
while ((Get-Date) -lt $deadline) {
  $remaining = Get-ListenerPids -LocalPort $Port
  if ($remaining -and $remaining.Count -gt 0) {
    foreach ($procId in $remaining) {
      try {
        $proc = Get-Process -Id $procId -ErrorAction Stop
        Stop-Process -Id $procId -Force -ErrorAction Stop
        Write-Host "Stopped PID=$procId ($($proc.ProcessName)) on port $Port."
      }
      catch {
        Write-Warning "Failed to stop PID=${procId}: $($_.Exception.Message)"
      }
    }
  }

  $targetStillRunning = $false
  if ($targetPid -gt 0) {
    try {
      Get-Process -Id $targetPid -ErrorAction Stop | Out-Null
      $targetStillRunning = $true
    }
    catch {
      $targetStillRunning = $false
    }
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
