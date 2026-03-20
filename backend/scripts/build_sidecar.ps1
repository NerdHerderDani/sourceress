$ErrorActionPreference = 'Stop'

$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$desktop = (Resolve-Path (Join-Path $root '..\desktop')).Path

Set-Location $root

# Ensure deps are available in the Python environment used for building
py -m pip install --upgrade pip | Out-Null
py -m pip install -r requirements.txt | Out-Null
py -m pip install pyinstaller | Out-Null

# Build the backend sidecar exe
py -m PyInstaller --noconfirm --clean --onefile `
  --name sourceress-backend `
  --paths "$root" `
  --collect-all fastapi `
  --collect-all starlette `
  --collect-all sqlmodel `
  --collect-all sqlalchemy `
  --collect-all uvicorn `
  --collect-all jinja2 `
  --collect-all cryptography `
  --hidden-import fastapi `
  --hidden-import starlette `
  --hidden-import sqlmodel `
  --hidden-import sqlalchemy `
  --hidden-import uvicorn `
  --hidden-import jinja2 `
  --hidden-import cryptography `
  --add-data "alembic;alembic" `
  --add-data "alembic.ini;." `
  --add-data "app;app" `
  --add-data "app\templates;app\templates" `
  --add-data "app\static;app\static" `
  backend_sidecar.py

# Copy into Tauri sidecar bin dir
$binDir = Join-Path $desktop 'src-tauri\bin'
New-Item -ItemType Directory -Force -Path $binDir | Out-Null

$src = Join-Path $root 'dist\sourceress-backend.exe'

# Tauri expects externalBin name suffixed with the target triple on Windows release builds.
$dst1 = Join-Path $binDir 'sourceress-backend.exe'
$dst2 = Join-Path $binDir 'sourceress-backend-x86_64-pc-windows-msvc.exe'

Copy-Item -Force $src $dst1
Copy-Item -Force $src $dst2

Write-Host "Sidecar built: $dst1" -ForegroundColor Green
Write-Host "Sidecar built: $dst2" -ForegroundColor Green
