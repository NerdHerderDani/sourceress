from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import SQLModel, Field


class Project(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow, index=True)

    name: str = Field(index=True)
    notes: str = ""


class ProjectCandidate(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)

    project_id: int = Field(index=True, foreign_key="project.id")
    login: str = Field(index=True, foreign_key="candidate.login")
    note: str = ""

    # lightweight pipeline
    status: str = Field(default="new", index=True)  # new|contacted|pass
