# Sourceress Desktop Beta Release Notes

Version: 0.1.0 (Windows)
Build date: 2026-03-26

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
  - SHA256: `FF95F39FCAE784D25C83188433502ED6126B8FC11433D24DD69DECB6A6101CF9`
- EXE: `Sourceress_0.1.0_x64-setup.exe`
  - SHA256: `3B27A4DE27A60201DA863354443374B196CF5414F774C7BE97847B76E62539F7`

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
