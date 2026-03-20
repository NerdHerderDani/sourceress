# Sourceress — Build on macOS (from source)

This repo contains two parts:
- `github-sourcer/` — FastAPI backend (also built as a **sidecar** binary)
- `github-sourcer-desktop/` — Tauri desktop app

The desktop app expects a bundled backend sidecar at:
`github-sourcer-desktop/src-tauri/bin/sourceress-backend`

## 0) Prereqs

- Xcode CLT:
  ```bash
  xcode-select --install
  ```
- Node.js (18+ recommended)
- Rust:
  ```bash
  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
  ```
- Tauri CLI v2:
  ```bash
  cargo install tauri-cli
  ```

## 1) Build the backend sidecar

```bash
cd github-sourcer
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install pyinstaller

python -m PyInstaller --noconfirm --clean --onefile \
  --name sourceress-backend \
  --paths "$(pwd)" \
  --collect-all fastapi \
  --collect-all starlette \
  --collect-all sqlmodel \
  --collect-all sqlalchemy \
  --collect-all uvicorn \
  --collect-all jinja2 \
  --collect-all cryptography \
  --hidden-import fastapi \
  --hidden-import starlette \
  --hidden-import sqlmodel \
  --hidden-import sqlalchemy \
  --hidden-import uvicorn \
  --hidden-import jinja2 \
  --hidden-import cryptography \
  --add-data "alembic:alembic" \
  --add-data "alembic.ini:." \
  --add-data "app:app" \
  --add-data "app/templates:app/templates" \
  --add-data "app/static:app/static" \
  backend_sidecar.py

mkdir -p ../github-sourcer-desktop/src-tauri/bin
cp dist/sourceress-backend ../github-sourcer-desktop/src-tauri/bin/sourceress-backend
```

## 2) Build the desktop app

```bash
cd ../github-sourcer-desktop
npm install
npm run tauri build
```

Artifacts will be in:
`github-sourcer-desktop/src-tauri/target/release/bundle/`

## Run (dev)

Backend:
```bash
cd github-sourcer
source .venv/bin/activate
python -m uvicorn app.main:app --app-dir . --host 127.0.0.1 --port 8000
```

Desktop:
```bash
cd github-sourcer-desktop
npm install
npm run dev
```
