from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import httpx
from sqlmodel import Session, select

from ..weekend_jobs_model import WeekendArtifact, WeekendJob
from .doc_import_service import extract_text_from_upload
from .weekend_jobs_service import job_root, add_result_artifact


ANTHROPIC_BATCH_URL = "https://api.anthropic.com/v1/messages/batches"

# Prefer env override so prod/dev can pin whatever Anthropic model is available.
DEFAULT_MODEL = (os.environ.get("ANTHROPIC_MODEL") or "").strip() or "claude-sonnet-4-6"


def _api_key(override: str | None = None) -> str:
    if override and override.strip():
        return override.strip()
    return (os.environ.get("ANTHROPIC_API_KEY") or "").strip()


def _headers(api_key: str) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }


def _iter_target_artifacts(session: Session, job_id: int) -> list[WeekendArtifact]:
    """Prefer extracted artifacts if present; else fall back to uploads."""
    extracted = list(
        session.exec(
            select(WeekendArtifact).where(WeekendArtifact.job_id == job_id, WeekendArtifact.kind == "extracted")
        ).all()
    )
    if extracted:
        return extracted

    return list(
        session.exec(
            select(WeekendArtifact).where(WeekendArtifact.job_id == job_id, WeekendArtifact.kind == "upload")
        ).all()
    )


def _artifact_text(root: Path, art: WeekendArtifact, *, max_chars: int = 120_000) -> str:
    path = root / (art.rel_path or "")
    if not path.exists():
        return ""

    data = path.read_bytes()

    text = ""
    try:
        text = extract_text_from_upload(art.filename or path.name, data)
    except Exception:
        # Best-effort: try to decode bytes as UTF-8.
        try:
            text = data.decode("utf-8", errors="replace")
        except Exception:
            text = ""

    text = (text or "").strip()
    if max_chars and len(text) > int(max_chars):
        text = text[: int(max_chars)]
    return text


def build_weekend_batch_payload(
    *,
    job: WeekendJob,
    artifacts: Iterable[WeekendArtifact],
    root: Path,
    model: str,
    system_prompt: str,
    max_tokens: int = 1200,
) -> dict[str, Any]:
    """Build the JSON payload for POST /v1/messages/batches.

    Note: Anthropic prompt caching (cache_control) is included on the system prompt.
    """

    reqs: list[dict[str, Any]] = []

    for art in artifacts:
        txt = _artifact_text(root, art)
        if not txt:
            continue

        user_text = (
            "You are processing a Weekend Mode job in Sourceress.\n\n"
            f"Job ID: {job.id}\n"
            f"Filename: {art.filename}\n\n"
            "---\n"
            f"{txt}\n"
            "---\n\n"
            "Task: Produce a concise structured JSON summary with keys: "
            "{filename, doc_type_guess, entities, key_points, action_items}. "
            "entities should include people/companies/roles if present."
        )

        params = {
            "model": model,
            "max_tokens": int(max_tokens),
            "system": [
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": user_text}],
                }
            ],
        }

        reqs.append(
            {
                "custom_id": f"job{job.id}:artifact{art.id}",
                "params": params,
            }
        )

    return {"requests": reqs}


def submit_batch(
    session: Session,
    *,
    job_id: int,
    api_key: str | None = None,
    model: str | None = None,
    max_tokens: int = 1200,
) -> WeekendJob:
    key = _api_key(api_key)
    if not key:
        raise RuntimeError("Missing ANTHROPIC_API_KEY (env var) and no per-request key provided")

    job = session.get(WeekendJob, job_id)
    if not job:
        raise RuntimeError("job not found")

    if (job.anthropic_batch_id or "").strip():
        # idempotency: do not submit twice
        return job

    root = job_root(job_id)
    artifacts = _iter_target_artifacts(session, job_id)

    system_prompt = (
        "You are Sourceress Weekend Mode. Return ONLY valid JSON and no surrounding text. "
        "If the document is not useful, return {\"skip\": true, \"reason\": \"...\"}."
    )

    mdl = (model or "").strip() or DEFAULT_MODEL
    payload = build_weekend_batch_payload(
        job=job,
        artifacts=artifacts,
        root=root,
        model=mdl,
        system_prompt=system_prompt,
        max_tokens=max_tokens,
    )

    if not payload.get("requests"):
        raise RuntimeError("No readable artifacts to submit (supported: .txt, .md, .pdf, .docx; or UTF-8 text)")

    with httpx.Client(timeout=60.0) as client:
        r = client.post(ANTHROPIC_BATCH_URL, headers=_headers(key), json=payload)
        if r.status_code >= 400:
            raise RuntimeError(f"Anthropic Batch API error {r.status_code}: {r.text}")
        data = r.json() if r.content else {}

    batch_id = (data.get("id") if isinstance(data, dict) else "") or ""
    if not batch_id:
        raise RuntimeError(f"Unexpected Anthropic batch response: missing id. keys={list(data.keys()) if isinstance(data, dict) else type(data)}")

    job.anthropic_batch_id = batch_id
    job.anthropic_batch_status = (data.get("processing_status") or data.get("status") or "submitted")
    job.anthropic_model = mdl
    job.anthropic_submitted_at = datetime.utcnow()
    job.status = "processing"
    job.error = ""
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def poll_batch(session: Session, *, job_id: int, api_key: str | None = None) -> dict[str, Any]:
    """Poll Anthropic for batch state; if complete, ingest results into WeekendArtifact(s)."""
    key = _api_key(api_key)
    if not key:
        raise RuntimeError("Missing ANTHROPIC_API_KEY env var")

    job = session.get(WeekendJob, job_id)
    if not job:
        raise RuntimeError("job not found")

    bid = (job.anthropic_batch_id or "").strip()
    if not bid:
        raise RuntimeError("job has no anthropic_batch_id")

    with httpx.Client(timeout=60.0) as client:
        r = client.get(f"{ANTHROPIC_BATCH_URL}/{bid}", headers=_headers(key))
        if r.status_code >= 400:
            raise RuntimeError(f"Anthropic Batch API error {r.status_code}: {r.text}")
        info = r.json() if r.content else {}

    status = (info.get("processing_status") or info.get("status") or "") if isinstance(info, dict) else ""
    job.anthropic_batch_status = status or job.anthropic_batch_status
    session.add(job)
    session.commit()

    # Determine completion.
    done_states = {"ended", "completed", "complete", "succeeded", "failed", "errored", "canceled", "cancelled"}
    if status and status.lower() in done_states:
        ingest_batch_results(session, job_id=job_id, api_key=key)
        session.refresh(job)

    return {"batch": info, "job": job.model_dump()}


def ingest_batch_results(session: Session, *, job_id: int, api_key: str) -> None:
    job = session.get(WeekendJob, job_id)
    if not job:
        raise RuntimeError("job not found")

    bid = (job.anthropic_batch_id or "").strip()
    if not bid:
        raise RuntimeError("job has no anthropic_batch_id")

    # Avoid duplicating results ingestion.
    existing = session.exec(
        select(WeekendArtifact).where(WeekendArtifact.job_id == job_id, WeekendArtifact.kind == "result")
    ).first()
    if existing:
        return

    with httpx.Client(timeout=60.0) as client:
        r = client.get(f"{ANTHROPIC_BATCH_URL}/{bid}/results", headers=_headers(api_key))
        if r.status_code >= 400:
            raise RuntimeError(f"Anthropic Batch results error {r.status_code}: {r.text}")

        # Results are typically JSONL; treat as bytes.
        raw = r.content or b""

    # Store the raw jsonl.
    add_result_artifact(
        session,
        job_id=job_id,
        filename="anthropic_results.jsonl",
        content_type="application/jsonl",
        data=raw,
    )

    # Best-effort: parse JSONL to compute success/error summary.
    succeeded = 0
    errored = 0
    skipped = 0

    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue

        res = obj.get("result") if isinstance(obj, dict) else None
        if not isinstance(res, dict):
            continue

        rtype = (res.get("type") or "").lower()
        if rtype in ("succeeded", "success"):
            succeeded += 1
        elif rtype in ("errored", "error", "failed"):
            errored += 1
        else:
            skipped += 1

    job.anthropic_completed_at = datetime.utcnow()
    if errored:
        job.status = "error"
        job.error = f"Batch completed with errors. succeeded={succeeded} errored={errored} other={skipped}"
    else:
        job.status = "done"
        job.error = ""

    # update result_count
    job.result_count = session.exec(
        select(WeekendArtifact).where(WeekendArtifact.job_id == job_id, WeekendArtifact.kind == "result")
    ).count()

    session.add(job)
    session.commit()
