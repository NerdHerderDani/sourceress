param(
  [string]$BackendOutDir = "dist-backend"
)

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot

Write-Host "== Sourceress Desktop Release (Windows) ==" -ForegroundColor Cyan

# 1) Build backend sidecar exe
Write-Host "[1/3] Building backend sidecar (PyInstaller)..." -ForegroundColor Cyan
& "$root\backend\build-backend-exe.ps1" -OutDir $BackendOutDir

$backendExe = Join-Path $root "backend\$BackendOutDir\sourceress-backend.exe"
if (!(Test-Path $backendExe)) {
  throw "Backend exe not found at: $backendExe"
}

# 2) Copy sidecar into Tauri bundle path
Write-Host "[2/3] Copying backend exe into desktop/src-tauri/bin/..." -ForegroundColor Cyan
$binDir = Join-Path $root "desktop\src-tauri\bin"
New-Item -ItemType Directory -Force -Path $binDir | Out-Null
Copy-Item $backendExe (Join-Path $binDir "sourceress-backend.exe") -Force
# Tauri may reference a target-triple-suffixed sidecar name via tauri.conf.json resources.
# Copy both names to keep builds resilient.
Copy-Item $backendExe (Join-Path $binDir "sourceress-backend-x86_64-pc-windows-msvc.exe") -Force

# 3) Build Tauri installers
Write-Host "[3/3] Building Tauri bundle..." -ForegroundColor Cyan
Push-Location (Join-Path $root "desktop")

if (!(Test-Path "node_modules")) {
  npm install
}

npm run build

Pop-Location

# Compute hashes for release notes
$tauriConf = Join-Path $root "desktop\src-tauri\tauri.conf.json"
$ver = "0.1.0"
try {
  $ver = (Get-Content $tauriConf -Raw | ConvertFrom-Json).version
} catch {}

$msi = Join-Path $root "desktop\src-tauri\target\release\bundle\msi\Sourceress_${ver}_x64_en-US.msi"
$exe = Join-Path $root "desktop\src-tauri\target\release\bundle\nsis\Sourceress_${ver}_x64-setup.exe"

if ((Test-Path $msi) -and (Test-Path $exe)) {
  $msiHash = (Get-FileHash $msi -Algorithm SHA256).Hash
  $exeHash = (Get-FileHash $exe -Algorithm SHA256).Hash
  $buildDate = (Get-Date).ToString('yyyy-MM-dd')

  $notesPath = Join-Path $root "scripts\release_notes_beta.md"

  @"
# Sourceress Desktop Beta Release Notes

Version: 0.1.0 (Windows)
Build date: $buildDate

## What this beta is
- Desktop-only Sourceress app with a local backend sidecar.
- No login required.
- Uses local SQLite DB stored in your app data directory.

## Setup
1) Install and open Sourceress.
2) Click **Settings** → paste your **GitHub token** → **Save**.
3) (Optional) Enable Fubuki:
   - Settings → check **Enable Fubuki** → paste your **Anthropic key (sk-ant-...)** → Save.

## Where logs live
- Click **Diagnostics** → **Open log folder**.
- Attach `backend.log` when reporting issues.

## Known behaviors
- Fubuki is disabled unless you provide an Anthropic key.
- Degen mode is a UI toggle (implemented as a request preset).

## Installers
- MSI: `Sourceress_0.1.0_x64_en-US.msi`
  - SHA256: `$msiHash`
- EXE: `Sourceress_0.1.0_x64-setup.exe`
  - SHA256: `$exeHash`

## How to report a bug (copy/paste template)
**Summary:**

**What I expected:**

**What happened:**

**Steps to reproduce:**
1)
2)
3)

**Diagnostics:**
- Open Sourceress → Diagnostics → Copy diagnostics → paste here.

**Logs:**
- Attach `backend.log` (Diagnostics → Open log folder)

**Screenshot (if relevant):**
"@ | Set-Content -Path $notesPath -Encoding UTF8

  Write-Host "Wrote release notes: $notesPath" -ForegroundColor Green
  Write-Host "MSI SHA256: $msiHash" -ForegroundColor DarkGray
  Write-Host "EXE SHA256: $exeHash" -ForegroundColor DarkGray
}

Write-Host "Done. Installers are under: desktop\src-tauri\target\release\bundle\" -ForegroundColor Green
