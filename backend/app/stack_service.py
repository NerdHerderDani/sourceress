from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlmodel import select

from .db import get_session
from .models import SearchRun, Candidate, CandidateScore
from .stack_client import StackClient


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
        run.processed = int(run.processed or 0) + 1
        s.add(run)
        s.commit()


def _now_ts() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def _days_ago_ts(days: int) -> int:
    return int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp())


def score_stack(profile: dict[str, Any], tags: list[str]) -> tuple[float, list[str]]:
    rep = int(profile.get("rep", 0) or 0)
    answers = int(profile.get("answers", 0) or 0)
    q_count = int(profile.get("questions", 0) or 0)
    last_seen = int(profile.get("last_seen", 0) or 0)
    tag_hits = int(profile.get("tag_hits", 0) or 0)

    # Simple heuristic: rep (log), answers (log), recency, tag hits
    import math

    rep_score = 40.0 * min(1.0, math.log10(1 + rep) / 5.0)  # ~100k => 1.0
    ans_score = 35.0 * min(1.0, math.log10(1 + answers) / 4.0)  # ~10k => 1.0

    days = 9999.0
    if last_seen:
        days = (_now_ts() - last_seen) / 86400.0
    recency = 25.0 * (1.0 if days <= 30 else 0.7 if days <= 90 else 0.3 if days <= 180 else 0.0)

    tag_score = min(10.0, float(tag_hits) * 2.0)

    score = rep_score + ans_score + recency + tag_score

    reasons = []
    reasons.append(f"rep {rep}")
    reasons.append(f"answers {answers}")
    if days < 9999:
        reasons.append(f"last seen ~{int(days)}d ago")
    if tag_hits:
        reasons.append(f"matched {tag_hits} tag(s)")

    return float(score), reasons[:4]


async def populate_stack_run(run_id: int) -> None:
    # Mark running and load params
    with get_session() as s:
        run = s.get(SearchRun, run_id)
        if not run:
            return
        run.status = "running"
        run.error = ""
        run.processed = 0
        run.total = 0
        s.add(run)
        s.commit()

        tags_raw = (getattr(run, "stack_tags", "") or "").strip()
        match = (getattr(run, "stack_match", "any") or "any").strip().lower()
        active_days = int(getattr(run, "active_days", 90) or 90)
        min_rep = int(getattr(run, "min_rep", 0) or 0)
        min_answers = int(getattr(run, "min_answers", 0) or 0)

    tags = [t.strip() for t in tags_raw.split(',') if t.strip()]
    if not tags:
        with get_session() as s:
            run = s.get(SearchRun, run_id)
            if run:
                run.status = "error"
                run.error = "No tags provided"
                s.add(run)
                s.commit()
        return

    # StackExchange uses ';' separator for tagged (AND semantics when multiple tags).
    # For ANY (OR), we run each tag separately and merge.
    tagged = ';'.join(tags)

    sc = StackClient(site="stackoverflow")

    fromdate = _days_ago_ts(active_days)

    try:
        q_items: list[dict[str, Any]] = []
        if match == 'any':
            for t in tags:
                q = await sc.search_questions(tagged=t, fromdate=fromdate, pagesize=50, page=1)
                q_items.extend(q.get('items') or [])
        else:
            # 1) get top questions in window for tagged set
            q = await sc.search_questions(tagged=tagged, fromdate=fromdate, pagesize=50, page=1)
            q_items = q.get('items') or []

        # de-dupe by question_id
        seen_q = set()
        q_items = [qi for qi in q_items if (qi.get('question_id') not in seen_q and not seen_q.add(qi.get('question_id')))]
    except Exception as e:
        with get_session() as s:
            run = s.get(SearchRun, run_id)
            if run:
                run.status = "error"
                run.error = f"Stack API error: {e}"
                s.add(run)
                s.commit()
        return

    # 2) for each question, take top answers and aggregate owners
    user_stats: dict[int, dict[str, Any]] = {}
    for qi in q_items[:50]:
        qid = int(qi.get('question_id') or 0)
        if not qid:
            continue
        try:
            ans = await sc.question_answers(qid, pagesize=20)
        except Exception:
            continue
        for a in (ans.get('items') or [])[:5]:
            owner = a.get('owner') or {}
            uid = owner.get('user_id')
            if not uid:
                continue
            uid = int(uid)
            st = user_stats.setdefault(uid, {
                'answers_in_sample': 0,
                'answer_score': 0,
                'accepted': 0,
                'tag_hits': set(),
            })
            st['answers_in_sample'] += 1
            st['answer_score'] += int(a.get('score') or 0)
            st['accepted'] += 1 if a.get('is_accepted') else 0
            for t in (qi.get('tags') or []):
                if t in tags:
                    st['tag_hits'].add(t)

    ids = list(user_stats.keys())[:100]
    _set_run_total(run_id, len(ids))

    if not ids:
        with get_session() as s:
            run = s.get(SearchRun, run_id)
            if run:
                run.status = "done"
                s.add(run)
                s.commit()
        return

    # 3) hydrate users
    users = await sc.users(ids)
    u_items = users.get('items') or []

    for u in u_items:
        uid = int(u.get('user_id') or 0)
        if not uid or uid not in user_stats:
            continue
        # filters
        rep = int(u.get('reputation') or 0)
        if min_rep and rep < min_rep:
            _inc_processed(run_id)
            continue

        # Stack doesn't provide total answers in users route for all filters; approximate with badge counts? Use answers_in_sample.
        ans_sample = int(user_stats[uid].get('answers_in_sample') or 0)
        if min_answers and ans_sample < min_answers:
            _inc_processed(run_id)
            continue

        login = f"so:{uid}"
        url = u.get('link') or f"https://stackoverflow.com/users/{uid}"
        avatar = u.get('profile_image') or ''
        name = u.get('display_name') or ''
        location = u.get('location') or ''
        about = u.get('about_me') or ''
        last_seen = int(u.get('last_access_date') or 0)

        tag_hits = sorted(list(user_stats[uid].get('tag_hits') or []))

        profile = {
            'source': 'stack',
            'user_id': uid,
            'url': url,
            'rep': rep,
            'answers': ans_sample,
            'questions': 0,
            'last_seen': last_seen,
            'tag_hits': len(tag_hits),
            'tags': tag_hits,
            'text_blob': f"{name} {location} {about}".lower(),
        }

        score, reasons = score_stack(profile, tags)

        with get_session() as s:
            cand = s.get(Candidate, login)
            if not cand:
                cand = Candidate(login=login)
            cand.html_url = url
            cand.avatar_url = avatar
            cand.name = name
            cand.location = location
            cand.company = ''
            cand.bio = ''
            cand.followers = 0
            cand.profile_json = profile
            s.add(cand)
            s.commit()

            cs = CandidateScore(run_id=run_id, login=login, score=score, reasons=reasons)
            s.add(cs)
            s.commit()

        _inc_processed(run_id)
