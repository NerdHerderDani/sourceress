$ErrorActionPreference = 'SilentlyContinue'
$root = 'C:\Users\Dani\clawd\github-sourcer'
$portFile = "$root\data\last_port.txt"

if (Test-Path $portFile) {
  $port = Get-Content $portFile | Select-Object -First 1
  # Find process listening on that port (best-effort)
  $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
  foreach ($c in $conns) {
    $p = Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue
    if ($p) { Stop-Process -Id $p.Id -Force }
  }
}

# Fallback: stop any uvicorn processes
Get-Process -Name python -ErrorAction SilentlyContinue | Where-Object { $_.Path -like '*Python311*' } | ForEach-Object {
  # can't reliably filter commandline without admin; leave as no-op
}
