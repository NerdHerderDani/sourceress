param(
  [string]$OutDir = "dist-backend"
)

$ErrorActionPreference = 'Stop'

# Build a standalone backend exe using PyInstaller.
# Requirements:
#   py -m pip install pyinstaller
#   backend requirements installed in the same environment

$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root 'backend'

Push-Location $backend

# Make sure runtime deps are installed in this environment (PyInstaller bundles from the current site-packages).
py -m pip install -r requirements.txt | Out-Host
py -m pip install --upgrade pyinstaller | Out-Host

# Onefile is convenient for users; use --noconsole so the backend doesn't pop a terminal window in demos.
py -m PyInstaller `
  --noconfirm `
  --clean `
  --onefile `
  --noconsole `
  --name sourceress-backend `
  --distpath $OutDir `
  --collect-submodules app `
  --add-data "app\static;app\static" `
  --add-data "app\templates;app\templates" `
  --add-data "app\prompts;app\prompts" `
  --add-data "alembic.ini;." `
  --add-data "alembic;alembic" `
  backend_sidecar.py | Out-Host

Write-Host "Built: $(Join-Path (Resolve-Path $OutDir) 'sourceress-backend.exe')"

Pop-Location
