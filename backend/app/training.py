from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import SQLModel, Field


class CandidateFeedback(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)

    run_id: int = Field(index=True, foreign_key="searchrun.id")
    login: str = Field(index=True, foreign_key="candidate.login")

    label: int = Field(index=True)  # +1 good, -1 bad
    note: str = ""
