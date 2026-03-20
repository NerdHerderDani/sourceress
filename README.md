# Sourceress (Monorepo)

This repo contains:
- `backend/` — FastAPI backend (GitHub Sourceress)
- `desktop/` — Tauri desktop app

## Dev

Backend:
```powershell
cd backend
py -m pip install -r requirements.txt
.\scripts\start_sourcer.ps1
```

Desktop:
```powershell
cd desktop
npm install
npm run dev
```

## Notes
- Do not commit DBs, build artifacts, or `.env` files.
