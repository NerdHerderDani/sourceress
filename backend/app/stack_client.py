from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional
import httpx


@dataclass
class StackClient:
    site: str = "stackoverflow"
    key: str | None = None

    def _params(self, extra: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        p: dict[str, Any] = {"site": self.site}
        if self.key:
            p["key"] = self.key
        if extra:
            p.update(extra)
        return p

    async def search_questions(self, tagged: str, fromdate: int, pagesize: int = 50, page: int = 1) -> dict[str, Any]:
        # Use advanced search for tags + recency.
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(
                "https://api.stackexchange.com/2.3/search/advanced",
                params=self._params(
                    {
                        "tagged": tagged,
                        "fromdate": fromdate,
                        "order": "desc",
                        "sort": "votes",
                        "pagesize": pagesize,
                        "page": page,
                    }
                ),
            )
            r.raise_for_status()
            return r.json()

    async def question_answers(self, question_id: int, pagesize: int = 30) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(
                f"https://api.stackexchange.com/2.3/questions/{question_id}/answers",
                params=self._params(
                    {
                        "order": "desc",
                        "sort": "votes",
                        "pagesize": pagesize,
                        "filter": "!-*jbN0CeyJHb",  # includes owner + score + is_accepted
                    }
                ),
            )
            r.raise_for_status()
            return r.json()

    async def users(self, ids: list[int]) -> dict[str, Any]:
        if not ids:
            return {"items": []}
        ids_str = ";".join(str(i) for i in ids)
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(
                f"https://api.stackexchange.com/2.3/users/{ids_str}",
                params=self._params(
                    {
                        "pagesize": min(100, len(ids)),
                        "filter": "!9_bDE(fI5",  # user details incl about_me
                    }
                ),
            )
            r.raise_for_status()
            return r.json()
