from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import SQLModel, Field


class SavedSearch(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow, index=True)

    name: str = Field(index=True)
    query: str
    repo_seeds: str = ""
    location: str = ""
    min_followers: int = 0
    active_days: int = 180
    min_contribs: int = 0
    max_contribs: int = 0

    location_include: str = ""
    location_exclude: str = ""
    company_include: str = ""
    company_exclude: str = ""
