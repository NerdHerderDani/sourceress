# Sourceress — Build on Windows (from source)

## Prereqs
- Python 3.11+
- Node.js 18+
- Rust toolchain (Tauri)

## Backend (dev)
```powershell
cd C:\Users\Dani\clawd\github-sourcer
py -m pip install -r requirements.txt
.\scripts\start_sourcer.ps1
```

## Desktop (dev)
```powershell
cd C:\Users\Dani\clawd\github-sourcer-desktop
npm install
npm run dev
```

## Self-contained (sidecar) build
```powershell
cd C:\Users\Dani\clawd\github-sourcer
.\scripts\build_sidecar.ps1

cd C:\Users\Dani\clawd\github-sourcer-desktop
npm run build
```

Installers:
`github-sourcer-desktop\src-tauri\target\release\bundle\`
