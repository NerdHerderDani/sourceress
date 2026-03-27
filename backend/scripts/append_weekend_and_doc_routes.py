from pathlib import Path

p = Path(__file__).resolve().parents[1] / 'app' / 'main.py'
add = r'''


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

    with get_session() as s:
        job = _wk_create_job(s, owner_email=owner_email, title=title, notes=notes)
        for f in files:
            data = await f.read()
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
        path = root / art.rel_path
        if not path.exists():
            return JSONResponse({'ok': False, 'error': 'file missing on disk'}, status_code=404)
        return FileResponse(path, filename=art.filename or path.name, media_type=art.content_type or 'application/octet-stream')


# ─────────────────────────────────────────────────────────────
# Doc import into Fubuki main chat
# ─────────────────────────────────────────────────────────────
from .services.doc_import_service import extract_text_from_upload


@app.post('/agent/fubuki/import_doc')
async def fubuki_import_doc(file: UploadFile = File(...), max_chars: int = Form(120_000)):
    data = await file.read()
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
'''

s = p.read_text(encoding='utf-8')
if 'Weekend Mode (batch upload scaffolding)' not in s:
    p.write_text(s + add, encoding='utf-8')
    print('appended')
else:
    print('already present')
