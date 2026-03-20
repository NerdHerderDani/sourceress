from __future__ import annotations

from typing import Optional, Tuple

from sqlmodel import Session

from ..config import settings
from ..github_client import GitHubClient
from ..models import Candidate


def _extract_commit_email(commit_obj: dict) -> Optional[str]:
    # REST /commits returns: { commit: { author: { email } } }
    try:
        email = (((commit_obj or {}).get("commit") or {}).get("author") or {}).get("email")
        if not email:
            return None
        email = str(email).strip()
        if not email or email.endswith("@users.noreply.github.com"):
            return None
        return email
    except Exception:
        return None


def _repo_full_names_from_profile(profile_json: dict) -> list[str]:
    # We only stored repo names + urls; infer full_name from url
    repos = (profile_json or {}).get("repos") or []
    full_names: list[str] = []
    for r in repos:
        url = (r or {}).get("url") or ""
        # url like https://github.com/{owner}/{repo}
        parts = url.split("github.com/")
        if len(parts) == 2:
            full = parts[1].strip("/")
            if full.count("/") == 1:
                full_names.append(full)
    return full_names


async def fetch_email_for_login(login: str) -> Tuple[str, str]:
    """Returns (email, source). Source is profile|commit|none."""
    gh = GitHubClient(settings.github_token)

    # 1) Profile email (public)
    try:
        u = await gh.get_user(login)
        email = (u.get("email") or "").strip() if isinstance(u.get("email"), str) else ""
        if email and not email.endswith("@users.noreply.github.com"):
            return email, "profile"
    except Exception:
        pass

    # 2) Commit author email (best-effort)
    # We'll look at a couple recent repos we already have for the candidate.
    # If we don't have repos cached, we can't do much.
    return "", "none"


async def fetch_email_for_candidate(session: Session, login: str) -> Tuple[str, str]:
    if not settings.github_token:
        return "", "none"

    cand = session.get(Candidate, login)
    if not cand:
        return "", "none"

    # If already fetched, return it
    if cand.email:
        return cand.email, cand.email_source or ""

    gh = GitHubClient(settings.github_token)

    # 1) Public profile email
    try:
        u = await gh.get_user(login)
        email = (u.get("email") or "").strip() if isinstance(u.get("email"), str) else ""
        if email and not email.endswith("@users.noreply.github.com"):
            cand.email = email
            cand.email_source = "profile"
            session.add(cand)
            session.commit()
            return cand.email, cand.email_source
    except Exception:
        pass

    # 2) Commit email from recent repos
    repo_full_names = _repo_full_names_from_profile(cand.profile_json)
    for full_name in repo_full_names[:3]:
        try:
            commits = await gh.list_commits_by_author(full_name, author=login, per_page=10)
            for co in commits:
                email = _extract_commit_email(co)
                if email:
                    cand.email = email
                    cand.email_source = "commit"
                    session.add(cand)
                    session.commit()
                    return cand.email, cand.email_source
        except Exception:
            continue

    cand.email = ""
    cand.email_source = "none"
    session.add(cand)
    session.commit()
    return "", "none"
