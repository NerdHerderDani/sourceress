# Sourceress Desktop Beta — Installer Checklist (Windows/macOS)

Goal: "idiot proof" beta installers that run **fully local** (no hosted web app) using the bundled backend sidecar.

## What ships
- Tauri desktop app (UI)
- Bundled backend sidecar `sourceress-backend` (PyInstaller)
- Local SQLite database stored under the OS app-data directory
- Local log file: `backend.log` in the same app-data directory

## Beta constraints / decisions
- **Desktop only** (web app paused)
- **No login / no Supabase dependency** for beta
- Degen mode exists as a UI toggle but is implemented as `preset=degen` in the API
- "Beta" persona toggle is removed; philosophy layer is HR-only substrate

---

## Must-pass smoke tests (before distributing builds)
### App launches
- Installer runs without requiring Python/Node/Rust on the target machine
- Desktop app opens and starts backend automatically
- No extra console window appears (Windows release)

### Backend health
- Backend is reachable at `http://127.0.0.1:<port>/health`
- If backend fails, UI error shows the **log file path**

### Fubuki
- Each mode works:
  - Source / Boolean / Outreach / Screen / Fake
  - HR Helpdesk (loads philosophy substrate + HR layers)
  - AskFubuki SWE (loads SWE KB layer)
- Degen preset works (toggle on/off)

### Data + persistence
- Candidate search run persists across app restart
- Settings (GitHub token) persists

---

## Build pipeline (Windows)
### Prereqs (builder machine)
- Python 3.11+
- Node 18+
- Rust toolchain (Tauri)

### One-command build (recommended)
Use `scripts/build_desktop_release_windows.ps1` (added in repo).

Artifacts:
- `desktop/src-tauri/target/release/bundle/` (MSI/EXE depending on Tauri config)

---

## Build pipeline (macOS)
### Prereqs (builder machine)
- Xcode command line tools
- Rust toolchain
- Node 18+
- Python 3.11+

### Notes
- For real external beta, you will want **codesigning + notarization**.
- Unsigned builds will trigger Gatekeeper warnings.

---

## Common failure modes (and fixes)
- Backend sidecar not found → ensure backend exe is copied to `desktop/src-tauri/bin/` before `tauri build`
- Port conflicts → sidecar picks a free port; UI must wait for readiness (already does)
- Migration failures on fresh installs → sidecar runs Alembic, falls back to SQLModel create_all, then stamps head

---

## Release hygiene
- Include a short "How to report a bug" section:
  - What you did
  - Screenshot
  - Attach `backend.log`
  - Version number
