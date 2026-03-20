$ErrorActionPreference = 'Stop'

$root = 'C:\Users\Dani\clawd\github-sourcer'
Set-Location $root

# Load .env into current process env (best-effort)
if (Test-Path .env) {
  Get-Content .env | ForEach-Object {
    if ($_ -match '^\s*#' -or $_ -match '^\s*$') { return }
    $kv = $_.Split('=',2)
    if ($kv.Length -eq 2) {
      $name = $kv[0].Trim()
      $val = $kv[1].Trim()
      if ($name) { [Environment]::SetEnvironmentVariable($name, $val) }
    }
  }
}

function Get-FreePort {
  param([int]$Start=8000,[int]$End=8999)
  for ($p=$Start; $p -le $End; $p++) {
    try {
      $l = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $p)
      $l.Start()
      $l.Stop()
      return $p
    } catch {
      # try next
    }
  }
  throw "No free port found in range $Start-$End"
}

$port = Get-FreePort

# Ensure DB is migrated
py -m alembic -c alembic.ini upgrade head | Out-Null

# Start uvicorn in a separate process WITH logs (so failures aren't silent)
$uvicorn = "py -m uvicorn app.main:app --app-dir . --host 127.0.0.1 --port $port"

$dataDir = Join-Path $root 'data'
if (-not (Test-Path $dataDir)) { New-Item -ItemType Directory -Path $dataDir | Out-Null }
$log = Join-Path $dataDir 'uvicorn.log'

# Use a visible window so you can see tracebacks during dev/demo.
# Also tee output to a log file for easy copy/paste.
$cmd = "cd '$root'; $uvicorn 2>&1 | Tee-Object -FilePath '$log'"
Start-Process -WindowStyle Normal -FilePath "powershell" -ArgumentList "-NoProfile -ExecutionPolicy Bypass -NoExit -Command $cmd"

# Give server a moment, then open browser (only if listening)
Start-Sleep -Milliseconds 900
$ok = (Test-NetConnection 127.0.0.1 -Port $port).TcpTestSucceeded
if ($ok) {
  Start-Process "http://127.0.0.1:$port/"
} else {
  Write-Host "Backend failed to start on port $port. Check $log" -ForegroundColor Red
  Start-Process notepad.exe $log
}

# Write port to a file so we can stop it later
Set-Content -Path "$root\data\last_port.txt" -Value $port
