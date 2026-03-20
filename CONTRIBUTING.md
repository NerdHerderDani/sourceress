# Contributing to Sourceress

## Repo layout
- `backend/` FastAPI backend
- `desktop/` Tauri desktop app

## Windows dev
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

## Releases
GitHub Actions builds Windows installers on each push to `main` and updates the `nightly` release.
