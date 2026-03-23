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

    return templates.TemplateResponse(
        "candidate.html",
        {"request": request, "cand": cand, "items": items, "stats": stats, "warnings": warnings, "back": back},
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
