from __future__ import annotations

from typing import Any, Optional
import httpx


class OpenAlexClient:
    base_url: str = "https://api.openalex.org"

    def __init__(self, mailto: str | None = None):
        self.mailto = (mailto or "").strip() or None

    def _params(self, extra: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        p: dict[str, Any] = {}
        if self.mailto:
            p["mailto"] = self.mailto
        if extra:
            p.update(extra)
        return p

    async def search_authors(self, query: str, per_page: int = 25, page: int = 1) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(
                f"{self.base_url}/authors",
                params=self._params({"search": query, "per-page": per_page, "page": page}),
            )
            r.raise_for_status()
            return r.json()

    async def search_works(self, query: str, per_page: int = 25, page: int = 1) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(
                f"{self.base_url}/works",
                params=self._params({"search": query, "per-page": per_page, "page": page}),
            )
            r.raise_for_status()
            return r.json()
