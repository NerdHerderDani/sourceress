from __future__ import annotations

from datetime import datetime, date
from typing import Optional
import re

from sqlmodel import SQLModel, Field, Column, JSON


class CandidateExperience(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)

    login: str = Field(index=True, foreign_key="candidate.login")
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)

    # provenance
    source: str = Field(default="linkedin_paste", index=True)
    raw_text: str = ""

    company: str = ""
    title: str = ""
    location: str = ""

    start_date: Optional[date] = Field(default=None, index=True)
    end_date: Optional[date] = Field(default=None, index=True)  # null means Present/unknown

    bullets: list[str] = Field(default_factory=list, sa_column=Column(JSON))


_MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}


def _parse_month_year(s: str) -> Optional[date]:
    s = (s or "").strip()
    if not s:
        return None
    if re.fullmatch(r"\d{4}", s):
        return date(int(s), 1, 1)
    m = re.match(r"^([A-Za-z]{3,9})\s+(\d{4})$", s)
    if m:
        mon = _MONTHS.get(m.group(1).lower())
        if mon:
            return date(int(m.group(2)), mon, 1)
    return None


def _parse_range(line: str) -> tuple[Optional[date], Optional[date]]:
    """Parse date ranges like:
    - Jul 2024 - Present
    - May 2023 – May 2024
    - 2020 - 2021
    """
    t = (line or "").strip()
    if not t:
        return None, None

    # normalize dashes
    t = t.replace("—", "-").replace("–", "-")

    if "-" not in t:
        return None, None

    left, right = [x.strip() for x in t.split("-", 1)]

    start = _parse_month_year(left)

    end: Optional[date]
    if right.lower().startswith("present") or right.lower().startswith("current"):
        end = None
    else:
        end = _parse_month_year(right)

    return start, end


def parse_linkedin_experience_paste(raw_text: str) -> tuple[list[dict], list[str]]:
    """Best-effort parser for pasted LinkedIn experience sections.

    Returns (items, warnings)
    items: [{title, company, location, start_date, end_date, bullets, raw_text}]
    """
    text = (raw_text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    warnings: list[str] = []
    if not text:
        return [], ["empty paste"]

    lines = [ln.strip() for ln in text.split("\n")]
    # drop empty runs
    norm: list[str] = []
    for ln in lines:
        if ln:
            norm.append(ln)
    lines = norm

    # Heuristic: start a new entry when we see a likely date range line.
    # We'll include a couple of lines before it as header.
    date_pat = re.compile(r"(?i)(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|january|february|march|april|june|july|august|september|october|november|december|\b\d{4}\b).*\s-\s*(?:present|current|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|january|february|march|april|june|july|august|september|october|november|december|\b\d{4}\b)")

    idxs = [i for i, ln in enumerate(lines) if date_pat.search(ln.replace("–", "-").replace("—", "-"))]
    if not idxs:
        # fall back to a single block
        idxs = [len(lines)]

    # Build chunks ending at each date line; include surrounding lines
    chunks: list[list[str]] = []
    start_i = 0
    for di in idxs:
        # if di is a date line index, close chunk at next date line
        if di < len(lines):
            # keep chunk up through date line
            chunk = lines[start_i : di + 1]
            chunks.append(chunk)
            start_i = di + 1
        else:
            chunk = lines[start_i:]
            if chunk:
                chunks.append(chunk)

    items: list[dict] = []

    for cix, chunk in enumerate(chunks):
        if not chunk:
            continue

        # Find date line inside chunk (last line matching date pattern)
        date_line = None
        for ln in reversed(chunk):
            if date_pat.search(ln.replace("–", "-").replace("—", "-")):
                date_line = ln
                break

        start_date, end_date = _parse_range(date_line or "")

        # Remove date line from header candidates
        hdr = [ln for ln in chunk if ln != date_line]

        bullets: list[str] = []
        header_lines: list[str] = []
        for ln in hdr:
            if ln.startswith(("•", "-", "*")):
                bullets.append(ln.lstrip("•-* ").strip())
            else:
                header_lines.append(ln)

        title = ""
        company = ""
        location = ""

        # Common paste order: title, company, (location), bullets
        if header_lines:
            title = header_lines[0]
        if len(header_lines) >= 2:
            company = header_lines[1]
        if len(header_lines) >= 3:
            # crude guess: if it contains a comma or common geo words, treat as location
            if any(x in header_lines[2].lower() for x in (",", "united", "states", "remote", "city", "area")):
                location = header_lines[2]

        if not (title or company or bullets):
            warnings.append(f"could not parse entry {cix+1}")
            continue

        items.append(
            {
                "title": title.strip(),
                "company": company.strip(),
                "location": location.strip(),
                "start_date": start_date,
                "end_date": end_date,
                "bullets": [b for b in bullets if b],
                "raw_text": "\n".join(chunk).strip(),
            }
        )

        if date_line and start_date is None:
            warnings.append(f"could not parse start date in entry {cix+1}: '{date_line}'")

    if not items:
        warnings.append("no entries parsed")

    return items, warnings


def month_diff(a: date, b: date) -> int:
    return (b.year - a.year) * 12 + (b.month - a.month)


def compute_experience_stats(items: list[dict], today: Optional[date] = None) -> dict:
    """Compute total experience / current tenure / average tenure.

    items expects start_date/end_date (None end_date => present)
    """
    today = today or date.today()

    spans: list[tuple[date, date]] = []
    for it in items:
        sd: Optional[date] = it.get("start_date")
        ed: Optional[date] = it.get("end_date")
        if not sd:
            continue
        end = ed or today
        if end < sd:
            continue
        spans.append((sd, end))

    total_months = 0
    if spans:
        earliest = min(sd for sd, _ in spans)
        total_months = max(0, month_diff(earliest, today))

    # current tenure: pick most recent "present" role if available else most recent end
    current_months = 0
    present = [it for it in items if it.get("start_date") and it.get("end_date") is None]
    if present:
        sd = max(it["start_date"] for it in present)
        current_months = max(0, month_diff(sd, today))
    else:
        # fallback to most recent span
        if spans:
            sd, _ = max(spans, key=lambda t: t[1])
            current_months = max(0, month_diff(sd, today))

    # average tenure: average per role months, require both dates (or present)
    tenure_months: list[int] = []
    for sd, ed in spans:
        m = max(0, month_diff(sd, ed))
        if m:
            tenure_months.append(m)
    avg_months = int(round(sum(tenure_months) / len(tenure_months))) if tenure_months else 0

    return {
        "total_months": total_months,
        "current_months": current_months,
        "avg_months": avg_months,
    }


def fmt_months(m: int) -> str:
    yrs = m // 12
    mos = m % 12
    parts = []
    if yrs:
        parts.append(f"{yrs} yr" + ("s" if yrs != 1 else ""))
    if mos or not parts:
        parts.append(f"{mos} mo" + ("s" if mos != 1 else ""))
    return " ".join(parts)
