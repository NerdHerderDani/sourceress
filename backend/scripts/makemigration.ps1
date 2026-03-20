param(
  [Parameter(Mandatory=$true)][string]$Message
)

Set-Location $PSScriptRoot\..

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

py -m alembic revision --autogenerate -m $Message
