from __future__ import annotations

import re

_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def parse_repo_seeds(raw: str) -> list[str]:
    """Parses comma-separated repos and GitHub URLs into normalized owner/repo list."""
    if not raw:
        return []

    parts = []
    for p in raw.split(","):
        p = p.strip()
        if not p:
            continue

        # Accept URLs like https://github.com/owner/repo or github.com/owner/repo
        p = p.replace("https://", "").replace("http://", "")
        if p.startswith("github.com/"):
            p = p[len("github.com/"):]
        p = p.strip("/")

        # If someone pastes "owner/repo/issues" etc, keep first two segments
        segs = p.split("/")
        if len(segs) >= 2:
            p2 = f"{segs[0]}/{segs[1]}"
        else:
            p2 = p

        if _REPO_RE.match(p2):
            parts.append(p2)

    # de-dupe preserving order
    out: list[str] = []
    seen: set[str] = set()
    for r in parts:
        key = r.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out
