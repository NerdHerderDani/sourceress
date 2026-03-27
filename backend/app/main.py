from __future__ import annotations

import csv
from io import StringIO
import logging

from fastapi import FastAPI, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, Response, JSONResponse
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi import Query
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

import asyncio
import time

import httpx

from .config import settings
from .db import init_db, get_session
from .services.search_service import create_run, populate_run, get_run_results, get_run_status
from .services.email_service import fetch_email_for_candidate
from .openalex_client import OpenAlexClient
from .training import CandidateFeedback
from .saved_searches import SavedSearch
from .projects import Project, ProjectCandidate
from .project_entity import ProjectEntity
from .models import SearchRun, Candidate
from .company_signals import Company, CompanySignal, upsert_company, norm_company_name
from .comp_bands import CompanyCompBand
from .posted_ranges import CompanyPostedRange
from .gdelt_client import fetch_doc_list
from .wikidata_client import enrich_company_by_name, fetch_company, search_company_qid
from .sec_edgar_client import fetch_company_submissions, norm_cik
from .fubuki_service import fubuki_call, fubuki_call_ex, anthropic_list_models
from .agent_key import agent_key_configured, set_agent_key
from .agent_api import require_agent_key
from .experience import CandidateExperience, parse_linkedin_experience_paste, compute_experience_stats, fmt_months
from .auth import get_bearer_token, verify_supabase_jwt, verify_supabase_token_remote, email_allowed
from .secrets_store import set_github_token, get_github_token

logger = logging.getLogger(__name__)


def _data_dir() -> Path:
    """Return a writable data directory.

    - In dev/CLI runs: ./data
    - In packaged/installer contexts: prefer %APPDATA%\Sourceress\data

    Best-effort: if anything fails, fall back to ./data.
    """
    try:
        import os

        appdata = (os.environ.get('APPDATA') or '').strip()
        if appdata:
            return Path(appdata) / 'Sourceress' / 'data'
    except Exception:
        pass

    return Path('data')


def _append_usage_log(rec: dict) -> None:
    """Append one usage record.

    Primary: DB (UsageEvent) when available.
    Fallback: JSONL under backend/data/.

    Best-effort: never break request handling if logging fails.
    """
    rec = dict(rec or {})

    # Try DB first
    try:
        from .db import get_session
        from .models import UsageEvent

        with get_session() as s:
            ev = UsageEvent(
                owner_email=str(rec.get('owner_email') or ''),
                kind=str(rec.get('kind') or ''),
                mode=str(rec.get('mode') or ''),
                preset=str(rec.get('preset') or ''),
                model_used=str(rec.get('model_used') or ''),
                input_tokens=int(rec.get('input_tokens') or 0),
                output_tokens=int(rec.get('output_tokens') or 0),
                est_cost_usd=float(rec.get('est_cost_usd') or 0.0),
                ok=bool(rec.get('ok', True)),
                error=str(rec.get('error') or ''),
            )
            s.add(ev)
            s.commit()
    except Exception:
        pass

    # Fallback JSONL
    try:
        import json
        import pathlib
        import time

        rec.setdefault('ts', int(time.time()))

        p = _data_dir()
        p.mkdir(parents=True, exist_ok=True)
        out = p / 'fubuki-usage.jsonl'
        out.write_text('', encoding='utf-8') if not out.exists() else None
        with out.open('a', encoding='utf-8') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    except Exception:
        return


async def _read_json_body(request: Request) -> dict:
    """Read JSON body with friendlier errors than FastAPI's default.

    This specifically helps when people test with PowerShell + curl.exe and accidentally
    send malformed JSON (common quoting/escaping issue).
    """
    import json

    raw = await request.body()
    if not raw or not raw.strip():
        raise ValueError('empty request body')

    try:
        return json.loads(raw.decode('utf-8', errors='replace'))
    except json.JSONDecodeError as e:
        raise ValueError(
            f"invalid JSON body: {e}. "
            "If you are using PowerShell, prefer Invoke-RestMethod + ConvertTo-Json, "
            "or ensure curl.exe --data-binary contains valid JSON with double-quotes."
        )

from pathlib import Path

app = FastAPI(title="Sourceress (MVP)")

# Resolve asset paths relative to this file so PyInstaller onefile works.
_APP_DIR = Path(__file__).resolve().parent
_STATIC_DIR = _APP_DIR / "static"
_TEMPLATES_DIR = _APP_DIR / "templates"

app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

# Allow Supabase auth to redirect back and for browser login.
# NOTE: The desktop app is a Tauri WebView; its requests may arrive with these origins.
# If we don't explicitly allow them, the WebView will hit CORS errors.
CORS_ALLOW_ORIGINS = [
    # Tauri/WebView
    "tauri://localhost",
    "http://tauri.localhost",
    "https://tauri.localhost",
    "null",
    # Local dev
    "http://localhost",
    "http://127.0.0.1",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOW_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _get_session_token(req: Request) -> str | None:
    # Prefer cookie, fallback to bearer
    tok = req.cookies.get('sb_access_token')
    if tok:
        return tok
    return get_bearer_token(req)


def _auth_bypass_enabled() -> bool:
    """Whether to bypass auth.

    Only allowed in dev.
    """
    if (settings.env or 'dev') == 'prod':
        return False

    # Local/dev convenience:
    # - if SUPABASE not configured we cannot verify tokens
    # - if ALLOWLIST_EMAILS empty we treat the app as "open" for local use
    allow = [e.strip() for e in (settings.allowlist_emails or '').split(',') if e.strip()]
    if not (settings.supabase_jwt_secret or (settings.supabase_url and settings.supabase_anon_key)):
        return True
    if not allow:
        return True
    return False


# Simple in-memory rate limiter (best-effort; per-instance on Fly)
_RATE: dict[str, list[float]] = {}


def _rate_allow(key: str, limit: int, window_s: int) -> bool:
    import time

    now = time.time()
    lst = _RATE.get(key) or []
    # keep only recent
    cutoff = now - float(window_s)
    lst = [t for t in lst if t >= cutoff]
    ok = len(lst) < int(limit)
    if ok:
        lst.append(now)
    _RATE[key] = lst
    return ok


@app.middleware('http')
async def _auth_mw(request: Request, call_next):
    path = request.url.path

    # Allow unauth routes
    if (
        path.startswith('/static')
        or path in ('/health', '/login', '/auth/callback', '/auth/session', '/auth/logout')
    ):
        return await call_next(request)

    if _auth_bypass_enabled():
        # Dev bypass: treat request as authenticated so per-user features still work.
        request.state.user_email = getattr(request.state, 'user_email', None) or 'dev@local'
        return await call_next(request)

    tok = _get_session_token(request)
    if not tok:
        return RedirectResponse(url='/login', status_code=303)

    claims = verify_supabase_jwt(tok)
    if not claims:
        claims = await verify_supabase_token_remote(tok)
    if not claims:
        return RedirectResponse(url='/login', status_code=303)

    email = (claims.get('email') or '').strip()
    if not email or not email_allowed(email):
        return JSONResponse({'ok': False, 'error': 'not invited'}, status_code=403)

    request.state.user_email = email

    # Rate limiting (only after auth so we can key by user)
    try:
        ip = (request.headers.get('x-forwarded-for') or request.client.host or '').split(',')[0].strip()
    except Exception:
        ip = ''

    if request.url.path.startswith('/agent/'):
        ukey = f"u:{email}:p:{request.url.path}"
        ikey = f"ip:{ip}:p:{request.url.path}"
        # Allow bursts, but cap sustained spam.
        if not _rate_allow(ukey, limit=60, window_s=60):
            return JSONResponse({'ok': False, 'error': 'rate limited (user)'}, status_code=429)
        if ip and not _rate_allow(ikey, limit=200, window_s=60):
            return JSONResponse({'ok': False, 'error': 'rate limited (ip)'}, status_code=429)

    return await call_next(request)

@app.on_event("startup")
def _startup() -> None:
    init_db()

def _wants_html(req: Request) -> bool:
    # Tauri WebView may send */*; browsers often send text/html in Accept.
    # If opened in a normal browser, show a friendly page with a link back.
    a = (req.headers.get('accept') or '').lower()
    ua = (req.headers.get('user-agent') or '').lower()
    if 'text/html' in a:
        return True
    # If someone hits it directly in a webview and gets stuck, still be nice.
    if 'tauri' in ua or 'wv' in ua or 'webview' in ua:
        return True
    return False


def _health_html(title: str, data: dict) -> HTMLResponse:
    import json

    pretty = json.dumps(data, indent=2)
    body = f"""<!doctype html>
<html>
<head>
  <meta charset='utf-8' />
  <meta name='viewport' content='width=device-width, initial-scale=1' />
  <title>{title}</title>
  <style>
    body {{ font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial; margin: 20px; }}
    .row {{ display:flex; gap:12px; align-items:center; flex-wrap:wrap; }}
    a.btn {{ display:inline-block; padding:8px 12px; border:1px solid #ddd; border-radius:10px; text-decoration:none; color:#111; background:#fafafa; }}
    a.btn:hover {{ background:#f2f2f2; }}
    pre {{ background:#0b1020; color:#e7e7e7; padding:12px; border-radius:12px; overflow:auto; }}
    .subtle {{ color:#666; font-size: 13px; }}
  </style>
</head>
<body>
  <div class='row'>
    <a class='btn' href='/agent/fubuki'>Back to Fubuki</a>
    <a class='btn' href='/weekend/jobs'>Weekend Jobs</a>
    <span class='subtle'>You’re looking at a health check endpoint.</span>
  </div>
  <h1 style='margin:14px 0 10px 0;'>{title}</h1>
  <pre>{pretty}</pre>
</body>
</html>"""
    return HTMLResponse(body)


@app.get("/health")
def health(request: Request):
    data = {"ok": True}
    if _wants_html(request):
        return _health_html('Health', data)
    return data


@app.get('/health/full')
def health_full(request: Request):
    """Deeper health check for demo readiness."""
    import os
    from sqlmodel import text

    out = {
        'ok': True,
        'checks': {},
    }

    # DB check
    try:
        with get_session() as s:
            s.exec(text('select 1')).all()
        out['checks']['db'] = {'ok': True}
    except Exception as e:
        out['checks']['db'] = {'ok': False, 'error': str(e)}
        out['ok'] = False

    # Secrets check
    out['checks']['app_secret_key'] = {'ok': bool((settings.app_secret_key or '').strip())}

    # GitHub token check (either per-user stored or global env)
    email = getattr(request.state, 'user_email', '') or ''
    gh = None
    if email:
        try:
            gh = get_github_token(email)
        except Exception:
            gh = None
    out['checks']['github_token'] = {'ok': bool((gh or '').strip() or (settings.github_token or '').strip())}

    # Anthropic key check
    server_key = (os.environ.get('ANTHROPIC_API_KEY') or '').strip()
    out['checks']['anthropic_key'] = {'ok': bool(server_key)}

    # Anthropic models check (best-effort, only if key present)
    if server_key:
        try:
            api_key = server_key
            items = anthropic_list_models(api_key=api_key)
            out['checks']['anthropic_models'] = {'ok': True, 'count': len(items)}
        except Exception as e:
            out['checks']['anthropic_models'] = {'ok': False, 'error': str(e)}
            out['ok'] = False
    else:
        out['checks']['anthropic_models'] = {'ok': False, 'error': 'missing key'}

    if _wants_html(request):
        return _health_html('Health (full)', out)
    return JSONResponse(out)


@app.get("/login", response_class=HTMLResponse)
def login(request: Request):
    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "supabase_url": settings.supabase_url,
            "supabase_anon_key": settings.supabase_anon_key,
            "supabase_configured": bool(settings.supabase_url and settings.supabase_anon_key),
        },
    )


@app.get("/auth/callback", response_class=HTMLResponse)
def auth_callback(request: Request):
    return templates.TemplateResponse(
        "auth_callback.html",
        {
            "request": request,
            "supabase_url": settings.supabase_url,
            "supabase_anon_key": settings.supabase_anon_key,
        },
    )


@app.post("/auth/session")
async def session_create(request: Request):
    data = await request.json()
    token = (data.get('access_token') or '').strip()
    if not token:
        return JSONResponse({'ok': False, 'error': 'missing token'}, status_code=400)

    if _auth_bypass_enabled():
        # In bypass mode we still set the cookie so prod-like flows can be tested.
        resp = JSONResponse({'ok': True, 'bypass': True})
        resp.set_cookie('sb_access_token', token, httponly=True, samesite='lax', secure=(request.url.scheme == 'https'))
        return resp

    claims = verify_supabase_jwt(token)
    if not claims:
        claims = await verify_supabase_token_remote(token)
    if not claims:
        return JSONResponse({'ok': False, 'error': 'invalid token'}, status_code=401)

    email = (claims.get('email') or '').strip()
    if not email or not email_allowed(email):
        return JSONResponse({'ok': False, 'error': 'not invited'}, status_code=403)

    resp = JSONResponse({'ok': True})
    # Session cookie
    resp.set_cookie(
        'sb_access_token',
        token,
        httponly=True,
        samesite='lax',
        secure=(request.url.scheme == 'https'),
    )
    return resp


@app.get('/auth/logout')
def logout() -> RedirectResponse:
    resp = RedirectResponse(url='/login', status_code=303)
    resp.delete_cookie('sb_access_token')
    return resp


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    email = getattr(request.state, 'user_email', '') or ''
    has_token = False
    if email:
        try:
            has_token = bool(get_github_token(email))
        except Exception:
            has_token = False

    allow = [e.strip() for e in (settings.allowlist_emails or '').split(',') if e.strip()]
    return templates.TemplateResponse(
        'settings.html',
        {
            'request': request,
            'has_token': has_token,
            'allowlist_enabled': bool(allow),
            'jwt_enabled': bool(settings.supabase_jwt_secret),
        },
    )


@app.post('/settings/github-token')
def settings_token(request: Request, token: str = Form("")):
    email = getattr(request.state, 'user_email', '')
    if not email:
        return JSONResponse({'ok': False, 'error': 'not logged in'}, status_code=401)
    tok = (token or '').strip()
    if not tok:
        return JSONResponse({'ok': False, 'error': 'missing token'}, status_code=400)
    try:
        set_github_token(email, tok)
    except Exception as e:
        return JSONResponse({'ok': False, 'error': str(e)}, status_code=400)
    return RedirectResponse(url='/settings', status_code=303)


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    defaults = {
        "query": "grpc AND kubernetes NOT blockchain",
        "location": settings.default_location,
        "min_followers": settings.default_min_followers,
        "active_days": settings.default_active_days,
        "min_contribs": 0,
        "max_contribs": 0,
    }
    return templates.TemplateResponse("index.html", {"request": request, "defaults": defaults})

@app.get("/stack", response_class=HTMLResponse)
def stack_index(request: Request):
    return templates.TemplateResponse("stack_index.html", {"request": request})


@app.get('/usage', response_class=HTMLResponse)
def usage_page(request: Request):
    return templates.TemplateResponse('usage.html', {'request': request})


# ─────────────────────────────────────────────────────────────
# Prices (CoinGecko)
# ─────────────────────────────────────────────────────────────
_PRICE_CACHE: dict = {"ts": 0.0, "data": None}


async def _fetch_top_prices(per_page: int = 25) -> list[dict]:
    url = "https://api.coingecko.com/api/v3/coins/markets"
    params = {
        "vs_currency": "usd",
        "order": "market_cap_desc",
        "per_page": int(per_page),
        "page": 1,
        "sparkline": "true",
        "price_change_percentage": "24h",
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(url, params=params, headers={"Accept": "application/json"})
        r.raise_for_status()
        data = r.json() if r.content else []

    # CoinGecko returns list of dicts; keep as-is (frontend expects these keys).
    return data if isinstance(data, list) else []


@app.get('/prices', response_class=HTMLResponse)
def prices_page(request: Request):
    return templates.TemplateResponse('prices.html', {'request': request})


@app.get('/prices.json')
async def prices_json():
    # Cache for 30s to avoid rate limits.
    now = time.time()
    if _PRICE_CACHE.get('data') is not None and (now - float(_PRICE_CACHE.get('ts') or 0)) < 30:
        return JSONResponse({'ok': True, 'items': _PRICE_CACHE['data'], 'fetched_at': _PRICE_CACHE.get('fetched_at')})

    try:
        items = await _fetch_top_prices(per_page=25)
        fetched_at = __import__('datetime').datetime.utcnow().strftime('%H:%M:%SZ')
        _PRICE_CACHE['ts'] = now
        _PRICE_CACHE['data'] = items
        _PRICE_CACHE['fetched_at'] = fetched_at
        return JSONResponse({'ok': True, 'items': items, 'fetched_at': fetched_at})
    except Exception as e:
        return JSONResponse({'ok': False, 'error': str(e)}, status_code=500)


# Price chart data for a single coin id (CoinGecko).
_PRICE_CHART_CACHE: dict[tuple[str, int], dict] = {}


# ─────────────────────────────────────────────────────────────
# Derivatives telemetry (Binance Futures public endpoints)
# ─────────────────────────────────────────────────────────────
_DERIVS_CACHE: dict[tuple[str, str], dict] = {}


def _binance_symbol(sym: str) -> str:
    s = (sym or '').strip().upper()
    if s in ('BTC', 'ETH', 'AVAX'):
        return f"{s}USDT"
    # allow already-formed symbols
    return s


async def _binance_get(path: str, params: dict | None = None) -> dict | list:
    url = f"https://fapi.binance.com{path}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(url, params=params or {}, headers={"Accept": "application/json"})
        r.raise_for_status()
        return r.json() if r.content else {}


@app.get('/derivs/funding.json')
async def derivs_funding(symbol: str = Query(default='BTC')):
    sym = _binance_symbol(symbol)
    key = ('funding', sym)
    now = time.time()
    cached = _DERIVS_CACHE.get(key)
    if cached and (now - float(cached.get('ts') or 0)) < 15:
        return JSONResponse({'ok': True, 'symbol': sym, **(cached.get('data') or {}), 'cached': True})

    try:
        # /fapi/v1/premiumIndex includes mark price + lastFundingRate + nextFundingTime
        data = await _binance_get('/fapi/v1/premiumIndex', params={'symbol': sym})
        out = {
            'markPrice': data.get('markPrice'),
            'lastFundingRate': data.get('lastFundingRate'),
            'nextFundingTime': data.get('nextFundingTime'),
            'time': data.get('time'),
        } if isinstance(data, dict) else {}

        _DERIVS_CACHE[key] = {'ts': now, 'data': out}
        return JSONResponse({'ok': True, 'symbol': sym, **out, 'cached': False})
    except Exception as e:
        return JSONResponse({'ok': False, 'error': str(e)}, status_code=500)


@app.get('/derivs/oi.json')
async def derivs_open_interest(symbol: str = Query(default='BTC')):
    sym = _binance_symbol(symbol)
    key = ('oi', sym)
    now = time.time()
    cached = _DERIVS_CACHE.get(key)
    if cached and (now - float(cached.get('ts') or 0)) < 15:
        return JSONResponse({'ok': True, 'symbol': sym, **(cached.get('data') or {}), 'cached': True})

    try:
        data = await _binance_get('/fapi/v1/openInterest', params={'symbol': sym})
        out = {
            'openInterest': data.get('openInterest'),
            'time': data.get('time'),
        } if isinstance(data, dict) else {}

        _DERIVS_CACHE[key] = {'ts': now, 'data': out}
        return JSONResponse({'ok': True, 'symbol': sym, **out, 'cached': False})
    except Exception as e:
        return JSONResponse({'ok': False, 'error': str(e)}, status_code=500)


@app.get('/prices/{coin_id}.json')
async def price_chart_json(coin_id: str, days: int = Query(default=7)):
    cid = (coin_id or '').strip()
    d = int(days or 7)
    if d not in (1, 7, 30, 90, 365):
        d = 7

    key = (cid, d)
    now = time.time()
    cached = _PRICE_CHART_CACHE.get(key)
    if cached and (now - float(cached.get('ts') or 0)) < 60:
        return JSONResponse({'ok': True, 'coin_id': cid, 'days': d, 'series': cached.get('series') or [], 'fetched_at': cached.get('fetched_at')})

    try:
        url = f"https://api.coingecko.com/api/v3/coins/{cid}/market_chart"
        params = {"vs_currency": "usd", "days": d}
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(url, params=params, headers={"Accept": "application/json"})
            r.raise_for_status()
            data = r.json() if r.content else {}

        prices = data.get('prices') if isinstance(data, dict) else []
        series = []
        if isinstance(prices, list):
            for pt in prices:
                if isinstance(pt, list) and len(pt) >= 2:
                    ts, px = pt[0], pt[1]
                    series.append({'t': ts, 'p': px})

        fetched_at = __import__('datetime').datetime.utcnow().strftime('%H:%M:%SZ')
        _PRICE_CHART_CACHE[key] = {'ts': now, 'series': series, 'fetched_at': fetched_at}
        return JSONResponse({'ok': True, 'coin_id': cid, 'days': d, 'series': series, 'fetched_at': fetched_at})
    except Exception as e:
        return JSONResponse({'ok': False, 'error': str(e)}, status_code=500)


@app.get('/openalex', response_class=HTMLResponse)
def openalex_index(request: Request):
    return templates.TemplateResponse('openalex.html', {'request': request})


@app.get('/agent/fubuki', response_class=HTMLResponse)
def fubuki_ui(request: Request):
    return templates.TemplateResponse('fubuki.html', {'request': request})


# ─────────────────────────────────────────────────────────────
# Job Board (Ashby public API)
# ─────────────────────────────────────────────────────────────
@app.get('/job-board', response_class=HTMLResponse)
def job_board_ui(request: Request):
    return templates.TemplateResponse(
        'job_board.html',
        {
            'request': request,
            'include_compensation': bool(getattr(settings, 'ashby_include_compensation', False)),
        },
    )


@app.get('/api/ashby/job-board')
async def ashby_job_board(includeCompensation: bool = Query(default=False)):
    board = (getattr(settings, 'ashby_job_board_name', '') or 'ava-labs').strip() or 'ava-labs'

    url = f"https://api.ashbyhq.com/posting-api/job-board/{board}"
    params = {'includeCompensation': 'true' if includeCompensation else 'false'}

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(url, params=params, headers={'Accept': 'application/json'})
            r.raise_for_status()
            data = r.json() if r.content else {}
        if not isinstance(data, dict):
            return JSONResponse({'ok': False, 'error': 'unexpected response from Ashby'}, status_code=502)
        # Pass through important fields; keep frontend stable.
        return JSONResponse({'ok': True, 'boardName': board, **data})
    except Exception as e:
        return JSONResponse({'ok': False, 'error': str(e)}, status_code=500)


@app.get('/command', response_class=HTMLResponse)
def command_center(request: Request):
    """Demo hub.

    MVP benchmarking: compare other companies' comp bands to Ava Labs baseline.
    Supports department/category filtering (engineering/product/...).
    """
    from sqlmodel import select

    dept = (request.query_params.get('dept') or 'engineering').strip().lower()
    dept_opts = [
        ('engineering', 'Engineering'),
        ('product', 'Product'),
        ('data', 'Data'),
        ('design', 'Design'),
        ('marketing', 'Marketing'),
        ('sales', 'Sales'),
        ('other', 'Other'),
        ('all', 'All'),
    ]
    if dept not in {k for k, _ in dept_opts}:
        dept = 'engineering'

    def family(role: str) -> str:
        # Within any dept, we still break down into these families for display.
        r = (role or '').lower()
        if 'product' in r or r.startswith('pm'):
            return 'PM'
        if 'data' in r or 'scientist' in r or 'ml' in r:
            return 'DS'
        if 'engineer' in r or 'developer' in r or 'software' in r:
            return 'SWE'
        return 'Other'

    def med(vals: list[int]) -> int:
        vals = sorted([int(v) for v in vals if v is not None and int(v) > 0])
        if not vals:
            return 0
        n = len(vals)
        m = n // 2
        if n % 2 == 1:
            return vals[m]
        return int((vals[m-1] + vals[m]) / 2)

    with get_session() as s:
        companies = s.exec(select(Company).order_by(Company.name.asc())).all()
        if dept == 'all':
            comp_rows = s.exec(select(CompanyCompBand)).all()
        else:
            comp_rows = s.exec(select(CompanyCompBand).where(CompanyCompBand.dept == dept)).all()

    # baseline: first company with 'ava' in name
    baseline = None
    for c in companies:
        if 'ava' in (c.norm_name or ''):
            baseline = c
            break

    # aggregates per company per family
    by_co: dict[int, dict[str, dict[str, int]]] = {}
    counts: dict[int, int] = {}
    for r in comp_rows:
        fid = family(r.role)
        d = by_co.setdefault(r.company_id, {}).setdefault(fid, {'low': 0, 'mid': 0, 'high': 0, 'bonus': 0, 'equity': 0, 'n': 0})
        # store lists via temp fields
        for k, v in [('low', r.low), ('mid', r.mid), ('high', r.high), ('bonus', getattr(r, 'bonus', 0)), ('equity', getattr(r, 'equity', 0))]:
            if v and int(v) > 0:
                d.setdefault('_' + k, []).append(int(v))
        d['n'] += 1
        counts[r.company_id] = counts.get(r.company_id, 0) + 1

    # finalize medians
    for cid, fams in by_co.items():
        for fid, d in fams.items():
            for k in ('low', 'mid', 'high', 'bonus', 'equity'):
                d[k] = med(d.get('_' + k, []))
                if '_' + k in d:
                    del d['_' + k]

    base_aggs = by_co.get(baseline.id, {}) if baseline else {}

    table = []
    for c in companies:
        if counts.get(c.id, 0) <= 0:
            continue
        if baseline and c.id == baseline.id:
            # Don't benchmark Ava against itself
            continue
        row = {
            'id': c.id,
            'name': c.name,
            'jobs_url': c.jobs_url,
            'github_org_url': c.github_org_url,
            'linkedin_company_url': c.linkedin_company_url,
            'aggs': by_co.get(c.id, {}),
            'deltas': {},
        }
        # delta vs baseline for each family
        for fid in ('SWE', 'PM', 'DS'):
            a = row['aggs'].get(fid, {})
            b = base_aggs.get(fid, {})
            if not a or not b:
                continue
            dm = (a.get('mid', 0) or 0) - (b.get('mid', 0) or 0)
            pct = None
            flag = ''
            if b.get('mid', 0) and a.get('mid', 0):
                ratio = a['mid'] / b['mid']
                pct = int(round((ratio - 1.0) * 100))
                if ratio < 0.85:
                    flag = 'UNDER_AVA'
                elif ratio > 1.15:
                    flag = 'OVER_AVA'
            row['deltas'][fid] = {'mid_delta': dm, 'pct': pct, 'flag': flag}
        table.append(row)

    return templates.TemplateResponse('command.html', {
        'request': request,
        'baseline': baseline,
        'table': table,
        'dept': dept,
        'dept_opts': dept_opts,
    })


@app.get('/companies', response_class=HTMLResponse)
def companies_index(request: Request, msg: str = Query(default='')):
    from sqlmodel import select

    with get_session() as s:
        companies = s.exec(select(Company).order_by(Company.updated_at.desc())).all()
        cands = s.exec(select(Candidate).where(Candidate.company != '')).all()

    # Candidate counts by normalized company string
    counts: dict[str, int] = {}
    for cand in cands:
        nn = norm_company_name(cand.company or '')
        if not nn:
            continue
        counts[nn] = counts.get(nn, 0) + 1

    rows = []
    for c in companies:
        rows.append({
            'id': c.id,
            'name': c.name,
            'origin': c.origin,
            'industry_tags': c.industry_tags or [],
            'candidate_count': counts.get(c.norm_name or '', 0),
        })

    return templates.TemplateResponse('companies.html', {'request': request, 'companies': rows, 'msg': msg})


@app.post('/companies/add')
def companies_add(name: str = Form('')):
    nm = (name or '').strip()
    if not nm:
        return RedirectResponse(url='/companies?msg=Missing+company+name', status_code=303)

    with get_session() as s:
        c = upsert_company(s, nm, origin='manual')

    if not c:
        return RedirectResponse(url='/companies?msg=Invalid+company+name', status_code=303)

    return RedirectResponse(url=f'/companies/{c.id}', status_code=303)


@app.get('/companies/export.json')
def companies_export(include_signals: int = Query(default=0)):
    """Export talent mapping data (companies + comp bands + optional signals) as a JSON download."""
    from sqlmodel import select
    import json
    import datetime

    inc = bool(int(include_signals or 0))

    with get_session() as s:
        companies = s.exec(select(Company)).all()
        comp_rows = s.exec(select(CompanyCompBand)).all()
        sig_rows = s.exec(select(CompanySignal)).all() if inc else []

    payload = {
        'schema_version': 1,
        'exported_at': datetime.datetime.utcnow().isoformat() + 'Z',
        'include_signals': inc,
        'companies': [jsonable_encoder(c) for c in companies],
        'comp_bands': [jsonable_encoder(r) for r in comp_rows],
        'signals': [jsonable_encoder(r) for r in sig_rows] if inc else [],
    }

    data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    fname = f"talent-mapping-export-{datetime.datetime.utcnow().date().isoformat()}.json"
    return Response(
        content=data,
        media_type='application/json',
        headers={'Content-Disposition': f'attachment; filename="{fname}"'},
    )


@app.post('/companies/import')
async def companies_import(
    request: Request,
    file: UploadFile = File(...),
    mode: str = Form('merge'),
    include_signals: int = Form(0),
):
    """Import talent mapping data from an export pack.

    mode:
      - merge: add missing records, keep existing
      - replace: wipe companies/comp bands/(signals) then import
    """
    from sqlmodel import select
    import json

    md = (mode or 'merge').strip().lower()
    if md not in ('merge', 'replace'):
        md = 'merge'

    inc = bool(int(include_signals or 0))

    raw = await file.read()
    if not raw:
        return RedirectResponse(url='/companies?msg=Empty+file', status_code=303)

    try:
        pack = json.loads(raw.decode('utf-8', errors='replace'))
    except Exception as e:
        return RedirectResponse(url='/companies?msg=Invalid+JSON', status_code=303)

    companies_in = pack.get('companies') or []
    comp_in = pack.get('comp_bands') or []
    sig_in = pack.get('signals') or []

    if not isinstance(companies_in, list) or not isinstance(comp_in, list):
        return RedirectResponse(url='/companies?msg=Invalid+pack+format', status_code=303)

    added_companies = 0
    added_bands = 0
    added_signals = 0

    with get_session() as s:
        if md == 'replace':
            # Wipe mapping tables. (Candidates remain; they are not FK-linked.)
            for r in s.exec(select(CompanyCompBand)).all():
                s.delete(r)
            if inc:
                for r in s.exec(select(CompanySignal)).all():
                    s.delete(r)
            for c in s.exec(select(Company)).all():
                s.delete(c)
            s.commit()

        # Build lookup of existing companies by norm_name
        existing_cos = {c.norm_name: c for c in s.exec(select(Company)).all() if (c.norm_name or '').strip()}

        # Upsert companies
        id_map: dict[int, int] = {}  # old_id -> new_id
        for c in companies_in:
            if not isinstance(c, dict):
                continue
            name = (c.get('name') or '').strip()
            if not name:
                continue
            origin = (c.get('origin') or 'manual').strip() or 'manual'
            obj = upsert_company(s, name, origin=origin)
            if not obj:
                continue

            # Copy enrichment fields (best-effort)
            for k in ('wikidata_id', 'sec_cik', 'github_org_url', 'linkedin_company_url', 'jobs_url', 'tags', 'notes'):
                if isinstance(c.get(k), str):
                    setattr(obj, k, c.get(k) or '')
            if isinstance(c.get('industry_tags'), list):
                obj.industry_tags = [str(x) for x in c.get('industry_tags') if str(x).strip()]
            if isinstance(c.get('domains'), list):
                obj.domains = [str(x) for x in c.get('domains') if str(x).strip()]
            if isinstance(c.get('comp_json'), dict):
                obj.comp_json = c.get('comp_json') or {}

            s.add(obj)
            s.commit()

            old_id = c.get('id')
            if isinstance(old_id, int):
                id_map[old_id] = obj.id

            if obj.norm_name not in existing_cos:
                existing_cos[obj.norm_name] = obj
                added_companies += 1

        # Existing comp band keys
        existing_keys: set[tuple] = set()
        for r in s.exec(select(CompanyCompBand)).all():
            existing_keys.add((
                int(r.company_id),
                (r.dept or ''),
                (r.role or ''),
                (r.level or ''),
                (r.location or ''),
                (r.currency or ''),
                int(r.low or 0),
                int(r.mid or 0),
                int(r.high or 0),
                int(getattr(r, 'bonus', 0) or 0),
                int(getattr(r, 'equity', 0) or 0),
                (getattr(r, 'source_url', '') or ''),
            ))

        # Import comp bands
        for r in comp_in:
            if not isinstance(r, dict):
                continue
            old_cid = r.get('company_id')
            cid = None
            if isinstance(old_cid, int) and old_cid in id_map:
                cid = id_map[old_cid]
            if not cid:
                # fallback: try find by company name fields if present
                continue

            row = CompanyCompBand(
                company_id=int(cid),
                dept=(r.get('dept') or 'engineering').strip() or 'engineering',
                role=(r.get('role') or '').strip(),
                level=(r.get('level') or '').strip(),
                location=(r.get('location') or '').strip(),
                currency=(r.get('currency') or 'USD').strip() or 'USD',
                low=int(r.get('low') or 0),
                mid=int(r.get('mid') or 0),
                high=int(r.get('high') or 0),
                bonus=int(r.get('bonus') or 0),
                equity=int(r.get('equity') or 0),
                source_url=(r.get('source_url') or '').strip(),
                notes=(r.get('notes') or '').strip(),
            )
            key = (
                row.company_id, row.dept, row.role, row.level, row.location, row.currency,
                row.low, row.mid, row.high, row.bonus, row.equity, row.source_url,
            )
            if key in existing_keys:
                continue
            s.add(row)
            s.commit()
            existing_keys.add(key)
            added_bands += 1

        # Import signals (optional)
        if inc and isinstance(sig_in, list):
            # Dedup signals by (company_id, signal_type, url)
            existing_sig = set()
            for rr in s.exec(select(CompanySignal)).all():
                existing_sig.add((int(rr.company_id), (rr.signal_type or ''), (rr.url or '')))

            for rr in sig_in:
                if not isinstance(rr, dict):
                    continue
                old_cid = rr.get('company_id')
                cid = id_map.get(old_cid) if isinstance(old_cid, int) else None
                if not cid:
                    continue
                sig = CompanySignal(
                    company_id=int(cid),
                    source=(rr.get('source') or 'manual') or 'manual',
                    signal_type=(rr.get('signal_type') or '').strip(),
                    value_json=rr.get('value_json') or {},
                    url=(rr.get('url') or '').strip(),
                )
                sk = (sig.company_id, sig.signal_type, sig.url)
                if sk in existing_sig:
                    continue
                s.add(sig)
                s.commit()
                existing_sig.add(sk)
                added_signals += 1

    msg = f"Imported: {added_companies} companies, {added_bands} comp bands" + (f", {added_signals} signals" if inc else "")
    return RedirectResponse(url='/companies?msg=' + __import__('urllib.parse').parse.quote(msg), status_code=303)


@app.post('/companies/{company_id:int}/delete')
def company_delete(company_id: int):
    """Delete a company record.

    NOTE: This does NOT delete Candidate rows; it only removes the watchlist company.
    Signals are deleted as well.
    """
    from sqlmodel import select

    with get_session() as s:
        c = s.get(Company, company_id)
        if not c:
            return RedirectResponse(url='/companies?msg=Company+not+found', status_code=303)

        # delete signals
        sigs = s.exec(select(CompanySignal).where(CompanySignal.company_id == company_id)).all()
        for r in sigs:
            s.delete(r)

        s.delete(c)
        s.commit()

    return RedirectResponse(url='/companies?msg=Deleted', status_code=303)


@app.get('/companies/{company_id:int}', response_class=HTMLResponse)
def company_detail(request: Request, company_id: int):
    from sqlmodel import select

    with get_session() as s:
        c = s.get(Company, company_id)
        if not c:
            return HTMLResponse('company not found', status_code=404)

        # Load latest cached signals (if any)
        sigs = s.exec(
            select(CompanySignal)
            .where(CompanySignal.company_id == company_id)
            .order_by(CompanySignal.created_at.desc())
        ).all()

    q = c.name
    google_url = f"https://www.google.com/search?q={q}"
    layoffs_url = f"https://layoffs.fyi/?query={q}"
    levels_url = f"https://www.levels.fyi/companies/?search={q}"
    crunch_url = f"https://www.crunchbase.com/textsearch?q={q}"

    # Comp bands (table)
    comp_rows = []
    try:
        from sqlmodel import select
        with get_session() as s:
            rows = s.exec(
                select(CompanyCompBand)
                .where(CompanyCompBand.company_id == company_id)
                .order_by(CompanyCompBand.role.asc(), CompanyCompBand.level.asc(), CompanyCompBand.location.asc(), CompanyCompBand.created_at.desc())
            ).all()
        for r in rows:
            comp_rows.append({
                'id': r.id,
                'role': r.role,
                'level': r.level,
                'location': r.location,
                'currency': r.currency,
                'low': r.low,
                'mid': r.mid,
                'high': r.high,
                'bonus': getattr(r, 'bonus', 0) or 0,
                'equity': getattr(r, 'equity', 0) or 0,
                'source_url': r.source_url,
                'notes': r.notes,
            })
    except Exception:
        comp_rows = []

    # Extract latest by type
    layoffs = {'count': 0, 'articles': [], 'query': ''}
    funding = {'count': 0, 'articles': [], 'query': ''}
    for s in sigs:
        if s.signal_type == 'layoffs' and not layoffs.get('query'):
            v = s.value_json or {}
            layoffs = {
                'count': v.get('count', 0) or 0,
                'articles': v.get('articles', []) or [],
                'query': v.get('query', '') or '',
            }
        if s.signal_type == 'funding' and not funding.get('query'):
            v = s.value_json or {}
            funding = {
                'count': v.get('count', 0) or 0,
                'articles': v.get('articles', []) or [],
                'query': v.get('query', '') or '',
            }

    # Aggregate (MVP): aggregate all rows with role containing 'engineer' as default headline
    agg = {}
    try:
        # prefer SWE-ish rows; fallback to all rows
        swe_rows = [r for r in comp_rows if isinstance(r.get('role'), str) and ('engineer' in r.get('role').lower())]
        rows_for_agg = swe_rows if swe_rows else comp_rows

        def _median(vals: list[int]) -> int:
            vals = sorted([int(v) for v in vals if v is not None])
            if not vals:
                return 0
            n = len(vals)
            mid = n // 2
            if n % 2 == 1:
                return vals[mid]
            return int((vals[mid - 1] + vals[mid]) / 2)

        lows = [r.get('low') or 0 for r in rows_for_agg if (r.get('low') or 0) > 0]
        mids = [r.get('mid') or 0 for r in rows_for_agg if (r.get('mid') or 0) > 0]
        highs = [r.get('high') or 0 for r in rows_for_agg if (r.get('high') or 0) > 0]
        cur = ''
        for r in rows_for_agg:
            if (r.get('currency') or '').strip():
                cur = (r.get('currency') or '').strip()
                break
        if lows or mids or highs:
            agg = {
                'role': 'SWE (aggregate)' if swe_rows else 'Aggregate',
                'currency': cur or 'USD',
                'low': _median(lows) if lows else 0,
                'mid': _median(mids) if mids else 0,
                'high': _median(highs) if highs else 0,
                'n': len(rows_for_agg),
            }
    except Exception:
        agg = {}

    return templates.TemplateResponse('company_detail.html', {
        'request': request,
        'c': c,
        'google_url': google_url,
        'layoffs_url': layoffs_url,
        'levels_url': levels_url,
        'crunch_url': crunch_url,
        'comp_rows': comp_rows,
        'agg': agg,
        'layoffs': layoffs,
        'funding': funding,
    })


@app.post('/companies/{company_id:int}/comp')
def company_set_comp(company_id: int, role: str = Form(''), low: str = Form(''), mid: str = Form(''), high: str = Form(''), notes: str = Form('')):
    # Legacy endpoint (kept for compatibility). Prefer /comp/add + table.
    return RedirectResponse(url=f'/companies/{company_id}', status_code=303)


@app.get('/agent/key/status')
def agent_key_status(request: Request):
    # Protected by standard auth middleware.
    return JSONResponse({'ok': True, 'configured': agent_key_configured()})


@app.post('/agent/key/set')
async def agent_key_set(request: Request):
    # Protected by standard auth middleware.
    data = await request.json()
    key = (data.get('key') or '').strip()
    if not key:
        return JSONResponse({'ok': False, 'error': 'missing key'}, status_code=400)
    try:
        set_agent_key(key)
    except Exception as e:
        return JSONResponse({'ok': False, 'error': str(e)}, status_code=400)
    return JSONResponse({'ok': True})


@app.get('/agent/fubuki/modes')
def fubuki_modes():
    # Source of truth is the embedded UI's MODES; backend expects these keys.
    # We also expose file-backed modes (HR Helpline / AskFubuki SWE).
    return {
        'source':  {'label': 'SOURCE & EVALUATE',     'desc': "Paste a profile, GitHub URL, or describe who you're hunting"},
        'boolean': {'label': 'BOOLEAN / SEARCH',      'desc': 'Describe the role — returns search strings'},
        'outreach':{'label': 'OUTREACH WRITER',       'desc': 'Describe the candidate and role — returns full sequence'},
        'screen':  {'label': 'SCREEN CANDIDATE',      'desc': 'Specify the role — returns question bank'},
        'fake':    {'label': 'FAKE PROFILE DETECT',   'desc': 'Paste profile text — returns authenticity score + threat check'},

        'hr':         {'label': 'HR HELPDESK',     'desc': 'HR Helpdesk (employment law + visas + CHRO guidance) with the Beta philosophy substrate'},
        'askfubuki':  {'label': 'ASKFUBUKI',       'desc': 'Staff+ SWE expert for Avalanche/EVM; recruiter-friendly explanations + deep tech'},
    }


@app.post('/agent/company/upsert')
async def agent_company_upsert_route(request: Request):
    # Requires standard auth + agent key.
    deny = require_agent_key(request)
    if deny:
        return deny

    data = await request.json()
    from .agent_tools import agent_company_upsert
    c, err = agent_company_upsert(data)
    if err:
        return JSONResponse({'ok': False, 'error': err}, status_code=400)

    return JSONResponse({'ok': True, 'company': {'id': c.id, 'name': c.name}})


@app.post('/agent/company/comp/import_csv')
async def agent_comp_import_csv_route(request: Request):
    deny = require_agent_key(request)
    if deny:
        return deny

    data = await request.json()
    from .agent_tools import agent_comp_import_csv
    added, err = agent_comp_import_csv(data)
    if err:
        return JSONResponse({'ok': False, 'error': err}, status_code=400)

    return JSONResponse({'ok': True, 'added': added})


@app.post('/agent/fubuki/dm')
async def fubuki_dm_route(request: Request):
    # Protected by standard auth middleware (same as other endpoints).
    try:
        data = await _read_json_body(request)
    except Exception as e:
        logger.warning('fubuki dm: bad JSON body (%s)', e)
        return JSONResponse({'ok': False, 'error': str(e)}, status_code=400)

    # Prefer server key when present (personal default). Allow per-user header only as fallback.
    import os
    server_key = (os.environ.get('ANTHROPIC_API_KEY') or '').strip()
    api_key = server_key or (request.headers.get('x-anthropic-key') or '').strip() or None

    from .agent_fubuki import fubuki_dm
    # fubuki_dm calls fubuki_call; thread api_key through by temporarily stashing on payload.
    # (Keeps agent_fubuki.py signature stable.)
    if api_key:
        data['_anthropic_api_key'] = api_key
    resp, err = fubuki_dm(data)

    # Best-effort usage logging (if available)
    meta = data.get('_usage_meta') if isinstance(data, dict) else None
    if isinstance(meta, dict):
        _append_usage_log({
            'kind': 'dm',
            'owner_email': getattr(request.state, 'user_email', '') or '',
            'model_used': meta.get('model_used') or '',
            'input_tokens': meta.get('input_tokens'),
            'output_tokens': meta.get('output_tokens'),
        })

    if err:
        return JSONResponse({'ok': False, 'error': err}, status_code=400)
    return JSONResponse({'ok': True, 'response': resp or ''})


def _extract_degen_system_prompt() -> str:
    """Extract const DEGEN_SYSTEM_PROMPT = `...`; from app/static/sourceress.html."""
    p = _STATIC_DIR / 'sourceress.html'
    s = p.read_text(encoding='utf-8', errors='ignore')

    token = 'const DEGEN_SYSTEM_PROMPT'
    start = s.find(token)
    if start < 0:
        raise RuntimeError('DEGEN_SYSTEM_PROMPT not found in sourceress.html')

    eq = s.find('=', start)
    if eq < 0:
        raise RuntimeError('DEGEN_SYSTEM_PROMPT assignment not found')

    i = s.find('`', eq)
    if i < 0:
        raise RuntimeError('DEGEN_SYSTEM_PROMPT opening backtick not found')

    # scan template literal
    i += 1
    j = i
    while j < len(s):
        c = s[j]
        if c == '\\':
            j += 2
            continue
        if c == '`':
            return s[i:j]
        j += 1

    raise RuntimeError('unterminated DEGEN_SYSTEM_PROMPT template literal')


def _extract_fubuki_system_prompts() -> dict[str, str]:
    """Extract system prompts from app/static/sourceress.html.

    The UI owns the prompt text in JS:
      const MODES = { source: { ..., system: `...` }, ... };

    These template literals are *huge* (thousands of chars) and may contain braces/newlines,
    so regex-only parsing is fragile. We do a small, purpose-built scanner:
    - locate the MODES object
    - brace-match to get its full text
    - for each mode, find "system: `" then parse a JS template literal until the closing backtick
      (handling escaped \`)
    """

    MODES_START = 'const MODES'

    p = _STATIC_DIR / 'sourceress.html'
    s = p.read_text(encoding='utf-8', errors='ignore')

    start = s.find(MODES_START)
    if start < 0:
        raise RuntimeError('const MODES not found in sourceress.html')

    # Find the opening '{' of the MODES object (after the '=')
    eq = s.find('=', start)
    if eq < 0:
        raise RuntimeError('MODES assignment not found')
    i = eq
    while i < len(s) and s[i] != '{':
        i += 1
    if i >= len(s) or s[i] != '{':
        raise RuntimeError('MODES object opening { not found')

    # Brace-match the MODES object, while skipping over quoted strings and template literals.
    def _scan_string(pos: int, quote: str) -> int:
        pos += 1
        while pos < len(s):
            c = s[pos]
            if c == '\\':
                pos += 2
                continue
            if c == quote:
                return pos + 1
            pos += 1
        raise RuntimeError('unterminated string literal in sourceress.html')

    def _scan_template(pos: int) -> int:
        # s[pos] == '`'
        pos += 1
        while pos < len(s):
            c = s[pos]
            if c == '\\':
                pos += 2
                continue
            if c == '`':
                return pos + 1
            pos += 1
        raise RuntimeError('unterminated template literal in sourceress.html')

    depth = 0
    j = i
    while j < len(s):
        c = s[j]
        if c in ('"', "'"):
            j = _scan_string(j, c)
            continue
        if c == '`':
            j = _scan_template(j)
            continue
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                # include closing brace
                j += 1
                break
        j += 1

    if depth != 0:
        raise RuntimeError('failed to parse MODES object (brace mismatch)')

    block = s[i:j]

    def _find_mode_key(from_pos: int, mode: str) -> int:
        """Find the position of the mode key inside the MODES object.

        We avoid naive .find(mode) because mode words can appear inside the prompt text.
        We look for patterns like:
          \n  source: {
          {source: {
        """
        patterns = [f"\n{mode}", f"\n {mode}", f"\n  {mode}", f"{{{mode}", f"{{ {mode}"]
        pos = from_pos
        while True:
            hit = -1
            for pat in patterns:
                h = block.find(pat, pos)
                if h >= 0 and (hit < 0 or h < hit):
                    hit = h
            if hit < 0:
                return -1

            # Normalize to start of the mode token
            if block[hit] == '{':
                k = hit + 1
                while k < len(block) and block[k] == ' ':
                    k += 1
            else:
                k = hit + 1  # skip leading '\n'
                while k < len(block) and block[k] == ' ':
                    k += 1

            if not block.startswith(mode, k):
                pos = hit + 1
                continue

            t = k + len(mode)
            # Skip whitespace then require ':'
            while t < len(block) and block[t] in (' ', '\t', '\r'):
                t += 1
            if t < len(block) and block[t] == ':':
                return k

            pos = hit + 1

    def _extract_mode_system_between(start_k: int, end_k: int, mode: str) -> str:
        seg = block[start_k:end_k]
        sys_key = 'system:'
        sys_pos = seg.find(sys_key)
        if sys_pos < 0:
            raise RuntimeError(f'system key not found for mode={mode}')
        bt = seg.find('`', sys_pos)
        if bt < 0:
            raise RuntimeError(f'opening backtick not found for mode={mode}')
        # Scan to closing backtick, respecting escapes
        pos = bt + 1
        while pos < len(seg):
            c = seg[pos]
            if c == '\\':
                pos += 2
                continue
            if c == '`':
                return seg[bt + 1:pos]
            pos += 1
        raise RuntimeError(f'unterminated system template literal for mode={mode}')

    modes = ('source', 'boolean', 'outreach', 'screen', 'fake')
    key_pos: dict[str, int] = {}
    search_pos = 0
    for mode in modes:
        k = _find_mode_key(search_pos, mode)
        if k < 0:
            raise RuntimeError(f'mode not found in MODES: {mode}')
        key_pos[mode] = k
        search_pos = k + len(mode)

    out: dict[str, str] = {}
    for idx, mode in enumerate(modes):
        start_k = key_pos[mode]
        end_k = key_pos[modes[idx + 1]] if idx + 1 < len(modes) else len(block)
        out[mode] = _extract_mode_system_between(start_k, end_k, mode)

    return out


def _read_prompt_file(name: str) -> str:
    """Read a prompt markdown file from app/prompts/.

    These are user-editable prompt layers that should ship with the backend bundle.
    """
    name = (name or '').strip()
    if not name:
        return ''
    p = _APP_DIR / 'prompts' / name
    if not p.exists():
        return ''
    return p.read_text(encoding='utf-8', errors='ignore').strip()


def _compact_prompt_text(md: str) -> str:
    """Trim markdown-ish formatting to reduce token count.

    Goal: keep meaning, drop visual structure: headings, horizontal rules, tables.
    """
    import re

    md = (md or '').replace('\r\n', '\n')
    if not md.strip():
        return ''

    out_lines: list[str] = []
    for ln in md.split('\n'):
        s = ln.strip()
        if not s:
            out_lines.append('')
            continue
        # Drop markdown headings
        if s.startswith('#'):
            continue
        # Drop horizontal rules
        if s in ('---', '—', '–––') or re.fullmatch(r"[-—_]{3,}", s or ''):
            continue
        # Drop table separator rows and dense table rows (pipes)
        if '|' in s:
            # Skip typical markdown table separator lines
            if re.fullmatch(r"\|?\s*[:-]+\s*(\|\s*[:-]+\s*)+\|?", s):
                continue
            # Skip most table rows; these are usually redundant for prose.
            # Keep if it's clearly not a table (rare).
            if s.count('|') >= 2:
                continue
        out_lines.append(ln)

    # Collapse multiple blank lines
    txt = '\n'.join(out_lines)
    txt = re.sub(r"\n{3,}", "\n\n", txt)
    return txt.strip()


def _file_prompt_for_mode(mode: str) -> str:
    """Lazy-load only the prompt files needed for the requested mode."""
    mode = (mode or '').strip().lower()

    if mode in ('askfubuki', 'swe'):
        return _compact_prompt_text(_read_prompt_file('askfubuki_swe_knowledge_base.md'))

    # Beta toggle removed: philosophy layer is only used as a substrate for HR.

    if mode in ('hr',):
        beta = _compact_prompt_text(_read_prompt_file('fubuki_beta_philosophy_layer.md'))
        hr_base = _compact_prompt_text(_read_prompt_file('fubuki_hr_helpline_persona.md'))
        hr_add = _compact_prompt_text(_read_prompt_file('fubuki_hr_behavioral_science_addendum.md'))
        hr_layer = (hr_base + '\n\n' + hr_add).strip() if (hr_base and hr_add) else (hr_base or hr_add)
        if beta and hr_layer:
            return (beta + '\n\n' + hr_layer).strip()
        return (hr_layer or beta or '').strip()

    return ''


def _file_backed_fubuki_prompts() -> dict[str, str]:
    """Small index for debug/UI listing.

    NOTE: keep this lightweight; actual query path uses lazy loading.
    """
    out: dict[str, str] = {}
    for k in ('hr', 'askfubuki', 'swe'):
        p = _file_prompt_for_mode(k)
        if p:
            out[k] = p

    # Add-ons / frameworks are not "modes", but we expose them for debugging.
    fw = _compact_prompt_text(_read_prompt_file('ava_labs_technical_pm_framework.md'))
    if fw:
        out['ava_labs_technical_pm_framework'] = fw

    return out


def _extract_md_section(md: str, header: str) -> str:
    """Extract a markdown section by exact header line (e.g. '## ORG LEARNING — ...').

    Returns content from the header line until the next same-level header (## ...).
    """
    md = md or ''
    if not md.strip() or not header:
        return ''

    lines = md.splitlines()
    start = -1
    for i, ln in enumerate(lines):
        if ln.strip() == header.strip():
            start = i
            break
    if start < 0:
        return ''

    out = []
    for j in range(start, len(lines)):
        ln = lines[j]
        if j > start and ln.startswith('## '):
            break
        out.append(ln)
    return ('\n'.join(out)).strip()


def _role_auto_layers(msg: str, hist: list[dict] | None = None) -> dict[str, str]:
    """Return auto-injected layers based on detected role/context.

    Important: lazy-load big files only when needed.
    """
    blob = (msg or '')
    if isinstance(hist, list):
        for h in hist[-6:]:
            if isinstance(h, dict):
                blob += '\n' + str(h.get('content') or '')
    t = blob.lower()

    # Trigger checks first (avoid loading framework unnecessarily)
    is_pmish = ('technical pm' in t) or ('technical product management' in t) or ('product management' in t)
    is_senior = any(x in t for x in ('director', 'vp', 'head', 'principal', 'senior', 'staff'))
    is_ava_dir_tech_pm = ('director of technical product management' in t) or ('director technical pm' in t) or ('director of technical pm' in t)

    if not (is_ava_dir_tech_pm or (is_pmish and is_senior)):
        return {}

    framework = _compact_prompt_text(_read_prompt_file('ava_labs_technical_pm_framework.md'))
    if not framework:
        return {}

    out: dict[str, str] = {}

    # Org learning becomes general recruiting intelligence for any senior technical PM role.
    if is_pmish and is_senior:
        org_learning = _extract_md_section(framework, '## ORG LEARNING — WHAT THIS FRAMEWORK TEACHES US')
        if org_learning:
            out['pm_org_learning'] = org_learning

    # Director of Technical PM at Ava Labs: inject full framework.
    if is_ava_dir_tech_pm:
        out['ava_director_technical_pm_framework'] = framework

    return out


def _system_block(text: str, cache: bool = False) -> dict:
    b = {"type": "text", "text": (text or '').strip()}
    if cache and b["text"]:
        b["cache_control"] = {"type": "ephemeral"}
    return b


def _fubuki_system_blocks_for_mode(mode: str, msg: str = '', hist: list[dict] | None = None) -> list[dict]:
    """Return Anthropic system blocks with per-layer caching.

    - File-backed persona layers are cached as their own blocks.
    - Embedded MODES are cached as a block (static in practice).
    - Auto role layers (like Technical PM framework) are cached as their own blocks,
      and only loaded when their trigger fires.
    """
    blocks: list[dict] = []

    # 1) Base mode content (file-backed OR embedded)
    base = _file_prompt_for_mode(mode)
    if base:
        blocks.append(_system_block(base, cache=True))
    else:
        embedded = (_extract_fubuki_system_prompts().get(mode) or '').strip()
        if embedded:
            blocks.append(_system_block(embedded, cache=True))

    # 2) Auto-injected role layers
    if msg:
        layers = _role_auto_layers(msg=msg, hist=hist)
        for _k, v in (layers or {}).items():
            if v and v.strip():
                blocks.append(_system_block(v, cache=True))

    # Filter empties
    return [b for b in blocks if (b.get('text') or '').strip()]


@app.get('/agent/fubuki/debug')
def fubuki_debug_prompts():
    if (settings.env or 'dev') == 'prod':
        return JSONResponse({'ok': False, 'error': 'not found'}, status_code=404)
    """Debug endpoint: returns system prompts for each mode.

    Includes:
    - extracted prompts from sourceress.html MODES
    - file-backed prompts (HR/AskFubuki SWE)
    """
    try:
        extracted = _extract_fubuki_system_prompts()
        file_backed = _file_backed_fubuki_prompts()

        merged = dict(extracted)
        merged.update(file_backed)

        return JSONResponse({
            'ok': True,
            'modes': {
                k: {
                    'len': len(v or ''),
                    'source': ('file' if k in file_backed else 'embedded'),
                    'system': v,
                }
                for k, v in merged.items()
            },
        })
    except Exception as e:
        logger.exception('fubuki debug failed')
        return JSONResponse({'ok': False, 'error': str(e)}, status_code=500)


@app.post('/agent/fubuki/debug/blocks')
async def fubuki_debug_blocks(request: Request):
    if (settings.env or 'dev') == 'prod':
        return JSONResponse({'ok': False, 'error': 'not found'}, status_code=404)
    """Debug endpoint: return Anthropic system blocks for a request.

    Use this to verify lazy-loading + per-layer caching.

    Body: { mode, message, history?, active_specs?, preset? }
    """
    try:
        data = await _read_json_body(request)
        mode = (data.get('mode') or '').strip()
        msg = (data.get('message') or '').strip()
        hist = data.get('history') or []
        specs = data.get('active_specs') or []
        preset = (data.get('preset') or 'recruiting').strip().lower()

        if mode not in ('source', 'boolean', 'outreach', 'screen', 'fake', 'hr', 'askfubuki'):
            return JSONResponse({'ok': False, 'error': 'invalid mode'}, status_code=400)
        if not msg:
            return JSONResponse({'ok': False, 'error': 'missing message'}, status_code=400)
        if preset not in ('recruiting', 'degen'):
            preset = 'recruiting'

        blocks = _fubuki_system_blocks_for_mode(mode, msg=msg, hist=hist)
        if preset == 'degen':
            blocks = [_system_block(_extract_degen_system_prompt(), cache=True)]
        else:
            import re
            for i, b in enumerate(blocks):
                txt = b.get('text') or ''
                txt2 = re.sub(
                    r"\[DEGEN_MODE_START\].*?\[DEGEN_MODE_END\]",
                    "",
                    txt,
                    flags=re.DOTALL,
                ).strip()
                blocks[i] = {**b, 'text': txt2}

            if specs and isinstance(specs, list):
                spec_txt = ", ".join([str(s).strip() for s in specs if str(s).strip()])
                if spec_txt:
                    blocks.append(_system_block("Active specialization context: " + spec_txt, cache=False))

        out_blocks = []
        for b in blocks:
            txt = (b.get('text') or '')
            out_blocks.append({
                'len': len(txt),
                'cached': bool(isinstance(b.get('cache_control'), dict) and b['cache_control'].get('type') == 'ephemeral'),
                'preview': (txt[:200] + ('…' if len(txt) > 200 else '')),
            })

        return JSONResponse({
            'ok': True,
            'mode': mode,
            'preset': preset,
            'block_count': len(out_blocks),
            'total_chars': sum([x['len'] for x in out_blocks]),
            'blocks': out_blocks,
        })

    except Exception as e:
        logger.exception('fubuki debug blocks failed')
        return JSONResponse({'ok': False, 'error': str(e)}, status_code=500)


@app.get('/agent/fubuki/models')
def fubuki_models(request: Request):
    if (settings.env or 'dev') == 'prod':
        return JSONResponse({'ok': False, 'error': 'not found'}, status_code=404)
    """List Anthropic models available to the provided key.

    If header `x-anthropic-key` is provided, uses that key.
    Otherwise falls back to server env ANTHROPIC_API_KEY.
    """
    try:
        import os
        server_key = (os.environ.get('ANTHROPIC_API_KEY') or '').strip()
        api_key = server_key or (request.headers.get('x-anthropic-key') or '').strip() or None
        items = anthropic_list_models(api_key=api_key)
        # Return a trimmed view to keep payload small.
        return JSONResponse({
            'ok': True,
            'models': [
                {
                    'id': m.get('id'),
                    'display_name': m.get('display_name'),
                    'created_at': m.get('created_at'),
                    'type': m.get('type'),
                }
                for m in items
                if isinstance(m, dict)
            ],
        })
    except Exception as e:
        logger.exception('fubuki models failed')
        return JSONResponse({'ok': False, 'error': str(e)}, status_code=500)


@app.get('/agent/fubuki/usage')
def fubuki_usage(limit: int = 50):
    if (settings.env or 'dev') == 'prod':
        return JSONResponse({'ok': False, 'error': 'not found'}, status_code=404)
    """Return recent usage records + aggregates.

    Computes averages by mode/preset/kind and estimates $ using a simple model.
    Price numbers are configurable via env vars.
    """
    try:
        import json
        import pathlib
        import os

        lim = max(1, min(int(limit or 50), 5000))
        p = _data_dir() / 'fubuki-usage.jsonl'
        if not p.exists():
            return JSONResponse({'ok': True, 'items': [], 'summary': {}})

        # Pricing (USD per 1M tokens). Defaults are placeholders; override via env.
        # Example:
        #   FUBUKI_COST_IN_PER_M=3
        #   FUBUKI_COST_OUT_PER_M=15
        cost_in_per_m = float(os.environ.get('FUBUKI_COST_IN_PER_M', '3') or 3)
        cost_out_per_m = float(os.environ.get('FUBUKI_COST_OUT_PER_M', '15') or 15)

        # Read last N lines
        lines: list[str] = []
        with p.open('r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                if line.strip():
                    lines.append(line)
        lines = lines[-lim:]

        items: list[dict] = []
        for ln in lines:
            try:
                o = json.loads(ln)
                if isinstance(o, dict):
                    items.append(o)
            except Exception:
                continue

        def _n(x):
            try:
                return int(x)
            except Exception:
                return 0

        def _est_cost(inp: int, outp: int) -> float:
            return (inp / 1_000_000.0) * cost_in_per_m + (outp / 1_000_000.0) * cost_out_per_m

        # Aggregate by (kind, mode, preset)
        agg: dict[tuple[str, str, str], dict] = {}
        total_in = total_out = 0
        total_cost = 0.0

        for it in items:
            kind = str(it.get('kind') or '')
            mode = str(it.get('mode') or '')
            preset = str(it.get('preset') or '')
            inp = _n(it.get('input_tokens'))
            outp = _n(it.get('output_tokens'))
            c = _est_cost(inp, outp)

            total_in += inp
            total_out += outp
            total_cost += c

            k = (kind, mode, preset)
            a = agg.setdefault(k, {'n': 0, 'input_tokens': 0, 'output_tokens': 0, 'est_cost_usd': 0.0})
            a['n'] += 1
            a['input_tokens'] += inp
            a['output_tokens'] += outp
            a['est_cost_usd'] += c

        by_key = []
        for (kind, mode, preset), a in sorted(agg.items(), key=lambda kv: kv[1]['est_cost_usd'], reverse=True):
            n = a['n'] or 1
            by_key.append({
                'kind': kind,
                'mode': mode,
                'preset': preset,
                'n': a['n'],
                'avg_input_tokens': int(a['input_tokens'] / n),
                'avg_output_tokens': int(a['output_tokens'] / n),
                'avg_est_cost_usd': round(a['est_cost_usd'] / n, 6),
                'total_est_cost_usd': round(a['est_cost_usd'], 6),
            })

        summary = {
            'pricing': {
                'cost_in_per_m': cost_in_per_m,
                'cost_out_per_m': cost_out_per_m,
            },
            'total': {
                'n': len(items),
                'input_tokens': total_in,
                'output_tokens': total_out,
                'est_cost_usd': round(total_cost, 6),
            },
            'by_key': by_key,
        }

        return JSONResponse({'ok': True, 'items': items[-50:], 'summary': summary})
    except Exception as e:
        return JSONResponse({'ok': False, 'error': str(e)}, status_code=500)


@app.post('/agent/fubuki/query')
async def fubuki_query(request: Request):
    # Protected by the same auth middleware as the rest of the app.
    try:
        data = await _read_json_body(request)
        mode = (data.get('mode') or '').strip()
        msg = (data.get('message') or '').strip()
        hist = data.get('history') or []
        specs = data.get('active_specs') or []

        if mode not in ('source', 'boolean', 'outreach', 'screen', 'fake', 'hr', 'askfubuki'):
            return JSONResponse({'ok': False, 'error': 'invalid mode'}, status_code=400)
        if not msg:
            return JSONResponse({'ok': False, 'error': 'missing message'}, status_code=400)

        system_blocks = _fubuki_system_blocks_for_mode(mode, msg=msg, hist=hist)
        if not system_blocks:
            return JSONResponse({'ok': False, 'error': f'system prompt missing for mode={mode}'}, status_code=500)

        # Get preset from request (default to 'recruiting' to save tokens)
        preset = (data.get('preset') or 'recruiting').strip().lower()
        if preset not in ('recruiting', 'degen'):
            preset = 'recruiting'

        if preset == 'degen':
            # Completely separate prompt: ignore MODES prompt and use DEGEN_SYSTEM_PROMPT.
            system_blocks = [_system_block(_extract_degen_system_prompt(), cache=True)]
        else:
            # Strip degen section if in recruiting mode (if markers exist)
            import re
            for i, b in enumerate(system_blocks):
                txt = b.get('text') or ''
                txt2 = re.sub(
                    r"\[DEGEN_MODE_START\].*?\[DEGEN_MODE_END\]",
                    "",
                    txt,
                    flags=re.DOTALL,
                ).strip()
                system_blocks[i] = {**b, 'text': txt2}

            if specs and isinstance(specs, list):
                spec_txt = ", ".join([str(s).strip() for s in specs if str(s).strip()])
                if spec_txt:
                    # Dynamic block: do NOT cache.
                    system_blocks.append(_system_block("Active specialization context: " + spec_txt, cache=False))

        # Normalize history
        messages = []
        if isinstance(hist, list):
            for h in hist:
                if not isinstance(h, dict):
                    continue
                r = (h.get('role') or '').strip()
                c = (h.get('content') or '').strip()
                if r in ('user', 'assistant') and c:
                    messages.append({'role': r, 'content': c})
        messages.append({'role': 'user', 'content': msg})

        # Prefer server key when present (personal default). Allow per-user header only as fallback.
        import os
        server_key = (os.environ.get('ANTHROPIC_API_KEY') or '').strip()
        api_key = server_key or (request.headers.get('x-anthropic-key') or '').strip() or None
        out, meta = fubuki_call_ex(system_blocks=system_blocks, messages=messages, max_tokens=1500, api_key=api_key)

        _append_usage_log({
            'kind': 'query',
            'mode': mode,
            'preset': preset,
            'owner_email': getattr(request.state, 'user_email', '') or '',
            'model_used': meta.get('model_used') or '',
            'input_tokens': meta.get('input_tokens'),
            'output_tokens': meta.get('output_tokens'),
        })

        # Frontend expects { ok: true, response: "..." } (and may ignore additional fields).
        return JSONResponse({'ok': True, 'mode': mode, 'response': out, 'mode_label': mode.upper()})

    except Exception as e:
        # If body parsing failed, make it a 400 (client error) not a 500.
        msg = str(e)
        if 'invalid JSON body' in msg or 'empty request body' in msg:
            logger.warning('fubuki query: bad JSON body (%s)', msg)
            return JSONResponse({'ok': False, 'error': msg}, status_code=400)

        # Otherwise return the actual exception to make debugging 500s painless.
        logger.exception('fubuki query failed')
        return JSONResponse({'ok': False, 'error': msg}, status_code=500)


@app.post('/companies/{company_id:int}/tags')
def company_tags_save(company_id: int, tags: str = Form('')):
    with get_session() as s:
        c = s.get(Company, company_id)
        if not c:
            return HTMLResponse('company not found', status_code=404)
        c.tags = (tags or '').strip()
        c.updated_at = __import__('datetime').datetime.utcnow()
        s.add(c)
        s.commit()

    return RedirectResponse(url=f'/companies/{company_id}', status_code=303)


@app.post('/companies/{company_id:int}/links')
def company_links_save(company_id: int, github_org_url: str = Form(''), linkedin_company_url: str = Form(''), jobs_url: str = Form('')):
    with get_session() as s:
        c = s.get(Company, company_id)
        if not c:
            return HTMLResponse('company not found', status_code=404)
        c.github_org_url = (github_org_url or '').strip()
        c.linkedin_company_url = (linkedin_company_url or '').strip()
        c.jobs_url = (jobs_url or '').strip()
        c.updated_at = __import__('datetime').datetime.utcnow()
        s.add(c)
        s.commit()

    return RedirectResponse(url=f'/companies/{company_id}', status_code=303)


@app.post('/companies/{company_id:int}/comp/add')
def company_comp_add(company_id: int, dept: str = Form('engineering'), role: str = Form(''), level: str = Form(''), location: str = Form(''), currency: str = Form('USD'), low: str = Form(''), mid: str = Form(''), high: str = Form(''), bonus: str = Form(''), equity: str = Form(''), source_url: str = Form(''), notes: str = Form('')):
    rl = (role or '').strip()
    if not rl:
        return RedirectResponse(url=f'/companies/{company_id}', status_code=303)

    def _to_int(x: str) -> int:
        x = (x or '').strip().replace(',', '').replace('$', '')
        if not x:
            return 0
        try:
            return int(float(x))
        except Exception:
            return 0

    with get_session() as s:
        c = s.get(Company, company_id)
        if not c:
            return HTMLResponse('company not found', status_code=404)
        row = CompanyCompBand(
            company_id=company_id,
            dept=(dept or 'engineering').strip() or 'engineering',
            role=rl,
            level=(level or '').strip(),
            location=(location or '').strip(),
            currency=(currency or 'USD').strip() or 'USD',
            low=_to_int(low),
            mid=_to_int(mid),
            high=_to_int(high),
            bonus=_to_int(bonus),
            equity=_to_int(equity),
            source_url=(source_url or '').strip(),
            notes=(notes or '').strip(),
        )
        s.add(row)
        s.commit()

    return RedirectResponse(url=f'/companies/{company_id}', status_code=303)


@app.get('/companies/{company_id:int}/comp/{row_id:int}/edit', response_class=HTMLResponse)
def company_comp_edit_page(request: Request, company_id: int, row_id: int):
    with get_session() as s:
        c = s.get(Company, company_id)
        row = s.get(CompanyCompBand, row_id)
        if not c or not row or row.company_id != company_id:
            return HTMLResponse('not found', status_code=404)

    return templates.TemplateResponse('comp_edit.html', {'request': request, 'c': c, 'row': row})


@app.post('/companies/{company_id:int}/comp/{row_id:int}/edit')
def company_comp_edit_save(
    company_id: int,
    row_id: int,
    dept: str = Form('engineering'),
    role: str = Form(''),
    level: str = Form(''),
    location: str = Form(''),
    currency: str = Form('USD'),
    low: str = Form(''),
    mid: str = Form(''),
    high: str = Form(''),
    bonus: str = Form(''),
    equity: str = Form(''),
    source_url: str = Form(''),
    notes: str = Form(''),
):
    def _to_int(x: str) -> int:
        x = (x or '').strip().replace(',', '').replace('$', '')
        if not x:
            return 0
        try:
            return int(float(x))
        except Exception:
            return 0

    with get_session() as s:
        row = s.get(CompanyCompBand, row_id)
        if not row or row.company_id != company_id:
            return HTMLResponse('not found', status_code=404)
        row.dept = (dept or 'engineering').strip() or 'engineering'
        row.role = (role or '').strip()
        row.level = (level or '').strip()
        row.location = (location or '').strip()
        row.currency = (currency or 'USD').strip() or 'USD'
        row.low = _to_int(low)
        row.mid = _to_int(mid)
        row.high = _to_int(high)
        row.bonus = _to_int(bonus)
        row.equity = _to_int(equity)
        row.source_url = (source_url or '').strip()
        row.notes = (notes or '').strip()
        s.add(row)
        s.commit()

    return RedirectResponse(url=f'/companies/{company_id}', status_code=303)


@app.post('/companies/{company_id:int}/comp/{row_id:int}/delete')
def company_comp_delete(company_id: int, row_id: int):
    with get_session() as s:
        row = s.get(CompanyCompBand, row_id)
        if row and row.company_id == company_id:
            s.delete(row)
            s.commit()

    return RedirectResponse(url=f'/companies/{company_id}', status_code=303)


@app.post('/companies/{company_id:int}/comp/bulk-add')
def company_comp_bulk_add(
    company_id: int,
    dept: str = Form('engineering'),
    role: str = Form(''),
    location: str = Form(''),
    source_url: str = Form(''),
    mode: str = Form('L'),
    level: list[str] = Form([]),
    low: list[str] = Form([]),
    mid: list[str] = Form([]),
    high: list[str] = Form([]),
    bonus: list[str] = Form([]),
    equity: list[str] = Form([]),
):
    rl = (role or '').strip()
    if not rl:
        return RedirectResponse(url=f'/companies/{company_id}?msg=Missing+role', status_code=303)

    loc = (location or '').strip()
    src = (source_url or '').strip()

    def _to_int(x: str) -> int:
        x = (x or '').strip().replace(',', '').replace('$', '')
        if not x:
            return 0
        try:
            return int(float(x))
        except Exception:
            return 0

    n = min(len(level), len(low), len(mid), len(high), len(bonus), len(equity))
    if n <= 0:
        return RedirectResponse(url=f'/companies/{company_id}', status_code=303)

    added = 0
    with get_session() as s:
        c = s.get(Company, company_id)
        if not c:
            return HTMLResponse('company not found', status_code=404)

        for i in range(n):
            lv = (level[i] or '').strip()
            lo = _to_int(low[i])
            mi = _to_int(mid[i])
            hi = _to_int(high[i])
            bo = _to_int(bonus[i])
            eq = _to_int(equity[i])

            # Only add if at least something filled
            if not (lo or mi or hi or bo or eq):
                continue

            s.add(CompanyCompBand(
                company_id=company_id,
                dept=(dept or 'engineering').strip() or 'engineering',
                role=rl,
                level=lv,
                location=loc,
                currency='USD',
                low=lo,
                mid=mi,
                high=hi,
                bonus=bo,
                equity=eq,
                source_url=src,
            ))
            added += 1

        s.commit()

    return RedirectResponse(url=f'/companies/{company_id}?msg=Added+{added}+rows', status_code=303)


@app.post('/companies/{company_id:int}/comp/import')
def company_comp_import(company_id: int, raw_table: str = Form(''), source_url: str = Form(''), replace: str = Form(''), dept: str = Form('engineering')):
    import csv
    from io import StringIO
    from sqlmodel import select

    raw = (raw_table or '').strip()
    if not raw:
        return RedirectResponse(url=f'/companies/{company_id}', status_code=303)

    # Detect delimiter: tab > comma
    delim = '\t' if '\t' in raw.splitlines()[0] else ','
    reader = csv.reader(StringIO(raw), delimiter=delim)
    rows = [r for r in reader if r and any((c or '').strip() for c in r)]
    if not rows:
        return RedirectResponse(url=f'/companies/{company_id}', status_code=303)

    # Header mapping (best-effort)
    hdr = [c.strip().lower() for c in rows[0]]
    has_header = any(x in hdr for x in ('role', 'title', 'level', 'location', 'min', 'max', 'low', 'high', 'median', 'mid', 'currency'))
    data_rows = rows[1:] if has_header else rows

    def col_idx(*names):
        for n in names:
            if n in hdr:
                return hdr.index(n)
        return -1

    idx_role = col_idx('role', 'title', 'job', 'position')
    idx_level = col_idx('level', 'lvl')
    idx_loc = col_idx('location', 'loc')
    idx_cur = col_idx('currency', 'cur')
    idx_low = col_idx('low', 'min')
    idx_mid = col_idx('mid', 'median', 'p50')
    idx_high = col_idx('high', 'max')
    idx_bonus = col_idx('bonus')
    idx_equity = col_idx('equity', 'stock')

    def _g(r, i):
        if i < 0:
            return ''
        if i >= len(r):
            return ''
        return (r[i] or '').strip()

    def _to_int(x: str) -> int:
        x = (x or '').strip().replace(',', '').replace('$', '')
        if not x:
            return 0
        # handle ranges like 200-250
        if '-' in x and x.count('-') == 1:
            a,b = x.split('-',1)
            try:
                return int(float(a))
            except Exception:
                pass
        try:
            return int(float(x))
        except Exception:
            return 0

    imported = 0

    with get_session() as s:
        c = s.get(Company, company_id)
        if not c:
            return HTMLResponse('company not found', status_code=404)

        if (replace or '').lower() == 'yes':
            existing = s.exec(select(CompanyCompBand).where(CompanyCompBand.company_id == company_id)).all()
            for r in existing:
                s.delete(r)
            s.commit()

        for r in data_rows:
            role = _g(r, idx_role) if idx_role >= 0 else (r[0].strip() if r else '')
            if not role:
                continue
            level = _g(r, idx_level)
            loc = _g(r, idx_loc)
            cur = _g(r, idx_cur) or 'USD'
            lowv = _to_int(_g(r, idx_low))
            midv = _to_int(_g(r, idx_mid))
            highv = _to_int(_g(r, idx_high))
            bonusv = _to_int(_g(r, idx_bonus))
            equityv = _to_int(_g(r, idx_equity))

            # If no header and looks like: role, level, location, low, mid, high
            if not has_header and len(r) >= 6:
                role = (r[0] or '').strip()
                level = (r[1] or '').strip()
                loc = (r[2] or '').strip()
                lowv = _to_int(r[3])
                midv = _to_int(r[4])
                highv = _to_int(r[5])
                bonusv = _to_int(r[6]) if len(r) >= 7 else bonusv
                equityv = _to_int(r[7]) if len(r) >= 8 else equityv

            s.add(CompanyCompBand(
                company_id=company_id,
                dept=(dept or 'engineering').strip() or 'engineering',
                role=role,
                level=level,
                location=loc,
                currency=cur,
                low=lowv,
                mid=midv,
                high=highv,
                bonus=bonusv,
                equity=equityv,
                source_url=(source_url or '').strip(),
            ))
            imported += 1

        s.commit()

    return RedirectResponse(url=f'/companies/{company_id}', status_code=303)


@app.get('/companies/{company_id:int}/wikidata/choose', response_class=HTMLResponse)
def company_wikidata_choose(request: Request, company_id: int, msg: str = Query(default='')):
    with get_session() as s:
        c = s.get(Company, company_id)
        if not c:
            return HTMLResponse('company not found', status_code=404)

    hits = []
    try:
        hits = search_company_qid(c.name, limit=8)
    except Exception as e:
        msg = (msg or '') + ((' | ' if msg else '') + str(e))

    return templates.TemplateResponse('company_wikidata_choose.html', {
        'request': request,
        'c': c,
        'hits': hits,
        'msg': msg,
    })


@app.post('/companies/{company_id:int}/wikidata/set')
def company_wikidata_set(company_id: int, qid: str = Form('')):
    q = (qid or '').strip()
    if not q:
        return RedirectResponse(url=f'/companies/{company_id}/wikidata/choose?msg=Missing+QID', status_code=303)

    with get_session() as s:
        c = s.get(Company, company_id)
        if not c:
            return HTMLResponse('company not found', status_code=404)

        wd = None
        try:
            wd = fetch_company(q)
        except Exception as e:
            return RedirectResponse(url=f'/companies/{company_id}/wikidata/choose?msg=' + __import__('urllib.parse').parse.quote(str(e)), status_code=303)

        if not wd:
            return RedirectResponse(url=f'/companies/{company_id}/wikidata/choose?msg=Not+found', status_code=303)

        c.wikidata_id = wd.qid
        c.industry_tags = wd.industry_labels or []
        doms = set([d for d in (c.domains or []) if isinstance(d, str) and d])
        for d in (wd.domains or []):
            if d:
                doms.add(d)
        c.domains = sorted(doms)
        c.updated_at = __import__('datetime').datetime.utcnow()
        s.add(c)
        s.commit()

    return RedirectResponse(url=f'/companies/{company_id}', status_code=303)


@app.post('/companies/{company_id:int}/wikidata/refresh')
def company_refresh_wikidata(company_id: int):
    """Refresh Wikidata enrichment.

    If not linked yet, redirect to chooser.
    """
    with get_session() as s:
        c = s.get(Company, company_id)
        if not c:
            return HTMLResponse('company not found', status_code=404)

        if not (c.wikidata_id or '').strip():
            return RedirectResponse(url=f'/companies/{company_id}/wikidata/choose', status_code=303)

        wd = None
        err = ''
        try:
            wd = fetch_company(c.wikidata_id)
        except Exception as e:
            wd = None
            err = str(e)

        if wd:
            c.industry_tags = wd.industry_labels or []
            doms = set([d for d in (c.domains or []) if isinstance(d, str) and d])
            for d in (wd.domains or []):
                if d:
                    doms.add(d)
            c.domains = sorted(doms)
            c.updated_at = __import__('datetime').datetime.utcnow()
            s.add(c)
            s.commit()

    if err:
        return RedirectResponse(url=f'/companies/{company_id}?msg=' + __import__('urllib.parse').parse.quote(err), status_code=303)

    return RedirectResponse(url=f'/companies/{company_id}', status_code=303)


@app.post('/companies/{company_id:int}/sec/set')
def company_sec_set(company_id: int, sec_cik: str = Form('')):
    cik10 = norm_cik(sec_cik)
    if not cik10:
        return RedirectResponse(url=f'/companies/{company_id}?msg=Invalid+CIK', status_code=303)

    with get_session() as s:
        c = s.get(Company, company_id)
        if not c:
            return HTMLResponse('company not found', status_code=404)
        c.sec_cik = cik10
        c.updated_at = __import__('datetime').datetime.utcnow()
        s.add(c)
        s.commit()

    return RedirectResponse(url=f'/companies/{company_id}', status_code=303)


@app.post('/companies/{company_id:int}/sec/refresh')
def company_sec_refresh(company_id: int):
    """Cache recent SEC filings for a company (public companies only)."""
    with get_session() as s:
        c = s.get(Company, company_id)
        if not c:
            return HTMLResponse('company not found', status_code=404)
        cik = (c.sec_cik or '').strip()

    if not cik:
        return RedirectResponse(url=f'/companies/{company_id}?msg=Set+CIK+first', status_code=303)

    try:
        sub = fetch_company_submissions(cik)
    except Exception as e:
        return RedirectResponse(url=f'/companies/{company_id}?msg=' + __import__('urllib.parse').parse.quote(str(e)), status_code=303)

    if not sub:
        return RedirectResponse(url=f'/companies/{company_id}?msg=No+SEC+data', status_code=303)

    # Simple metrics
    recent = sub.recent or []
    forms = [r.get('form') for r in recent if isinstance(r, dict)]
    def _count(prefix: str) -> int:
        return sum(1 for f in forms if isinstance(f, str) and f.strip().upper().startswith(prefix))

    metrics = {
        'name': sub.name,
        'tickers': sub.tickers,
        'sic': sub.sic,
        'sic_description': sub.sic_description,
        'state': sub.state,
        'counts': {
            '10-K': _count('10-K'),
            '10-Q': _count('10-Q'),
            '8-K': _count('8-K'),
            'S-1': _count('S-1'),
        },
        'recent': recent[:10],
    }

    with get_session() as s:
        s.add(CompanySignal(
            company_id=company_id,
            source='sec',
            signal_type='sec_filings',
            url=f'https://data.sec.gov/submissions/CIK{cik}.json',
            value_json=metrics,
        ))
        s.commit()

    return RedirectResponse(url=f'/companies/{company_id}', status_code=303)


@app.post('/companies/{company_id:int}/signals/refresh')
def company_refresh_signals(company_id: int):
    """Fetch and cache simple news-derived signals from free sources (GDELT).

    MVP heuristics:
    - Layoffs: company name + layoff-ish keywords
    - Funding: company name + funding-ish keywords
    """
    with get_session() as s:
        c = s.get(Company, company_id)
        if not c:
            return HTMLResponse('company not found', status_code=404)

        nm = (c.name or '').strip()
        # Quote the company name to reduce noise.
        layoffs_q = f'"{nm}" (layoff OR layoffs OR "reduction in force" OR RIF OR furlough)'
        funding_q = f'"{nm}" ("raised" OR funding OR "seed round" OR "Series A" OR "Series B" OR "Series C" OR "led by")'

        try:
            layoffs = fetch_doc_list(layoffs_q, days=90, limit=8)
        except Exception as e:
            layoffs = None
            err = str(e)
        else:
            err = ''

        try:
            funding = fetch_doc_list(funding_q, days=90, limit=8)
        except Exception as e:
            funding = None
            err = (err + ' | ' if err else '') + str(e)

        if layoffs:
            s.add(CompanySignal(
                company_id=company_id,
                source='gdelt',
                signal_type='layoffs',
                url='https://api.gdeltproject.org/api/v2/doc/doc',
                value_json={
                    'count': layoffs.count,
                    'articles': layoffs.articles,
                    'query': layoffs.query,
                    'start': layoffs.start,
                    'end': layoffs.end,
                },
            ))
        if funding:
            s.add(CompanySignal(
                company_id=company_id,
                source='gdelt',
                signal_type='funding',
                url='https://api.gdeltproject.org/api/v2/doc/doc',
                value_json={
                    'count': funding.count,
                    'articles': funding.articles,
                    'query': funding.query,
                    'start': funding.start,
                    'end': funding.end,
                },
            ))
        s.commit()

    if err:
        return RedirectResponse(url=f'/companies/{company_id}?msg=' + __import__('urllib.parse').parse.quote(err), status_code=303)

    return RedirectResponse(url=f'/companies/{company_id}', status_code=303)

    def _to_int(x: str):
        x = (x or '').strip().replace(',', '')
        if not x:
            return ''
        try:
            return int(float(x))
        except Exception:
            return x

    with get_session() as s:
        c = s.get(Company, company_id)
        if not c:
            return HTMLResponse('company not found', status_code=404)
        cj = c.comp_json or {}
        cj[rl] = {
            'low': _to_int(low),
            'mid': _to_int(mid),
            'high': _to_int(high),
            'notes': (notes or '').strip(),
        }
        c.comp_json = cj
        c.updated_at = __import__('datetime').datetime.utcnow()
        s.add(c)
        s.commit()

    return RedirectResponse(url=f'/companies/{company_id}', status_code=303)


@app.get('/linkedin', response_class=HTMLResponse)
def linkedin_index(request: Request, login: str = Query(default='')):
    lg = (login or '').strip()
    cand = None
    prefill = {"name": "", "location": "", "company": "", "linkedin_url": ""}

    if lg:
        with get_session() as s:
            cand = s.get(Candidate, lg)
            if cand:
                prefill["name"] = (cand.name or '').strip()
                prefill["location"] = (cand.location or '').strip()
                prefill["company"] = (cand.company or '').strip()
                try:
                    prefill["linkedin_url"] = (cand.profile_json or {}).get('linkedin_url') or ''
                except Exception:
                    prefill["linkedin_url"] = ''

    return templates.TemplateResponse('linkedin.html', {"request": request, "cand": cand, "prefill": prefill})


@app.post('/candidates/{login}/linkedin-url')
def candidate_set_linkedin_url(login: str, linkedin_url: str = Form('')):
    url = (linkedin_url or '').strip()
    if not url:
        return JSONResponse({"ok": False, "error": "missing url"}, status_code=400)

    with get_session() as s:
        cand = s.get(Candidate, login)
        if not cand:
            return JSONResponse({"ok": False, "error": "candidate not found"}, status_code=404)
        pj = cand.profile_json or {}
        pj['linkedin_url'] = url
        cand.profile_json = pj
        s.add(cand)
        s.commit()

    return JSONResponse({"ok": True})


@app.get('/openalex/search')
async def openalex_search(mode: str = Query(default='authors'), q: str = Query(default='')):
    md = (mode or 'authors').strip().lower()
    query = (q or '').strip()
    if not query:
        return JSONResponse({'ok': False, 'error': 'missing q'}, status_code=400)

    oa = OpenAlexClient()
    try:
        if md == 'works':
            data = await oa.search_works(query, per_page=25, page=1)
            items = []
            for w in (data.get('results') or []):
                items.append({
                    'id': w.get('id') or '',
                    'url': w.get('id') or w.get('primary_location', {}).get('source', {}).get('host_organization_name', '') or '',
                    'display_name': w.get('display_name') or '',
                    'publication_year': w.get('publication_year'),
                    'cited_by_count': w.get('cited_by_count') or 0,
                    'venue': ((w.get('primary_location') or {}).get('source') or {}).get('display_name') or '',
                })
            # for works, url should be an OpenAlex web URL
            for it in items:
                if it.get('id') and isinstance(it['id'], str) and it['id'].startswith('https://openalex.org/'):
                    it['url'] = it['id']
            return JSONResponse({'ok': True, 'items': items})

        # default authors
        data = await oa.search_authors(query, per_page=25, page=1)
        items = []
        for a in (data.get('results') or []):
            inst = (a.get('last_known_institution') or {}).get('display_name') or ''
            items.append({
                'id': a.get('id') or '',
                'url': a.get('id') or '',
                'display_name': a.get('display_name') or '',
                'last_known_institution': inst,
                'works_count': a.get('works_count') or 0,
                'cited_by_count': a.get('cited_by_count') or 0,
            })
        return JSONResponse({'ok': True, 'items': items})
    except Exception as e:
        return JSONResponse({'ok': False, 'error': str(e)}, status_code=500)


@app.post("/search")
async def search(
    request: Request,
    query: str = Form(...),
    repo_seeds: str = Form(""),
    location: str = Form(""),
    min_followers: int = Form(0),
    active_days: int = Form(180),
    min_contribs: int = Form(0),
    max_contribs: int = Form(0),
    location_include: str = Form(""),
    location_exclude: str = Form(""),
    company_include: str = Form(""),
    company_exclude: str = Form(""),
):
    run_id = create_run(
        query,
        owner_email=getattr(request.state, 'user_email', ''),
        repo_seeds=repo_seeds,
        location=location,
        min_followers=min_followers,
        active_days=active_days,
        min_contribs=min_contribs,
        max_contribs=max_contribs,
        location_include=location_include,
        location_exclude=location_exclude,
        company_include=company_include,
        company_exclude=company_exclude,
    )
    # Fire-and-forget background population (personal-use MVP)
    asyncio.create_task(populate_run(run_id))
    return RedirectResponse(url=f"/runs/{run_id}", status_code=303)

@app.get("/runs/{run_id:int}.json")
def run_results_json(
    run_id: int,
    sort: str = Query(default="score"),
    direction: str = Query(default="desc"),
):
    status = get_run_status(run_id)
    candidates = get_run_results(run_id)

    key_map = {
        "score": lambda c: c.get("score") or 0,
        "followers": lambda c: c.get("followers") or 0,
        "stars": lambda c: c.get("stars_total") or 0,
        "go_share": lambda c: c.get("go_share") or 0,
        "recency": lambda c: (c.get("recency_days") if c.get("recency_days") is not None else 1e9),
    }
    k = key_map.get(sort, key_map["score"])
    reverse = (direction != "asc")
    # For recency, smaller is better → if descending requested, still treat as ascending
    if sort == "recency":
        # smaller is better; ignore direction for now
        reverse = False

    candidates_sorted = sorted(candidates, key=k, reverse=reverse)
    return JSONResponse({"status": status, "candidates": candidates_sorted[:200]})


@app.get("/candidates/{login}", response_class=HTMLResponse)
def candidate_page(request: Request, login: str):
    from sqlmodel import select
    with get_session() as s:
        cand = s.get(Candidate, login)
        if not cand:
            return HTMLResponse("candidate not found", status_code=404)

        # Auto-discover companies from candidate profiles
        if (cand.company or '').strip():
            try:
                upsert_company(s, cand.company, origin='candidate')
            except Exception:
                pass

        exps = s.exec(
            select(CandidateExperience)
            .where(CandidateExperience.login == login)
            .order_by(CandidateExperience.start_date.desc().nullslast(), CandidateExperience.created_at.desc())
        ).all()

    # Build view model for template
    items = []
    for e in exps:
        sd = e.start_date
        ed = e.end_date
        dr = ""
        if sd and ed:
            dr = f"{sd.strftime('%b %Y')} - {ed.strftime('%b %Y')}"
        elif sd and ed is None:
            dr = f"{sd.strftime('%b %Y')} - Present"
        elif sd:
            dr = f"{sd.strftime('%b %Y')}"

        # duration months (best-effort)
        dur = ""
        if sd:
            from datetime import date as _date
            end = ed or _date.today()
            # compute months
            months = (end.year - sd.year) * 12 + (end.month - sd.month)
            if months < 0:
                months = 0
            dur = fmt_months(months)

        items.append(
            {
                "title": e.title,
                "company": e.company,
                "location": e.location,
                "date_range": dr,
                "duration": dur,
                "bullets": e.bullets or [],
            }
        )

    stats_raw = compute_experience_stats([
        {"start_date": e.start_date, "end_date": e.end_date} for e in exps
    ])
    stats = {
        "total": fmt_months(stats_raw.get("total_months", 0) or 0),
        "current": fmt_months(stats_raw.get("current_months", 0) or 0),
        "avg": fmt_months(stats_raw.get("avg_months", 0) or 0),
    }

    # warnings via query param
    w = (request.query_params.get('w') or '').strip()
    warnings = [w] if w else []

    back = (request.query_params.get('back') or '').strip()

    # Company comp snapshot (aggregate, SWE-ish)
    comp_snapshot = None
    try:
        if (cand.company or '').strip():
            nn = norm_company_name(cand.company)
            from sqlmodel import select
            with get_session() as s:
                co = s.exec(select(Company).where(Company.norm_name == nn)).first()
                if co:
                    rows = s.exec(select(CompanyCompBand).where(CompanyCompBand.company_id == co.id)).all()
            if co and rows:
                # SWE-ish rows
                swe = [r for r in rows if (r.role or '').lower().find('engineer') >= 0]
                use = swe if swe else rows

                def _median_int(vals):
                    vals = sorted([int(v) for v in vals if v is not None])
                    if not vals:
                        return 0
                    n = len(vals)
                    m = n // 2
                    if n % 2 == 1:
                        return vals[m]
                    return int((vals[m-1] + vals[m]) / 2)

                lows = [r.low for r in use if (r.low or 0) > 0]
                mids = [r.mid for r in use if (r.mid or 0) > 0]
                highs = [r.high for r in use if (r.high or 0) > 0]
                cur = ''
                for r in use:
                    if (r.currency or '').strip():
                        cur = (r.currency or '').strip(); break

                if lows or mids or highs:
                    comp_snapshot = {
                        'company_id': co.id,
                        'company_name': co.name,
                        'role': 'SWE (aggregate)' if swe else 'Aggregate',
                        'currency': cur or 'USD',
                        'low': _median_int(lows) if lows else 0,
                        'mid': _median_int(mids) if mids else 0,
                        'high': _median_int(highs) if highs else 0,
                        'n': len(use),
                    }
    except Exception:
        comp_snapshot = None

    return templates.TemplateResponse(
        "candidate.html",
        {"request": request, "cand": cand, "items": items, "stats": stats, "warnings": warnings, "back": back, "comp_snapshot": comp_snapshot},
    )


@app.post("/candidates/{login}/experience/import-paste")
def candidate_experience_import_paste(
    request: Request,
    login: str,
    raw_text: str = Form(""),
    confirm_replace: str = Form(""),
):
    from sqlmodel import select

    raw = (raw_text or "").strip()
    if not raw:
        return RedirectResponse(url=f"/candidates/{login}", status_code=303)

    items, warnings = parse_linkedin_experience_paste(raw)

    with get_session() as s:
        cand = s.get(Candidate, login)
        if not cand:
            return HTMLResponse("candidate not found", status_code=404)

        if (confirm_replace or "").lower() == "yes":
            rows = s.exec(
                select(CandidateExperience)
                .where(CandidateExperience.login == login)
                .where(CandidateExperience.source == "linkedin_paste")
            ).all()
            for r in rows:
                s.delete(r)
            s.commit()

        for it in items:
            ce = CandidateExperience(
                login=login,
                source="linkedin_paste",
                raw_text=it.get("raw_text") or raw,
                company=it.get("company") or "",
                title=it.get("title") or "",
                location=it.get("location") or "",
                start_date=it.get("start_date"),
                end_date=it.get("end_date"),
                bullets=it.get("bullets") or [],
            )
            s.add(ce)
        s.commit()

    # render with warnings shown
    # (simple approach: stash warnings via query param)
    if warnings:
        # encode into a short query param (truncate)
        import urllib.parse
        w = "; ".join(warnings)[:500]
        return RedirectResponse(url=f"/candidates/{login}?w={urllib.parse.quote(w)}", status_code=303)

    return RedirectResponse(url=f"/candidates/{login}", status_code=303)


@app.post("/candidates/{login}/email")
async def candidate_email(login: str):
    # Safer: fetch email only on-demand per candidate.
    with get_session() as s:
        email, source = await fetch_email_for_candidate(s, login)
    return JSONResponse({"login": login, "email": email, "email_source": source})


@app.post("/runs/{run_id:int}/feedback")
def run_feedback(
    run_id: int,
    login: str = Form(...),
    label: int = Form(0),
    note: str = Form(""),
):
    # Minimal "training" signal: store thumbs up/down per candidate.
    if label not in (-1, 1):
        return JSONResponse({"ok": False, "error": "label must be -1 or 1"}, status_code=400)

    with get_session() as s:
        fb = CandidateFeedback(run_id=run_id, login=login, label=label, note=note)
        s.add(fb)
        s.commit()

    return JSONResponse({"ok": True})

@app.get("/out")
def out(url: str = Query(...)):
    # Bulletproof external link handler: only allow GitHub URLs.
    u = (url or "").strip()
    if not (u.startswith("https://github.com/") or u.startswith("http://github.com/")):
        return JSONResponse({"ok": False, "error": "only github.com urls allowed"}, status_code=400)
    if u.startswith("http://"):
        u = "https://" + u[len("http://"):]
    return RedirectResponse(u, status_code=302)


@app.get("/runs/{run_id:int}.csv")
def run_csv(run_id: int):
    candidates = get_run_results(run_id)
    buf = StringIO()
    writer = csv.DictWriter(buf, fieldnames=["login","name","url","location","company","followers","score","reasons"])
    writer.writeheader()
    for c in candidates:
        writer.writerow({
            "login": c["login"],
            "name": c["name"],
            "url": c["url"],
            "location": c["location"],
            "company": c["company"],
            "followers": c["followers"],
            "score": f"{c['score']:.2f}",
            "reasons": "; ".join(c["reasons"]),
        })

    return Response(content=buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": f"attachment; filename=run-{run_id}.csv"})


@app.get("/runs/{run_id:int}", response_class=HTMLResponse)
def run_results(request: Request, run_id: int):
    # Page is dynamic (polls JSON)
    st = get_run_status(run_id)
    if (st or {}).get("source") == "stack":
        return templates.TemplateResponse("stack_results.html", {"request": request, "run_id": run_id})
    return templates.TemplateResponse("results.html", {"request": request, "run_id": run_id})


@app.get("/projects-ui", response_class=HTMLResponse)
def projects_ui(request: Request):
    return templates.TemplateResponse("projects.html", {"request": request})


@app.post("/stack/search")
async def stack_search(
    request: Request,
    tags: str = Form(""),
    match: str = Form("any"),
    days: int = Form(90),
    min_rep: int = Form(0),
    min_answers: int = Form(0),
):
    tags = (tags or "").strip()
    if not tags:
        return RedirectResponse(url="/stack", status_code=303)

    # Store tags in dedicated fields; raw_query for display/trace
    raw_query = f"stack tags: {tags}"
    run_id = create_run(raw_query, owner_email=getattr(request.state, 'user_email', '') or '')
    with get_session() as s:
        run = s.get(SearchRun, run_id)
        if run:
            run.source = "stack"
            run.stack_tags = tags
            run.stack_match = (match or "any").lower()
            run.active_days = int(days or 90)
            run.min_rep = int(min_rep or 0)
            run.min_answers = int(min_answers or 0)
            run.status = "queued"
            run.processed = 0
            run.total = 0
            run.error = ""
            s.add(run)
            s.commit()

    asyncio.create_task(populate_run(run_id))
    return RedirectResponse(url=f"/runs/{run_id}", status_code=303)


@app.get("/saved-searches")
def saved_searches_list():
    from sqlmodel import select
    with get_session() as s:
        rows = s.exec(select(SavedSearch).order_by(SavedSearch.updated_at.desc())).all()
    return JSONResponse({"items": [r.model_dump() for r in rows]})


@app.post("/saved-searches")
def saved_searches_create(
    name: str = Form(...),
    query: str = Form(...),
    repo_seeds: str = Form(""),
    location: str = Form(""),
    min_followers: int = Form(0),
    active_days: int = Form(180),
    min_contribs: int = Form(0),
    max_contribs: int = Form(0),
    location_include: str = Form(""),
    location_exclude: str = Form(""),
    company_include: str = Form(""),
    company_exclude: str = Form(""),
):
    from datetime import datetime
    with get_session() as s:
        ss = SavedSearch(
            name=name.strip(),
            query=query,
            repo_seeds=repo_seeds,
            location=location,
            min_followers=min_followers,
            active_days=active_days,
            min_contribs=min_contribs,
            max_contribs=max_contribs,
            location_include=location_include,
            location_exclude=location_exclude,
            company_include=company_include,
            company_exclude=company_exclude,
            updated_at=datetime.utcnow(),
        )
        s.add(ss)
        s.commit()
        s.refresh(ss)
        return JSONResponse({"ok": True, "item": ss.model_dump()})


@app.delete("/saved-searches/{saved_id:int}")
def saved_searches_delete(saved_id: int):
    with get_session() as s:
        ss = s.get(SavedSearch, saved_id)
        if not ss:
            return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
        s.delete(ss)
        s.commit()
    return JSONResponse({"ok": True})


@app.post("/saved-searches/{saved_id:int}/run")
async def saved_searches_run(request: Request, saved_id: int):
    with get_session() as s:
        ss = s.get(SavedSearch, saved_id)
        if not ss:
            return JSONResponse({"ok": False, "error": "not found"}, status_code=404)

    run_id = create_run(
        ss.query,
        owner_email=getattr(request.state, 'user_email', '') or '',
        repo_seeds=ss.repo_seeds,
        location=ss.location,
        min_followers=ss.min_followers,
        active_days=ss.active_days,
        min_contribs=getattr(ss, "min_contribs", 0) or 0,
        max_contribs=getattr(ss, "max_contribs", 0) or 0,
        location_include=getattr(ss, "location_include", "") or "",
        location_exclude=getattr(ss, "location_exclude", "") or "",
        company_include=getattr(ss, "company_include", "") or "",
        company_exclude=getattr(ss, "company_exclude", "") or "",
    )
    asyncio.create_task(populate_run(run_id))
    return JSONResponse({"ok": True, "run_id": run_id})


# ---- Projects (favorite profiles grouped by project) ----
@app.get("/projects")
def projects_list(sort: str = Query(default="updated")):
    from sqlmodel import select

    srt = (sort or "updated").strip().lower()

    order = Project.updated_at.desc()
    if srt == "name":
        order = Project.name.asc()
    elif srt == "created":
        order = Project.created_at.desc()

    with get_session() as s:
        rows = s.exec(select(Project).order_by(order)).all()

    return JSONResponse(jsonable_encoder({"items": [r.model_dump() for r in rows]}))


@app.post("/projects")
def projects_create(name: str = Form(...), notes: str = Form("")):
    from datetime import datetime
    nm = (name or "").strip()
    if not nm:
        return JSONResponse({"ok": False, "error": "missing name"}, status_code=400)

    with get_session() as s:
        p = Project(name=nm, notes=notes, updated_at=datetime.utcnow())
        s.add(p)
        s.commit()
        s.refresh(p)
    return JSONResponse(jsonable_encoder({"ok": True, "item": p.model_dump()}))


@app.post("/projects/{project_id:int}/edit")
def projects_edit(project_id: int, name: str = Form(""), notes: str = Form("")):
    from datetime import datetime

    nm = (name or "").strip()

    with get_session() as s:
        p = s.get(Project, project_id)
        if not p:
            return JSONResponse({"ok": False, "error": "not found"}, status_code=404)

        if nm:
            p.name = nm
        if notes is not None:
            p.notes = notes
        p.updated_at = datetime.utcnow()
        s.add(p)
        s.commit()
        s.refresh(p)

    return JSONResponse(jsonable_encoder({"ok": True, "item": p.model_dump()}))


@app.post("/projects/{project_id:int}/delete")
def projects_delete(project_id: int):
    from sqlmodel import select

    with get_session() as s:
        p = s.get(Project, project_id)
        if not p:
            return JSONResponse({"ok": False, "error": "not found"}, status_code=404)

        # delete children first (sqlite FK cascades not guaranteed)
        pcs = s.exec(select(ProjectCandidate).where(ProjectCandidate.project_id == project_id)).all()
        for pc in pcs:
            s.delete(pc)

        s.delete(p)
        s.commit()

    return JSONResponse({"ok": True})


@app.get("/projects/{project_id:int}")
def projects_get(project_id: int):
    """Return unified project pipeline items.

    In dev, this endpoint should *never* hard-500 without explanation.
    """
    from sqlmodel import select

    try:
        with get_session() as s:
            p = s.get(Project, project_id)
            if not p:
                return JSONResponse({"ok": False, "error": "not found"}, status_code=404)

            # Unified pipeline items
            entities = s.exec(
                select(ProjectEntity)
                .where(ProjectEntity.project_id == project_id)
                .order_by(ProjectEntity.updated_at.desc())
            ).all()

            # Back-compat: also show legacy ProjectCandidate rows as github entities
            legacy = s.exec(
                select(ProjectCandidate, Candidate)
                .where(ProjectCandidate.project_id == project_id)
                .join(Candidate, Candidate.login == ProjectCandidate.login)
                .order_by(ProjectCandidate.created_at.desc())
            ).all()

        items = []

        # New unified
        for e in entities:
            items.append({
                "id": e.id,
                "source": e.source,
                "external_id": e.external_id,
                "display_name": e.display_name,
                "url": e.url,
                "avatar": (e.summary_json or {}).get('avatar') or '',
                "note": e.note,
                "status": (e.status or 'new'),
                "added_at": e.created_at.isoformat(),
                "summary": e.summary_json or {},
            })

        # Legacy items (skip if already present in entities as github+login)
        existing_keys = {(it.get('source'), it.get('external_id')) for it in items}
        for pc, c in legacy:
            key = ('github', c.login)
            if key in existing_keys:
                continue
            items.append({
                "id": None,
                "source": 'github',
                "external_id": c.login,
                "display_name": c.name or c.login,
                "url": c.html_url,
                "avatar": c.avatar_url,
                "note": pc.note,
                "status": getattr(pc, 'status', 'new') or 'new',
                "added_at": pc.created_at.isoformat(),
                "summary": {"login": c.login, "location": c.location, "company": c.company, "followers": c.followers},
            })

        return JSONResponse(jsonable_encoder({"ok": True, "project": p.model_dump(), "items": items}))

    except Exception as e:
        return JSONResponse({"ok": False, "error": f"projects_get failed: {type(e).__name__}: {e}"}, status_code=500)


@app.post("/projects/{project_id:int}/add")
def projects_add(
    project_id: int,
    # github legacy
    login: str = Form(""),
    # generic
    source: str = Form(""),
    external_id: str = Form(""),
    display_name: str = Form(""),
    url: str = Form(""),
    avatar: str = Form(""),
    note: str = Form(""),
    status: str = Form("new"),
):
    from datetime import datetime
    from sqlmodel import select

    status = (status or 'new').strip().lower()
    if status not in ('new', 'contacted', 'pass'):
        status = 'new'

    src = (source or '').strip().lower()
    ext = (external_id or '').strip()

    # Back-compat: if login provided, treat as github
    if (not src or not ext) and (login or '').strip():
        src = 'github'
        ext = (login or '').strip()

    if not src or not ext:
        return JSONResponse({"ok": False, "error": "missing source/external_id"}, status_code=400)

    with get_session() as s:
        p = s.get(Project, project_id)
        if not p:
            return JSONResponse({"ok": False, "error": "project not found"}, status_code=404)

        summary = {}
        # If github, enrich from Candidate row when possible
        if src == 'github':
            c = s.get(Candidate, ext)
            if c:
                summary = {"login": c.login, "location": c.location, "company": c.company, "followers": c.followers, "avatar": c.avatar_url}
                if not display_name:
                    display_name = c.name or c.login
                if not url:
                    url = c.html_url
                if not avatar:
                    avatar = c.avatar_url

        if avatar:
            summary["avatar"] = avatar

        existing = s.exec(
            select(ProjectEntity).where(
                ProjectEntity.project_id == project_id,
                ProjectEntity.source == src,
                ProjectEntity.external_id == ext,
            )
        ).first()

        if existing:
            existing.note = note or existing.note
            if status:
                existing.status = status
            if display_name:
                existing.display_name = display_name
            if url:
                existing.url = url
            if summary:
                existing.summary_json = {**(existing.summary_json or {}), **summary}
            existing.updated_at = datetime.utcnow()
            s.add(existing)
        else:
            s.add(
                ProjectEntity(
                    project_id=project_id,
                    source=src,
                    external_id=ext,
                    display_name=display_name or ext,
                    url=url,
                    summary_json=summary,
                    status=status,
                    note=note,
                    updated_at=datetime.utcnow(),
                )
            )

        # Keep legacy table updated for github only (compat)
        if src == 'github':
            pc = s.exec(
                select(ProjectCandidate).where(ProjectCandidate.project_id == project_id, ProjectCandidate.login == ext)
            ).first()
            if pc:
                pc.note = note or pc.note
                pc.status = status
                s.add(pc)
            else:
                s.add(ProjectCandidate(project_id=project_id, login=ext, note=note, status=status))

        p.updated_at = datetime.utcnow()
        s.add(p)
        s.commit()

    return JSONResponse({"ok": True})


@app.post("/projects/{project_id:int}/remove")
def projects_remove(
    project_id: int,
    login: str = Form(""),
    source: str = Form(""),
    external_id: str = Form(""),
):
    from datetime import datetime
    from sqlmodel import select

    src = (source or '').strip().lower()
    ext = (external_id or '').strip()
    if (not src or not ext) and (login or '').strip():
        src = 'github'
        ext = (login or '').strip()

    if not src or not ext:
        return JSONResponse({"ok": False, "error": "missing source/external_id"}, status_code=400)

    with get_session() as s:
        p = s.get(Project, project_id)
        if not p:
            return JSONResponse({"ok": False, "error": "project not found"}, status_code=404)

        pe = s.exec(
            select(ProjectEntity).where(ProjectEntity.project_id == project_id, ProjectEntity.source == src, ProjectEntity.external_id == ext)
        ).first()
        if pe:
            s.delete(pe)

        # legacy github
        if src == 'github':
            pc = s.exec(
                select(ProjectCandidate).where(ProjectCandidate.project_id == project_id, ProjectCandidate.login == ext)
            ).first()
            if pc:
                s.delete(pc)

        p.updated_at = datetime.utcnow()
        s.add(p)
        s.commit()

    return JSONResponse({"ok": True})


@app.post("/projects/{project_id:int}/status")
def projects_set_status(
    project_id: int,
    login: str = Form(""),
    source: str = Form(""),
    external_id: str = Form(""),
    status: str = Form(...),
):
    """Update pipeline status for an entity in a project."""
    from datetime import datetime
    from sqlmodel import select

    status = (status or '').strip().lower()
    if status not in ('new', 'contacted', 'pass'):
        return JSONResponse({"ok": False, "error": "invalid status"}, status_code=400)

    src = (source or '').strip().lower()
    ext = (external_id or '').strip()
    if (not src or not ext) and (login or '').strip():
        src = 'github'
        ext = (login or '').strip()

    if not src or not ext:
        return JSONResponse({"ok": False, "error": "missing source/external_id"}, status_code=400)

    with get_session() as s:
        p = s.get(Project, project_id)
        if not p:
            return JSONResponse({"ok": False, "error": "project not found"}, status_code=404)

        pe = s.exec(
            select(ProjectEntity).where(ProjectEntity.project_id == project_id, ProjectEntity.source == src, ProjectEntity.external_id == ext)
        ).first()
        if pe:
            pe.status = status
            pe.updated_at = datetime.utcnow()
            s.add(pe)

        # legacy github
        if src == 'github':
            pc = s.exec(
                select(ProjectCandidate).where(ProjectCandidate.project_id == project_id, ProjectCandidate.login == ext)
            ).first()
            if pc:
                pc.status = status
                s.add(pc)

        p.updated_at = datetime.utcnow()
        s.add(p)
        s.commit()

    return JSONResponse({"ok": True})



# ─────────────────────────────────────────────────────────────
# Weekend Mode (batch upload scaffolding)
# ─────────────────────────────────────────────────────────────
from .services.weekend_jobs_service import (
    create_job as _wk_create_job,
    add_upload_artifact as _wk_add_upload_artifact,
    expand_zip_uploads as _wk_expand_zip_uploads,
    list_jobs as _wk_list_jobs,
    get_job as _wk_get_job,
    get_job_artifacts as _wk_get_job_artifacts,
    set_job_status as _wk_set_job_status,
    job_root as _wk_job_root,
)
from .weekend_jobs_model import WeekendArtifact
from .services.weekend_anthropic_batch_service import (
    submit_batch as _wk_submit_batch,
    poll_batch as _wk_poll_batch,
)


@app.get('/weekend/jobs', response_class=HTMLResponse)
def weekend_jobs_page(request: Request):
    return templates.TemplateResponse('weekend_jobs.html', {'request': request})


@app.get('/weekend/jobs/{job_id:int}', response_class=HTMLResponse)
def weekend_job_detail_page(request: Request, job_id: int):
    with get_session() as s:
        job = _wk_get_job(s, job_id)
        if not job:
            return HTMLResponse('job not found', status_code=404)
        artifacts = _wk_get_job_artifacts(s, job_id)
    return templates.TemplateResponse('weekend_job_detail.html', {'request': request, 'job': job, 'artifacts': artifacts})


@app.get('/api/weekend/jobs')
def weekend_jobs_list_api(limit: int = 50):
    with get_session() as s:
        jobs = _wk_list_jobs(s, limit=limit)
    return JSONResponse({'ok': True, 'jobs': [j.model_dump() for j in jobs]})


@app.post('/api/weekend/jobs')
async def weekend_jobs_create_api(
    request: Request,
    title: str = Form(''),
    notes: str = Form(''),
    files: list[UploadFile] = File(default_factory=list),
):
    if not files:
        return JSONResponse({'ok': False, 'error': 'no files uploaded'}, status_code=400)

    owner_email = getattr(request.state, 'user_email', '') or ''

    # Extra-paranoid limits to keep demo builds resilient.
    MAX_FILE_BYTES = 20 * 1024 * 1024   # 20 MiB per uploaded file
    MAX_TOTAL_BYTES = 50 * 1024 * 1024  # 50 MiB per request

    total = 0

    with get_session() as s:
        job = _wk_create_job(s, owner_email=owner_email, title=title, notes=notes)
        for f in files:
            data = await f.read()
            sz = len(data or b'')
            total += sz
            if sz > MAX_FILE_BYTES:
                return JSONResponse({'ok': False, 'error': f'file too large: {f.filename} ({sz} bytes), limit is {MAX_FILE_BYTES}'}, status_code=413)
            if total > MAX_TOTAL_BYTES:
                return JSONResponse({'ok': False, 'error': f'total upload too large ({total} bytes), limit is {MAX_TOTAL_BYTES}'}, status_code=413)

            _wk_add_upload_artifact(
                s,
                job_id=job.id,
                filename=f.filename or 'file',
                content_type=(f.content_type or ''),
                data=data,
            )
        _wk_expand_zip_uploads(s, job_id=job.id)

    return JSONResponse({'ok': True, 'job_id': job.id})


@app.get('/api/weekend/jobs/{job_id:int}')
def weekend_jobs_get_api(job_id: int):
    with get_session() as s:
        job = _wk_get_job(s, job_id)
        if not job:
            return JSONResponse({'ok': False, 'error': 'job not found'}, status_code=404)
        artifacts = _wk_get_job_artifacts(s, job_id)
    return JSONResponse({'ok': True, 'job': job.model_dump(), 'artifacts': [a.model_dump() for a in artifacts]})


@app.post('/api/weekend/jobs/{job_id:int}/status')
async def weekend_jobs_set_status_api(job_id: int, request: Request):
    try:
        body = await _read_json_body(request)
    except Exception as e:
        return JSONResponse({'ok': False, 'error': str(e)}, status_code=400)

    status = (body.get('status') or '').strip().lower()
    if status not in ('queued', 'processing', 'done', 'error'):
        return JSONResponse({'ok': False, 'error': 'invalid status'}, status_code=400)
    err = (body.get('error') or '').strip()

    with get_session() as s:
        job = _wk_set_job_status(s, job_id, status, error=err)
        if not job:
            return JSONResponse({'ok': False, 'error': 'job not found'}, status_code=404)
    return JSONResponse({'ok': True, 'job': job.model_dump()})


@app.get('/api/weekend/jobs/{job_id:int}/artifacts/{artifact_id:int}/download')
def weekend_jobs_download_artifact(job_id: int, artifact_id: int):
    from fastapi.responses import FileResponse

    with get_session() as s:
        job = _wk_get_job(s, job_id)
        if not job:
            return JSONResponse({'ok': False, 'error': 'job not found'}, status_code=404)
        art = s.get(WeekendArtifact, artifact_id)
        if not art or art.job_id != job_id:
            return JSONResponse({'ok': False, 'error': 'artifact not found'}, status_code=404)
        root = _wk_job_root(job_id)
        path = (root / (art.rel_path or '')).resolve()
        # Extra-paranoid: ensure artifact path stays inside the job root.
        try:
            if root.resolve() not in path.parents and path != root.resolve():
                return JSONResponse({'ok': False, 'error': 'invalid artifact path'}, status_code=400)
        except Exception:
            return JSONResponse({'ok': False, 'error': 'invalid artifact path'}, status_code=400)
        if not path.exists():
            return JSONResponse({'ok': False, 'error': 'file missing on disk'}, status_code=404)
        return FileResponse(path, filename=art.filename or path.name, media_type=art.content_type or 'application/octet-stream')


@app.post('/api/weekend/jobs/{job_id:int}/batch/submit')
async def weekend_jobs_submit_batch_api(job_id: int, request: Request):
    """Submit a Weekend job to Anthropic Batch API.

    Uses ANTHROPIC_API_KEY from the backend environment.
    """
    try:
        body = await _read_json_body(request)
    except Exception:
        body = {}

    model = (body.get('model') or '').strip()
    max_tokens = int(body.get('max_tokens') or 1200)

    with get_session() as s:
        try:
            job = _wk_submit_batch(s, job_id=job_id, model=model or None, max_tokens=max_tokens)
        except Exception as e:
            return JSONResponse({'ok': False, 'error': str(e)}, status_code=400)

    return JSONResponse({'ok': True, 'job': job.model_dump()})


@app.post('/api/weekend/jobs/{job_id:int}/batch/poll')
def weekend_jobs_poll_batch_api(job_id: int):
    with get_session() as s:
        try:
            out = _wk_poll_batch(s, job_id=job_id)
        except Exception as e:
            return JSONResponse({'ok': False, 'error': str(e)}, status_code=400)

    return JSONResponse({'ok': True, **out})


# ─────────────────────────────────────────────────────────────
# Doc import into Fubuki main chat
# ─────────────────────────────────────────────────────────────
from .services.doc_import_service import extract_text_from_upload


@app.post('/agent/fubuki/import_doc')
async def fubuki_import_doc(file: UploadFile = File(...), max_chars: int = Form(120_000)):
    # Basic safety: limit upload size to keep demo builds resilient.
    # (Users can still import large docs by raising the limit later.)
    data = await file.read()
    MAX_BYTES = 10 * 1024 * 1024  # 10 MiB
    if data and len(data) > MAX_BYTES:
        return JSONResponse({'ok': False, 'error': f'file too large ({len(data)} bytes), limit is {MAX_BYTES}'}, status_code=413)
    try:
        text = extract_text_from_upload(file.filename or 'file', data)
    except Exception as e:
        return JSONResponse({'ok': False, 'error': str(e)}, status_code=400)

    max_chars = int(max(10_000, min(int(max_chars or 120_000), 500_000)))
    truncated = False
    if len(text) > max_chars:
        text = text[:max_chars]
        truncated = True

    return JSONResponse({
        'ok': True,
        'filename': file.filename or 'file',
        'text': text,
        'truncated': truncated,
        'chars': len(text),
    })
