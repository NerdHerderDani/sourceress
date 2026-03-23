from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import SQLModel, Field, Column, JSON


class ProjectEntity(SQLModel, table=True):
    """A source-agnostic item in a project pipeline.

    Examples:
    - github: external_id=login
    - stack: external_id=stack user id
    - openalex: external_id=openalex author id
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow, index=True)

    project_id: int = Field(index=True, foreign_key="project.id")

    source: str = Field(default="github", index=True)  # github|stack|openalex|linkedin|...
    external_id: str = Field(index=True)

    display_name: str = ""
    url: str = ""

    summary_json: dict = Field(default_factory=dict, sa_column=Column(JSON))

    status: str = Field(default="new", index=True)  # new|contacted|pass
    note: str = ""
