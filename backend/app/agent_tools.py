from __future__ import annotations

import csv
from io import StringIO

from fastapi import Request
from fastapi.responses import JSONResponse

from .company_signals import Company, upsert_company
from .comp_bands import CompanyCompBand
from .db import get_session


def _to_int(x: str) -> int:
    x = (x or '').strip().replace(',', '').replace('$', '')
    if not x:
        return 0
    try:
        return int(float(x))
    except Exception:
        return 0


def agent_company_upsert(payload: dict):
    name = (payload.get('name') or '').strip()
    if not name:
        return None, 'missing name'

    tags = (payload.get('tags') or '').strip()
    github_org_url = (payload.get('github_org_url') or '').strip()
    linkedin_company_url = (payload.get('linkedin_company_url') or '').strip()
    jobs_url = (payload.get('jobs_url') or '').strip()

    with get_session() as s:
        c = upsert_company(s, name, origin='manual')
        if not c:
            return None, 'invalid company'
        if tags:
            c.tags = tags
        if github_org_url:
            c.github_org_url = github_org_url
        if linkedin_company_url:
            c.linkedin_company_url = linkedin_company_url
        if jobs_url:
            c.jobs_url = jobs_url
        s.add(c)
        s.commit()
        s.refresh(c)

    return c, None


def agent_comp_import_csv(payload: dict):
    company_name = (payload.get('company_name') or '').strip()
    dept = (payload.get('dept') or 'engineering').strip().lower() or 'engineering'
    csv_text = (payload.get('csv_text') or '').strip()
    source_url = (payload.get('source_url') or '').strip()

    if not company_name:
        return 0, 'missing company_name'
    if not csv_text:
        return 0, 'missing csv_text'

    with get_session() as s:
        c = upsert_company(s, company_name, origin='manual')
        if not c:
            return 0, 'invalid company'
        cid = c.id

        # parse CSV (comma or tab)
        first = csv_text.splitlines()[0] if csv_text.splitlines() else ''
        delim = '\t' if '\t' in first else ','
        reader = csv.reader(StringIO(csv_text), delimiter=delim)
        rows = [r for r in reader if r and any((x or '').strip() for x in r)]
        if not rows:
            return 0, 'no rows'

        hdr = [c.strip().lower() for c in rows[0]]
        has_header = any(x in hdr for x in ('role','title','level','location','low','mid','high','bonus','equity','currency'))
        data_rows = rows[1:] if has_header else rows

        def idx(*names):
            for n in names:
                if n in hdr:
                    return hdr.index(n)
            return -1

        i_role = idx('role','title')
        i_level = idx('level')
        i_loc = idx('location')
        i_low = idx('low','min','base')
        i_mid = idx('mid','median','p50')
        i_high = idx('high','max')
        i_bonus = idx('bonus')
        i_equity = idx('equity','stock')
        i_cur = idx('currency')

        def g(r, i):
            if i < 0 or i >= len(r):
                return ''
            return (r[i] or '').strip()

        added = 0
        for r in data_rows:
            role = g(r, i_role) if i_role >= 0 else ((r[0] or '').strip() if r else '')
            if not role:
                continue
            level = g(r, i_level)
            loc = g(r, i_loc)
            cur = g(r, i_cur) or 'USD'

            low = _to_int(g(r, i_low))
            mid = _to_int(g(r, i_mid))
            high = _to_int(g(r, i_high))
            bonus = _to_int(g(r, i_bonus))
            equity = _to_int(g(r, i_equity))

            s.add(CompanyCompBand(
                company_id=cid,
                dept=dept,
                role=role,
                level=level,
                location=loc,
                currency=cur,
                low=low,
                mid=mid,
                high=high,
                bonus=bonus,
                equity=equity,
                source_url=source_url,
            ))
            added += 1

        s.commit()

    return added, None
