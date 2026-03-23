from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


WIKIDATA_API = "https://www.wikidata.org/w/api.php"


@dataclass
class WikidataCompany:
    qid: str
    label: str
    description: str
    industry_labels: list[str]
    website: str
    domains: list[str]


def _get(url: str, timeout_s: float = 10.0) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Sourceress/1.0 (+https://github.com/NerdHerderDani/sourceress)'
    })
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        raw = resp.read() or b''
    return json.loads(raw.decode('utf-8') or '{}') if raw else {}


def search_company_qid(name: str, limit: int = 3) -> list[dict[str, str]]:
    q = (name or '').strip()
    if not q:
        return []

    params = {
        'action': 'wbsearchentities',
        'search': q,
        'language': 'en',
        'format': 'json',
        'limit': int(limit),
        'type': 'item',
    }
    url = WIKIDATA_API + '?' + urllib.parse.urlencode(params)
    data = _get(url)
    out = []
    for it in (data.get('search') or []):
        if not isinstance(it, dict):
            continue
        out.append({
            'id': (it.get('id') or '').strip(),
            'label': (it.get('label') or '').strip(),
            'description': (it.get('description') or '').strip(),
        })
    return [x for x in out if x.get('id')]


def _extract_domain(website: str) -> str:
    try:
        u = urllib.parse.urlparse((website or '').strip())
        host = (u.netloc or '').strip().lower()
        if host.startswith('www.'):
            host = host[4:]
        return host
    except Exception:
        return ''


def fetch_company(qid: str) -> WikidataCompany | None:
    qid = (qid or '').strip()
    if not qid:
        return None

    # Pull claims and basic labels
    params = {
        'action': 'wbgetentities',
        'ids': qid,
        'props': 'labels|descriptions|claims',
        'languages': 'en',
        'format': 'json',
    }
    url = WIKIDATA_API + '?' + urllib.parse.urlencode(params)
    data = _get(url)

    ent = ((data.get('entities') or {}).get(qid) or {})
    label = (((ent.get('labels') or {}).get('en') or {}).get('value') or '').strip()
    desc = (((ent.get('descriptions') or {}).get('en') or {}).get('value') or '').strip()
    claims = ent.get('claims') or {}

    # Industry (P452) -> list of QIDs
    inds: list[str] = []
    try:
        for c in (claims.get('P452') or []):
            dv = (((c.get('mainsnak') or {}).get('datavalue') or {}).get('value') or {})
            iid = (dv.get('id') or '').strip()
            if iid:
                inds.append(iid)
    except Exception:
        inds = []

    # Official website (P856)
    website = ''
    try:
        c0 = (claims.get('P856') or [None])[0] or {}
        dv = (((c0.get('mainsnak') or {}).get('datavalue') or {}).get('value') or '')
        website = (dv or '').strip()
    except Exception:
        website = ''

    domains = []
    dom = _extract_domain(website)
    if dom:
        domains = [dom]

    # Resolve industry labels in one call
    industry_labels: list[str] = []
    if inds:
        params2 = {
            'action': 'wbgetentities',
            'ids': '|'.join(sorted(set(inds))[:50]),
            'props': 'labels',
            'languages': 'en',
            'format': 'json',
        }
        url2 = WIKIDATA_API + '?' + urllib.parse.urlencode(params2)
        data2 = _get(url2)
        ents2 = data2.get('entities') or {}
        for _id, e in ents2.items():
            if not isinstance(e, dict):
                continue
            v = (((e.get('labels') or {}).get('en') or {}).get('value') or '').strip()
            if v:
                industry_labels.append(v)
        industry_labels = sorted(set(industry_labels))

    return WikidataCompany(
        qid=qid,
        label=label or qid,
        description=desc,
        industry_labels=industry_labels,
        website=website,
        domains=domains,
    )


def enrich_company_by_name(name: str) -> WikidataCompany | None:
    hits = search_company_qid(name, limit=3)
    if not hits:
        return None

    # Pick first hit (MVP). Later: allow user choose.
    qid = hits[0]['id']
    return fetch_company(qid)
