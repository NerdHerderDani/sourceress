from __future__ import annotations

from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field, Column, JSON

# keep extra tables in separate modules to avoid clutter
from .training import CandidateFeedback  # noqa: F401
from .saved_searches import SavedSearch  # noqa: F401
from .projects import Project, ProjectCandidate  # noqa: F401
from .project_entity import ProjectEntity  # noqa: F401
from .user_secret_model import UserSecret  # noqa: F401
from .experience import CandidateExperience  # noqa: F401

class SearchRun(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)

    # Auth / ownership (for per-user GitHub token)
    owner_email: str = Field(default="", index=True)

    # github | stack
    source: str = Field(default="github", index=True)

    raw_query: str
    repo_seeds: str = ""  # github: comma-separated owner/repo and/or GitHub URLs

    # github filters
    location: str = ""
    min_followers: int = 0
    active_days: int = 180
    min_contribs: int = 0
    max_contribs: int = 0

    location_include: str = ""
    location_exclude: str = ""
    company_include: str = ""
    company_exclude: str = ""

    # stack filters (MVP)
    stack_tags: str = ""  # comma-separated tags
    stack_match: str = "any"  # any|all
    min_rep: int = 0
    min_answers: int = 0

    status: str = Field(default="queued", index=True)  # queued|running|done|error
    processed: int = 0
    total: int = 0
    error: str = ""

class Candidate(SQLModel, table=True):
    login: str = Field(primary_key=True)
    html_url: str = ""
    avatar_url: str = ""
    name: str = ""
    company: str = ""
    location: str = ""
    bio: str = ""
    followers: int = 0

    # Contact (best-effort; may be blank)
    email: str = ""
    email_source: str = ""  # profile|commit|none

    # Snapshot of enrichment data (repos, languages, etc.)
    profile_json: dict = Field(default_factory=dict, sa_column=Column(JSON))

class CandidateScore(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: int = Field(index=True, foreign_key="searchrun.id")
    login: str = Field(index=True, foreign_key="candidate.login")

    score: float = 0.0
    reasons: list[str] = Field(default_factory=list, sa_column=Column(JSON))
