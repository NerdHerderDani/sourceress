from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import SQLModel, Field, Column, JSON


def norm_company_name(s: str) -> str:
    """Very lightweight normalization; good enough for MVP.

    We can improve later with alias tables + domain matching.
    """
    s = (s or '').strip().lower()
    if not s:
        return ''

    # Common noise
    for suf in [
        ', inc.', ' inc.', ' inc',
        ', llc', ' llc',
        ', ltd', ' ltd',
        ' corp', ' corporation',
        ' co.', ' company',
    ]:
        if s.endswith(suf):
            s = s[: -len(suf)].strip()

    # Collapse whitespace
    s = ' '.join(s.split())
    return s


class Company(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow, index=True)

    name: str = Field(default='', index=True)
    norm_name: str = Field(default='', index=True)

    # manual|candidate
    origin: str = Field(default='manual', index=True)

    # Optional enrichment
    wikidata_id: str = Field(default='', index=True)
    sec_cik: str = Field(default='', index=True)
    industry_tags: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    domains: list[str] = Field(default_factory=list, sa_column=Column(JSON))

    # Demo/practical links
    github_org_url: str = Field(default='')
    linkedin_company_url: str = Field(default='')
    jobs_url: str = Field(default='')

    notes: str = Field(default='')

    # Manual compensation notes/bands
    # Example: {"SWE": {"low": 180000, "mid": 230000, "high": 300000, "notes": "SF Bay"}}
    comp_json: dict = Field(default_factory=dict, sa_column=Column(JSON))


class CompanySignal(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)

    company_id: int = Field(index=True, foreign_key='company.id')

    # gdelt|edgar|manual|etc
    source: str = Field(default='manual', index=True)

    # layoffs|funding|comp|etc
    signal_type: str = Field(default='', index=True)

    value_json: dict = Field(default_factory=dict, sa_column=Column(JSON))
    url: str = Field(default='')


def upsert_company(session, name: str, origin: str = 'manual') -> Company | None:
    nm = (name or '').strip()
    if not nm:
        return None
    nn = norm_company_name(nm)
    if not nn:
        return None

    from sqlmodel import select

    c = session.exec(select(Company).where(Company.norm_name == nn)).first()
    if c:
        # Keep the nicer display name if existing is empty
        if not (c.name or '').strip():
            c.name = nm
        c.updated_at = datetime.utcnow()
        session.add(c)
        session.commit()
        session.refresh(c)
        return c

    c = Company(name=nm, norm_name=nn, origin=(origin or 'manual'))
    session.add(c)
    session.commit()
    session.refresh(c)
    return c
