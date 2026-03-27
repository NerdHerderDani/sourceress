from __future__ import annotations

import hashlib
import os
import re
import zipfile
from pathlib import Path
from typing import Iterable, Tuple

from sqlmodel import Session, select

from ..weekend_jobs_model import WeekendJob, WeekendArtifact


_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._ -]+")


def _safe_name(name: str) -> str:
    name = (name or "").strip()
    name = name.replace("\\", "/").split("/")[-1]
    name = _SAFE_NAME_RE.sub("_", name)
    return name[:180] or "file"


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _data_root() -> Path:
    """Return a writable base data directory.

    Prefer %APPDATA%\Sourceress\data on Windows; fall back to ./data.
    """
    try:
        appdata = (os.environ.get('APPDATA') or '').strip()
        if appdata:
            return Path(appdata) / 'Sourceress' / 'data'
    except Exception:
        pass
    return Path('data')


def job_root(job_id: int) -> Path:
    root = _data_root() / "weekend_jobs" / str(job_id)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _write_upload_bytes(job_id: int, filename: str, data: bytes) -> Tuple[Path, int, str]:
    root = job_root(job_id)
    up = root / "uploads"
    up.mkdir(parents=True, exist_ok=True)

    fn = _safe_name(filename)
    # Avoid overwrite collisions
    out = up / fn
    if out.exists():
        stem = out.stem
        suf = out.suffix
        i = 2
        while True:
            cand = up / f"{stem}__{i}{suf}"
            if not cand.exists():
                out = cand
                break
            i += 1

    out.write_bytes(data)
    size = out.stat().st_size
    sha = _sha256_file(out)
    return out, int(size), sha


def create_job(session: Session, *, owner_email: str = "", title: str = "", notes: str = "") -> WeekendJob:
    job = WeekendJob(owner_email=owner_email or "", title=title or "", notes=notes or "", status="queued")
    session.add(job)
    session.commit()
    session.refresh(job)
    job_root(job.id)
    return job


def add_upload_artifact(
    session: Session,
    *,
    job_id: int,
    filename: str,
    content_type: str,
    data: bytes,
) -> WeekendArtifact:
    path, size, sha = _write_upload_bytes(job_id, filename, data)
    rel = str(path.relative_to(job_root(job_id))).replace("\\", "/")

    art = WeekendArtifact(
        job_id=job_id,
        kind="upload",
        filename=path.name,
        rel_path=rel,
        size_bytes=size,
        sha256=sha,
        content_type=content_type or "",
    )
    session.add(art)
    session.commit()
    session.refresh(art)
    return art


def _extract_zip_safe(zip_path: Path, dest_dir: Path) -> list[Path]:
    """Extract zip contents to dest_dir, preventing path traversal.

    Extra-paranoid safeguards:
    - cap number of extracted files
    - cap total uncompressed bytes
    - cap per-file uncompressed bytes
    - stream copy (no "read entire file" into memory)
    """

    MAX_FILES = 250
    MAX_TOTAL_UNCOMPRESSED = 100 * 1024 * 1024  # 100 MiB
    MAX_MEMBER_UNCOMPRESSED = 25 * 1024 * 1024  # 25 MiB

    dest_dir.mkdir(parents=True, exist_ok=True)
    out: list[Path] = []
    total = 0

    with zipfile.ZipFile(zip_path, "r") as z:
        for info in z.infolist():
            if info.is_dir():
                continue

            # Hard caps first
            if len(out) >= MAX_FILES:
                break
            try:
                usize = int(getattr(info, 'file_size', 0) or 0)
            except Exception:
                usize = 0
            if usize <= 0:
                continue
            if usize > MAX_MEMBER_UNCOMPRESSED:
                continue
            if (total + usize) > MAX_TOTAL_UNCOMPRESSED:
                break

            # normalize zip internal path
            name = info.filename.replace("\\", "/")
            name = name.lstrip("/")
            # Disallow absolute paths and traversal
            if ".." in name.split("/"):
                continue
            # Only keep basename (flatten) to keep it simple for now
            base = _safe_name(name.split("/")[-1])
            if not base:
                continue

            target = dest_dir / base
            if target.exists():
                stem = target.stem
                suf = target.suffix
                i = 2
                while True:
                    cand = dest_dir / f"{stem}__{i}{suf}"
                    if not cand.exists():
                        target = cand
                        break
                    i += 1

            # Stream copy with a max size guard.
            copied = 0
            with z.open(info, "r") as src, target.open("wb") as dst:
                while True:
                    chunk = src.read(1024 * 1024)
                    if not chunk:
                        break
                    dst.write(chunk)
                    copied += len(chunk)
                    if copied > MAX_MEMBER_UNCOMPRESSED:
                        # abort oversized member
                        try:
                            dst.close()
                        except Exception:
                            pass
                        try:
                            target.unlink(missing_ok=True)
                        except Exception:
                            pass
                        copied = 0
                        break

            if copied <= 0:
                continue

            out.append(target)
            total += copied

    return out


def expand_zip_uploads(session: Session, *, job_id: int) -> int:
    """If any upload artifacts are zips, extract them and create extracted artifacts."""

    root = job_root(job_id)
    exdir = root / "extracted"
    exdir.mkdir(parents=True, exist_ok=True)

    arts = session.exec(
        select(WeekendArtifact).where(WeekendArtifact.job_id == job_id, WeekendArtifact.kind == "upload")
    ).all()

    created = 0
    for a in arts:
        if not a.filename.lower().endswith(".zip"):
            continue
        zip_path = root / a.rel_path
        if not zip_path.exists():
            continue
        extracted = _extract_zip_safe(zip_path, exdir)
        for p in extracted:
            size = p.stat().st_size
            sha = _sha256_file(p)
            rel = str(p.relative_to(root)).replace("\\", "/")
            art = WeekendArtifact(
                job_id=job_id,
                kind="extracted",
                filename=p.name,
                rel_path=rel,
                size_bytes=int(size),
                sha256=sha,
                content_type="application/octet-stream",
            )
            session.add(art)
            created += 1

    if created:
        session.commit()

    # update counts
    job = session.get(WeekendJob, job_id)
    if job:
        job.upload_count = session.exec(
            select(WeekendArtifact).where(WeekendArtifact.job_id == job_id, WeekendArtifact.kind == "upload")
        ).count()
        job.extracted_count = session.exec(
            select(WeekendArtifact).where(WeekendArtifact.job_id == job_id, WeekendArtifact.kind == "extracted")
        ).count()
        job.result_count = session.exec(
            select(WeekendArtifact).where(WeekendArtifact.job_id == job_id, WeekendArtifact.kind == "result")
        ).count()
        session.add(job)
        session.commit()

    return created


def list_jobs(session: Session, *, limit: int = 50) -> list[WeekendJob]:
    q = select(WeekendJob).order_by(WeekendJob.created_at.desc()).limit(int(limit))
    return list(session.exec(q).all())


def get_job(session: Session, job_id: int) -> WeekendJob | None:
    return session.get(WeekendJob, job_id)


def get_job_artifacts(session: Session, job_id: int) -> list[WeekendArtifact]:
    q = select(WeekendArtifact).where(WeekendArtifact.job_id == job_id).order_by(WeekendArtifact.created_at.asc())
    return list(session.exec(q).all())


def add_result_artifact(
    session: Session,
    *,
    job_id: int,
    filename: str,
    content_type: str,
    data: bytes,
) -> WeekendArtifact:
    """Persist a derived output for a job (e.g., Anthropic batch results)."""
    root = job_root(job_id)
    outdir = root / "results"
    outdir.mkdir(parents=True, exist_ok=True)

    fn = _safe_name(filename)
    path = outdir / fn
    path.write_bytes(data)
    size = path.stat().st_size
    sha = _sha256_file(path)
    rel = str(path.relative_to(root)).replace("\\", "/")

    art = WeekendArtifact(
        job_id=job_id,
        kind="result",
        filename=path.name,
        rel_path=rel,
        size_bytes=int(size),
        sha256=sha,
        content_type=content_type or "application/octet-stream",
    )
    session.add(art)
    session.commit()
    session.refresh(art)

    # update counts
    job = session.get(WeekendJob, job_id)
    if job:
        job.result_count = session.exec(
            select(WeekendArtifact).where(WeekendArtifact.job_id == job_id, WeekendArtifact.kind == "result")
        ).count()
        session.add(job)
        session.commit()

    return art


def set_job_status(session: Session, job_id: int, status: str, error: str = "") -> WeekendJob | None:
    job = session.get(WeekendJob, job_id)
    if not job:
        return None
    job.status = (status or "").strip() or job.status
    job.error = error or ""
    session.add(job)
    session.commit()
    session.refresh(job)
    return job
