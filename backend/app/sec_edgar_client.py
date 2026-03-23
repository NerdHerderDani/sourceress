from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


SEC_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"


def _get_json(url: str, timeout_s: float = 12.0) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={
        # SEC asks for a descriptive UA with contact
        'User-Agent': 'Sourceress/1.0 (recruiting signals; contact: dev@local)'
    })
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        raw = resp.read() or b''
    return json.loads(raw.decode('utf-8') or '{}') if raw else {}


def norm_cik(cik_or_ticker: str) -> str:
    """Return 10-digit zero-padded CIK if possible.

    Accepts raw digits, with/without CIK prefix. (Ticker lookup is not implemented.)
    """
    s = (cik_or_ticker or '').strip().upper()
    if not s:
        return ''

    # Extract digits
    m = re.search(r'(\d{1,10})', s)
    if not m:
        return ''

    cik = m.group(1)
    return cik.zfill(10)


@dataclass
class SecFilingsSummary:
    cik: str
    name: str
    tickers: list[str]
    sic: str
    sic_description: str
    state: str
    recent: list[dict[str, Any]]


def fetch_company_submissions(cik: str) -> SecFilingsSummary | None:
    cik10 = norm_cik(cik)
    if not cik10:
        return None

    url = SEC_SUBMISSIONS.format(cik=cik10)
    data = _get_json(url)

    name = (data.get('name') or '').strip()
    tickers = data.get('tickers') or []
    if not isinstance(tickers, list):
        tickers = []

    sic = str(data.get('sic') or '').strip()
    sic_desc = str(data.get('sicDescription') or '').strip()
    state = str(data.get('stateOfIncorporation') or '').strip()

    recent = []
    try:
        r = (((data.get('filings') or {}).get('recent')) or {})
        forms = r.get('form') or []
        dates = r.get('filingDate') or []
        acc = r.get('accessionNumber') or []
        prim = r.get('primaryDocument') or []

        n = min(len(forms), len(dates), len(acc), len(prim))
        for i in range(n):
            f = (forms[i] or '').strip()
            d = (dates[i] or '').strip()
            a = (acc[i] or '').strip()
            p = (prim[i] or '').strip()
            if not (f and d and a):
                continue
            # doc URL pattern
            # https://www.sec.gov/Archives/edgar/data/{CIK without leading zeros}/{accession no dashes}/{primaryDoc}
            cik_int = str(int(cik10))
            a_nodash = a.replace('-', '')
            doc_url = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{a_nodash}/{p}"
            recent.append({
                'form': f,
                'filingDate': d,
                'accession': a,
                'url': doc_url,
            })
    except Exception:
        recent = []

    return SecFilingsSummary(
        cik=cik10,
        name=name,
        tickers=[t for t in tickers if isinstance(t, str)],
        sic=sic,
        sic_description=sic_desc,
        state=state,
        recent=recent[:25],
    )
