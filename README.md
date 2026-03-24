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

## Claude Desktop Agent Connector (MCP)

Goal: let **Claude Desktop** (local agent) control your local Sourceress instance via tools.

### Architecture (high level)
- Sourceress backend runs locally (typically `http://127.0.0.1:8000`).
- A local **Sourceress Connector** runs an **MCP server** that Claude Desktop connects to.
- The connector forwards MCP tool calls → Sourceress HTTP endpoints.
- Requests are authenticated with a per-user key header:
  - `X-Sourceress-Agent-Key: <random>`

### Autodetect / config
The connector should (by default):
- probe common localhost ports and/or read the desktop sidecar URL if available
- fall back to `http://127.0.0.1:8000`

### Security
- Never expose the agent endpoints on a public interface.
- Always require `X-Sourceress-Agent-Key` for mutation endpoints.

### Planned tooling
We plan to ship a **single-binary** connector for:
- Windows (`SourceressConnector.exe`)
- macOS (`SourceressConnector`)

Expected commands:
- `--install` generates/stores the agent key locally and prints the Claude Desktop config snippet.
- `--start` runs the MCP server.

Example tools:
- `sourceress.add_company`
- `sourceress.set_company_links`
- `sourceress.set_company_tags`
- `sourceress.import_comp_csv`
- `sourceress.benchmark`

## Notes
- Do not commit DBs, build artifacts, or `.env` files.
