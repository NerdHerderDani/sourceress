# GitHub Sourcer (MVP)

Personal GitHub sourcing tool: boolean-ish search → ranked Go candidates → web UI + CSV export.

## Setup

1) Copy `.env.example` → `.env` and set `GITHUB_TOKEN`.

2) Install deps:

```bash
py -m pip install -r requirements.txt
```

3) Run DB migrations:

```powershell
./scripts/migrate.ps1
```

4) Run the app:

```bash
py -m uvicorn app.main:app --reload --app-dir .
```

Open: http://127.0.0.1:8000/

## Migrations

Create a new migration after changing `app/models.py`:

```powershell
./scripts/makemigration.ps1 -Message "add_xyz"
./scripts/migrate.ps1
```

## Render deploy checklist

### 1) Create Postgres
- Create a Render Postgres instance.
- Copy its **Internal Database URL** into `DATABASE_URL`.

### 2) Create the web service
- Runtime: Python
- Start command:
  - `uvicorn app.main:app --host 0.0.0.0 --port $PORT --app-dir .`
- Build command:
  - `pip install -r requirements.txt && ./scripts/migrate.ps1`
  - If Render can’t run PowerShell in your environment, run Alembic directly instead:
    - `alembic upgrade head`

### 3) Required environment variables
- `DATABASE_URL` (Render sets this automatically for some Postgres setups; otherwise set it)
- `APP_SECRET_KEY` (random long string; used to encrypt per-user GitHub tokens)

### 4) Supabase magic-link auth (recommended for hosted)
- `SUPABASE_URL`
- `SUPABASE_ANON_KEY`
- `SUPABASE_JWT_SECRET` (from Supabase project settings)
- `ALLOWLIST_EMAILS` (comma-separated emails allowed to use the app)

### 5) GitHub token
Two options:
- Global fallback: set `GITHUB_TOKEN` on the server.
- Per-user (preferred): users save their own token in **Settings** (encrypted in DB).

### 6) Verify
- Visit `/login` and sign in via magic link.
- Visit `/settings` and store a GitHub token.
- Run a search.

## Weekend Mode (Anthropic Batch)

Weekend Mode lives at:
- `/weekend/jobs` (UI)

To enable Anthropic Batch processing:
1) Set `ANTHROPIC_API_KEY` in `.env` (or environment).
2) Run migrations (`./scripts/migrate.ps1`) to add batch columns.
3) Create a Weekend job, open it, and click **Submit batch**, then **Poll status**.

Notes:
- We submit one batch request per artifact (prefers extracted files if a ZIP was uploaded).
- Prompt caching is enabled by including `cache_control: {type: 'ephemeral'}` on the system prompt inside the batch payload.
- Results are stored as a `result` artifact (`anthropic_results.jsonl`) under `data/weekend_jobs/<job_id>/results/`.

## Notes
- GitHub search is approximated: we translate boolean-ish query into GitHub tokens.
- MVP uses REST for discovery + GraphQL for enrichment.
- Local dev bypass: if `SUPABASE_JWT_SECRET` is missing OR `ALLOWLIST_EMAILS` is empty, the app will not enforce auth.
