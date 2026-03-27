from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import SQLModel, Field


class WeekendJob(SQLModel, table=True):
    """Weekend Mode batch job metadata.

    Stores uploads/extracted artifacts and (optionally) an Anthropic Batch API
    submission.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)

    # Future auth/ownership (blank for now when unauthenticated)
    owner_email: str = Field(default="", index=True)

    title: str = Field(default="")
    notes: str = Field(default="")

    status: str = Field(default="queued", index=True)  # queued|processing|done|error
    error: str = Field(default="")

    # Anthropic Batch API (optional)
    anthropic_batch_id: str = Field(default="", index=True)
    anthropic_batch_status: str = Field(default="", index=True)
    anthropic_model: str = Field(default="")
    anthropic_submitted_at: Optional[datetime] = Field(default=None, index=True)
    anthropic_completed_at: Optional[datetime] = Field(default=None, index=True)

    # quick stats
    upload_count: int = Field(default=0)
    extracted_count: int = Field(default=0)
    result_count: int = Field(default=0)


class WeekendArtifact(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)

    job_id: int = Field(index=True, foreign_key="weekendjob.id")

    kind: str = Field(default="upload", index=True)  # upload|extracted|result
    filename: str = Field(default="")
    rel_path: str = Field(default="")  # relative to backend/data/weekend_jobs/<job_id>/
    size_bytes: int = Field(default=0)
    sha256: str = Field(default="")
    content_type: str = Field(default="")
