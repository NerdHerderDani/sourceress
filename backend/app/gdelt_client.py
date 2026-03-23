from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import json
import urllib.parse
import urllib.request


GDELT_DOC_API = "https://api.gdeltproject.org/api/v2/doc/doc"


@dataclass
class GdeltResult:
    count: int
    articles: list[dict[str, Any]]
    query: str
    start: str
    end: str


def _fmt_dt(dt: datetime) -> str:
    # GDELT wants YYYYMMDDHHMMSS in UTC
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime('%Y%m%d%H%M%S')


def fetch_doc_list(query: str, days: int = 90, limit: int = 10, timeout_s: float = 10.0) -> GdeltResult:
    """Fetch a count + recent article list from GDELT 2.1 DOC API.

    Uses mode=ArtList which includes an article list plus a total count.
    """
    q = (query or '').strip()
    if not q:
        return GdeltResult(count=0, articles=[], query=q, start='', end='')

    end_dt = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=max(1, int(days)))

    params = {
        'query': q,
        'mode': 'ArtList',
        'format': 'json',
        'maxrecords': int(limit),
        'startdatetime': _fmt_dt(start_dt),
        'enddatetime': _fmt_dt(end_dt),
        # Sort newest first
        'sort': 'HybridRel',
    }

    url = GDELT_DOC_API + '?' + urllib.parse.urlencode(params)

    req = urllib.request.Request(url, headers={
        'User-Agent': 'Sourceress/1.0 (+https://github.com/NerdHerderDani/sourceress)'
    })
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        raw = resp.read() or b''

    data = json.loads(raw.decode('utf-8') or '{}') if raw else {}

    count = 0
    if isinstance(data, dict):
        count = int(data.get('totalArticles') or data.get('totalarticles') or 0)

    arts = []
    raw = data.get('articles') if isinstance(data, dict) else None
    if isinstance(raw, list):
        for a in raw:
            if not isinstance(a, dict):
                continue
            arts.append({
                'title': a.get('title') or '',
                'url': a.get('url') or '',
                'sourceCountry': a.get('sourceCountry') or '',
                'sourceCollection': a.get('sourceCollection') or '',
                'seendate': a.get('seendate') or a.get('seenDate') or '',
                'domain': a.get('domain') or '',
            })

    return GdeltResult(
        count=count,
        articles=arts,
        query=q,
        start=_fmt_dt(start_dt),
        end=_fmt_dt(end_dt),
    )
