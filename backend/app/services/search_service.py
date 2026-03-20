from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlmodel import select

from ..config import settings
from ..db import get_session
from ..models import SearchRun, Candidate, CandidateScore
from ..secrets_store import get_github_token
from ..query_parser import parse_boolean, to_github_tokens
from ..github_client import GitHubClient
from ..scoring import score_candidate
from ..repo_seeds import parse_repo_seeds

ENRICH_QUERY = r"""
query($login: String!, $from: DateTime!) {
  user(login: $login) {
    login
    name
    url
    avatarUrl
    bio
    company
    location
    followers { totalCount }

    contributionsCollection(from: $from) {
      contributionCalendar {
        totalContributions
      }
    }

    repositories(first: 12, ownerAffiliations: OWNER, orderBy: {field: PUSHED_AT, direction: DESC}) {
      nodes {
        name
        url
        stargazerCount
        forkCount
        pushedAt
        primaryLanguage { name }
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          totalSize
          edges {
            size
            node { name }
          }
        }
      }
    }
  }
}
"""

def create_run(
    raw_query: str,
    owner_email: str = "",
    repo_seeds: str = "",
    location: str = "",
    min_followers: int = 0,
    active_days: int = 180,
    min_contribs: int = 0,
    max_contribs: int = 0,
    location_include: str = "",
    location_exclude: str = "",
    company_include: str = "",
    company_exclude: str = "",
) -> int:
    with get_session() as s:
        run = SearchRun(
            source="github",
            owner_email=(owner_email or "").strip().lower(),
            raw_query=raw_query,
            repo_seeds=repo_seeds,
            location=location,
            min_followers=min_followers,
            active_days=active_days,
            min_contribs=min_contribs,
            max_contribs=max_contribs,
            location_include=location_include,
            location_exclude=location_exclude,
            company_include=company_include,
            company_exclude=company_exclude,
            status="queued",
            processed=0,
            total=0,
            error="",
        )
        s.add(run)
        s.commit()
        s.refresh(run)
        return int(run.id)


async def populate_run(run_id: int) -> None:
    # Dispatch by source
    with get_session() as s:
        run = s.get(SearchRun, run_id)
        if not run:
            return
        source = getattr(run, "source", "github") or "github"

    if source == "stack":
        from ..stack_service import populate_stack_run
        await populate_stack_run(run_id)
        with get_session() as s:
            r2 = s.get(SearchRun, run_id)
            if r2 and r2.status != "error":
                r2.status = "done"
                s.add(r2)
                s.commit()
        return

    with get_session() as s:
        run = s.get(SearchRun, run_id)
        if not run:
            return
        raw_query = run.raw_query
        owner_email = (getattr(run, "owner_email", "") or "").strip().lower()

    token = ""
    if owner_email:
        try:
            token = get_github_token(owner_email) or ""
        except Exception:
            token = ""
    if not token:
        token = settings.github_token

    if not token:
        _set_run_error(run_id, "No GitHub token available (set GITHUB_TOKEN or save one in Settings)")
        return

    with get_session() as s:
        run = s.get(SearchRun, run_id)
        if not run:
            return
        raw_query = run.raw_query
        repo_seeds_raw = getattr(run, "repo_seeds", "") or ""
        location = run.location
        min_followers = run.min_followers
        active_days = run.active_days
        min_contribs = int(getattr(run, "min_contribs", 0) or 0)
        max_contribs = int(getattr(run, "max_contribs", 0) or 0)

        loc_inc = (getattr(run, "location_include", "") or "").strip()
        loc_exc = (getattr(run, "location_exclude", "") or "").strip()
        comp_inc = (getattr(run, "company_include", "") or "").strip()
        comp_exc = (getattr(run, "company_exclude", "") or "").strip()
        run.status = "running"
        run.error = ""
        run.processed = 0
        run.total = 0
        s.add(run)
        s.commit()

        # Clear any previous scores for this run (if re-populating)
        try:
            s.exec(CandidateScore.__table__.delete().where(CandidateScore.__table__.c.run_id == run_id))
            s.commit()
        except Exception:
            # Non-fatal; continue
            s.rollback()

    pq = parse_boolean(raw_query)
    github_terms = to_github_tokens(pq)

    # Build repo/user search queries
    base = ["language:Go"]
    if location:
        base_user = base + [f'location:"{location}"']
    else:
        base_user = base

    if min_followers and min_followers > 0:
        base_user = base_user + [f"followers:>={min_followers}"]

    repo_q = " ".join(base + github_terms + ["stars:>10"])
    user_q = " ".join(base_user + github_terms)

    gh = GitHubClient(token)

    try:
        seed_repos = parse_repo_seeds(repo_seeds_raw)

        # Discovery: seeded repos (if provided)
        logins: set[str] = set()
        for full_name in seed_repos:
            try:
                contribs = await gh.repo_contributors(full_name, per_page=100, page=1)
                for c in contribs:
                    if c.get("type") == "User" and c.get("login"):
                        logins.add(c["login"])
            except Exception:
                continue

        # Discovery: repo search + contributors (always runs; improves breadth)
        repos_json = await gh.search_repositories(repo_q, per_page=25, page=1)
        repos = [item["full_name"] for item in repos_json.get("items", [])]

        for full_name in repos[:10]:
            try:
                contribs = await gh.repo_contributors(full_name, per_page=100, page=1)
                for c in contribs:
                    if c.get("type") == "User" and c.get("login"):
                        logins.add(c["login"])
            except Exception:
                continue

        # Discovery: user search
        users_json = await gh.search_users(user_q, per_page=50, page=1)
        for item in users_json.get("items", []):
            if item.get("login"):
                logins.add(item["login"])

        logins_list = list(logins)[:200]
        _set_run_total(run_id, len(logins_list))

        # Enrich + score
        from_dt = datetime.now(timezone.utc) - timedelta(days=active_days)

        for login in logins_list:
            data = await gh.graphql(ENRICH_QUERY, {"login": login, "from": from_dt.isoformat()})
            user = (data.get("data") or {}).get("user")
            if not user:
                _inc_processed(run_id)
                continue

            followers = int(user.get("followers", {}).get("totalCount") or 0)
            if min_followers and followers < min_followers:
                _inc_processed(run_id)
                continue

            def _kw_list(s: str) -> list[str]:
                return [x.strip().lower() for x in (s or '').split(',') if x.strip()]

            # Enforce location filter across *all* modes
            user_loc = (user.get("location") or "").strip()
            if location:
                if location.lower() not in user_loc.lower():
                    _inc_processed(run_id)
                    continue

            u_loc_l = user_loc.lower()
            if loc_inc:
                kws = _kw_list(loc_inc)
                if kws and not any(k in u_loc_l for k in kws):
                    _inc_processed(run_id)
                    continue
            if loc_exc:
                kws = _kw_list(loc_exc)
                if kws and any(k in u_loc_l for k in kws):
                    _inc_processed(run_id)
                    continue

            u_comp_l = (user.get("company") or "").lower()
            if comp_inc:
                kws = _kw_list(comp_inc)
                if kws and not any(k in u_comp_l for k in kws):
                    _inc_processed(run_id)
                    continue
            if comp_exc:
                kws = _kw_list(comp_exc)
                if kws and any(k in u_comp_l for k in kws):
                    _inc_processed(run_id)
                    continue

            # Normalize repos + language bytes
            repos_nodes = (user.get("repositories") or {}).get("nodes") or []
            go_bytes = 0
            total_bytes = 0
            norm_repos: list[dict[str, Any]] = []
            for r in repos_nodes:
                langs = (r.get("languages") or {}).get("edges") or []
                for e in langs:
                    size = int(e.get("size") or 0)
                    name = (e.get("node") or {}).get("name")
                    total_bytes += size
                    if name == "Go":
                        go_bytes += size
                norm_repos.append({
                    "name": r.get("name"),
                    "url": r.get("url"),
                    "stars": r.get("stargazerCount"),
                    "forks": r.get("forkCount"),
                    "pushedAt": r.get("pushedAt"),
                    "primaryLanguage": (r.get("primaryLanguage") or {}).get("name"),
                })

            contribs_180 = int(((user.get("contributionsCollection") or {}).get("contributionCalendar") or {}).get("totalContributions") or 0)

            # Enforce contributions filter (within active_days window)
            if min_contribs and contribs_180 < min_contribs:
                _inc_processed(run_id)
                continue
            if max_contribs and contribs_180 > max_contribs:
                _inc_processed(run_id)
                continue

            # Enforce recency filter (active_days): require at least one repo pushed within window OR any contributions.
            latest_days = None
            for rr in norm_repos:
                pa = rr.get("pushedAt")
                if not pa:
                    continue
                try:
                    dt = datetime.fromisoformat(str(pa).replace("Z", "+00:00"))
                    days = (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0
                    if latest_days is None or days < latest_days:
                        latest_days = days
                except Exception:
                    continue

            if active_days:
                if contribs_180 <= 0 and (latest_days is None or latest_days > float(active_days)):
                    _inc_processed(run_id)
                    continue

            text_blob = " ".join([
                user.get("bio") or "",
                user.get("company") or "",
                user.get("location") or "",
                " ".join([rr.get("name") or "" for rr in norm_repos]),
            ])

            profile = {
                "login": user.get("login"),
                "followers": followers,
                "go_bytes": go_bytes,
                "total_bytes": total_bytes,
                "contribs_180": contribs_180,
                "repos": norm_repos,
                "text_blob": text_blob,
            }

            score, reasons = score_candidate(profile, must_terms=pq.must, should_terms=pq.should)

            with get_session() as s:
                cand = s.get(Candidate, login)
                if not cand:
                    cand = Candidate(
                        login=login,
                        html_url=user.get("url") or "",
                        avatar_url=user.get("avatarUrl") or "",
                        name=user.get("name") or "",
                        company=user.get("company") or "",
                        location=user.get("location") or "",
                        bio=user.get("bio") or "",
                        followers=followers,
                        profile_json=profile,
                    )
                    s.add(cand)
                else:
                    cand.html_url = user.get("url") or cand.html_url
                    cand.avatar_url = user.get("avatarUrl") or cand.avatar_url
                    cand.name = user.get("name") or cand.name
                    cand.company = user.get("company") or cand.company
                    cand.location = user.get("location") or cand.location
                    cand.bio = user.get("bio") or cand.bio
                    cand.followers = followers
                    cand.profile_json = profile

                s.add(CandidateScore(run_id=run_id, login=login, score=score, reasons=reasons))
                s.commit()

            _inc_processed(run_id)

        _set_run_done(run_id)

    except Exception as e:
        _set_run_error(run_id, f"{type(e).__name__}: {e}")


def _set_run_total(run_id: int, total: int) -> None:
    with get_session() as s:
        run = s.get(SearchRun, run_id)
        if not run:
            return
        run.total = int(total)
        s.add(run)
        s.commit()


def _inc_processed(run_id: int) -> None:
    with get_session() as s:
        run = s.get(SearchRun, run_id)
        if not run:
            return
        run.processed = int(run.processed) + 1
        s.add(run)
        s.commit()


def _set_run_done(run_id: int) -> None:
    with get_session() as s:
        run = s.get(SearchRun, run_id)
        if not run:
            return
        run.status = "done"
        s.add(run)
        s.commit()


def _set_run_error(run_id: int, msg: str) -> None:
    with get_session() as s:
        run = s.get(SearchRun, run_id)
        if not run:
            return
        run.status = "error"
        run.error = msg
        s.add(run)
        s.commit()


def get_run_results(run_id: int) -> list[dict[str, Any]]:
    with get_session() as s:
        run = s.get(SearchRun, run_id)
        source = getattr(run, "source", "github") if run else "github"

        stmt = (
            select(CandidateScore, Candidate)
            .where(CandidateScore.run_id == run_id)
            .join(Candidate, Candidate.login == CandidateScore.login)
            .order_by(CandidateScore.score.desc())
        )
        rows = s.exec(stmt).all()

    out: list[dict[str, Any]] = []

    if source == "stack":
        for cs, c in rows:
            prof = c.profile_json or {}
            out.append({
                "source": "stack",
                "login": c.login,
                "name": c.name,
                "url": c.html_url,
                "avatar": c.avatar_url,
                "location": c.location,
                "score": cs.score,
                "reasons": cs.reasons,
                "rep": int(prof.get("rep") or 0),
                "answers": int(prof.get("answers") or 0),
                "tags": prof.get("tags") or [],
                "last_seen": int(prof.get("last_seen") or 0),
            })
        return out

    # github
    for cs, c in rows:
        prof = c.profile_json or {}
        repos = prof.get("repos") or []
        stars_total = 0
        latest_days = None
        for rr in repos:
            try:
                stars_total += int(rr.get("stars") or 0)
            except Exception:
                pass
            pa = rr.get("pushedAt")
            if pa:
                try:
                    dt = datetime.fromisoformat(str(pa).replace("Z", "+00:00"))
                    days = (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0
                    if latest_days is None or days < latest_days:
                        latest_days = days
                except Exception:
                    pass

        go_bytes = int(prof.get("go_bytes") or 0)
        total_bytes = int(prof.get("total_bytes") or 0)
        go_share = (go_bytes / total_bytes) if total_bytes > 0 else 0.0

        out.append({
            "source": "github",
            "login": c.login,
            "name": c.name,
            "url": c.html_url,
            "avatar": c.avatar_url,
            "location": c.location,
            "company": c.company,
            "followers": c.followers,
            "email": getattr(c, "email", ""),
            "email_source": getattr(c, "email_source", ""),
            "score": cs.score,
            "reasons": cs.reasons,
            "stars_total": stars_total,
            "go_share": go_share,
            "recency_days": latest_days,
        })
    return out


def get_run_status(run_id: int) -> dict[str, Any]:
    from ..models import SearchRun

    with get_session() as s:
        run = s.get(SearchRun, run_id)
        if not run:
            return {"id": run_id, "status": "missing"}
        return {
            "id": run.id,
            "status": run.status,
            "processed": run.processed,
            "total": run.total,
            "error": run.error,
            "raw_query": run.raw_query,
            "repo_seeds": getattr(run, "repo_seeds", ""),
            "source": getattr(run, "source", "github"),
        }
