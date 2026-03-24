from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import SQLModel, Field


class CompanyCompBand(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)

    company_id: int = Field(index=True, foreign_key='company.id')

    # Department/category used for benchmarking (engineering|product|marketing|sales|design|data|other)
    dept: str = Field(default='engineering', index=True)

    role: str = Field(default='', index=True)
    level: str = Field(default='', index=True)
    location: str = Field(default='', index=True)
    currency: str = Field(default='USD', index=True)

    # store as ints when possible
    low: int = 0
    mid: int = 0
    high: int = 0

    # Optional components (annualized, best-effort)
    bonus: int = 0
    equity: int = 0

    source_url: str = Field(default='')
    notes: str = Field(default='')
