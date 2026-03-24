from __future__ import annotations

import csv
from io import StringIO

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, Response, JSONResponse
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi import Query
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

import asyncio

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
from .experience import CandidateExperience, parse_linkedin_experience_paste, compute_experience_stats, fmt_months
from .auth import get_bearer_token, verify_supabase_jwt, email_allowed
from .secrets_store import set_github_token, get_github_token

app = FastAPI(title="Sourceress (MVP)")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# Allow Supabase auth to redirect back and for browser login.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)


def _get_session_token(req: Request) -> str | None:
    # Prefer cookie, fallback to bearer
    tok = req.cookies.get('sb_access_token')
    if tok:
        return tok
    return get_bearer_token(req)


def _auth_bypass_enabled() -> bool:
    # Local/dev convenience:
    # - if SUPABASE_JWT_SECRET missing we cannot verify tokens
    # - if ALLOWLIST_EMAILS empty we treat the app as "open" for local use
    allow = [e.strip() for e in (settings.allowlist_emails or '').split(',') if e.strip()]
    if not settings.supabase_jwt_secret:
        return True
    if not allow:
        return True
    return False


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
        return RedirectResponse(url='/login', status_code=303)

    email = (claims.get('email') or '').strip()
    if not email or not email_allowed(email):
        return JSONResponse({'ok': False, 'error': 'not invited'}, status_code=403)

    request.state.user_email = email
    return await call_next(request)

@app.on_event("startup")
def _startup() -> None:
    init_db()

@app.get("/health")
def health():
    return {"ok": True}


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


@app.get('/openalex', response_class=HTMLResponse)
def openalex_index(request: Request):
    return templates.TemplateResponse('openalex.html', {'request': request})


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
            flag = ''
            if b.get('mid', 0) and a.get('mid', 0):
                ratio = a['mid'] / b['mid']
                if ratio < 0.85:
                    flag = 'UNDER_AVA'
                elif ratio > 1.15:
                    flag = 'OVER_AVA'
            row['deltas'][fid] = {'mid_delta': dm, 'flag': flag}
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
