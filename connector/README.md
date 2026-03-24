# Sourceress Connector (MCP)

Local MCP server that lets **Claude Desktop** control your local Sourceress instance.

## Quick start

1) Ensure Sourceress is running locally (Desktop app → Start), so backend is reachable at `http://127.0.0.1:8000`.

2) Install (generates per-machine key and sets it in Sourceress):
```powershell
SourceressConnector.exe install
```

3) Configure Claude Desktop MCP server using the snippet printed by `install`.

4) Start MCP server (Claude Desktop launches this automatically once configured):
```powershell
SourceressConnector.exe start
```

## Env vars
- `SOURCERESS_AGENT_KEY` (required for `start`)
- Optional: `--base-url http://127.0.0.1:8000`
- Optional: `--bearer <token>` if auth bypass is disabled

## Tools (initial)
- `sourceress_company_upsert`
- `sourceress_comp_import_csv`

## Notes
- This connector does **not** call any LLM.
- Claude Desktop runs the model; this connector is the tool bridge.
