from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import math

def _days_ago(dt_iso: str) -> float:
    try:
        dt = datetime.fromisoformat(dt_iso.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        return max(0.0, (now - dt).total_seconds() / 86400.0)
    except Exception:
        return 9999.0

def score_candidate(profile: dict[str, Any], must_terms: list[str], should_terms: list[str] | None = None) -> tuple[float, list[str]]:
    # profile is a normalized dict we store in Candidate.profile_json
    followers = int(profile.get("followers", 0) or 0)
    repos = profile.get("repos", []) or []
    contribs_180 = int(profile.get("contribs_180", 0) or 0)

    go_bytes = int(profile.get("go_bytes", 0) or 0)
    total_bytes = int(profile.get("total_bytes", 0) or 0)
    go_share = (go_bytes / total_bytes) if total_bytes > 0 else 0.0

    # Go signal
    go_signal = 50.0 * min(1.0, go_share * 1.25)

    # OSS impact (log stars)
    stars = sum(int(r.get("stars", 0) or 0) for r in repos)
    oss_impact = 20.0 * min(1.0, math.log10(1 + stars) / 3.0)  # ~ up to 1k stars

    # Recency: based on latest push
    pushed_ats = [r.get("pushedAt") for r in repos if r.get("pushedAt")]
    days = min([_days_ago(p) for p in pushed_ats], default=9999.0)
    recency = 20.0 * (1.0 if days <= 30 else 0.7 if days <= 90 else 0.3 if days <= 180 else 0.0)
    recency += 0.01 * min(1000, contribs_180)  # small boost
    recency = min(20.0, recency)

    # Credibility
    credibility = 10.0 * min(1.0, math.log10(1 + followers) / 2.0)  # ~100 followers => ~1.0

    # Keyword match bonus (small; keep ranking mostly signal-based)
    text = (profile.get("text_blob") or "").lower()
    must_hits = sum(1 for t in must_terms if t.lower() in text)
    must_keyword = min(5.0, must_hits * 1.5)

    should_terms = should_terms or []
    should_hits = sum(1 for t in should_terms if t.lower() in text)
    # Nice-to-have boosts ranking only (does not filter). Keep modest.
    should_bonus = min(6.0, should_hits * 1.0)

    score = go_signal + oss_impact + recency + credibility + must_keyword + should_bonus

    reasons: list[str] = []
    reasons.append(f"Go share ~{go_share:.0%} across top repos")
    if stars:
        reasons.append(f"~{stars} total stars across top repos")
    if days < 9999:
        reasons.append(f"recent push ~{int(days)}d ago")
    if followers:
        reasons.append(f"{followers} followers")
    if must_hits:
        reasons.append(f"matched {must_hits} must-term(s)")
    if should_hits:
        reasons.append(f"matched {should_hits} nice-to-have term(s)")

    return float(score), reasons[:4]
