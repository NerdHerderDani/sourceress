from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional
import httpx

@dataclass
class GitHubClient:
    token: str

    def _headers(self) -> dict[str, str]:
        h = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "github-sourcer-mvp",
        }
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    async def search_repositories(self, q: str, per_page: int = 30, page: int = 1) -> dict[str, Any]:
        async with httpx.AsyncClient(headers=self._headers(), timeout=30) as client:
            r = await client.get("https://api.github.com/search/repositories", params={"q": q, "sort": "stars", "order": "desc", "per_page": per_page, "page": page})
            r.raise_for_status()
            return r.json()

    async def search_users(self, q: str, per_page: int = 50, page: int = 1) -> dict[str, Any]:
        async with httpx.AsyncClient(headers=self._headers(), timeout=30) as client:
            r = await client.get("https://api.github.com/search/users", params={"q": q, "per_page": per_page, "page": page})
            r.raise_for_status()
            return r.json()

    async def repo_contributors(self, full_name: str, per_page: int = 100, page: int = 1) -> list[dict[str, Any]]:
        owner, repo = full_name.split("/", 1)
        async with httpx.AsyncClient(headers=self._headers(), timeout=30) as client:
            r = await client.get(f"https://api.github.com/repos/{owner}/{repo}/contributors", params={"per_page": per_page, "page": page})
            r.raise_for_status()
            return r.json()

    async def graphql(self, query: str, variables: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        async with httpx.AsyncClient(headers=self._headers(), timeout=30) as client:
            r = await client.post("https://api.github.com/graphql", json={"query": query, "variables": variables or {}})
            r.raise_for_status()
            return r.json()

    async def get_user(self, login: str) -> dict[str, Any]:
        async with httpx.AsyncClient(headers=self._headers(), timeout=30) as client:
            r = await client.get(f"https://api.github.com/users/{login}")
            r.raise_for_status()
            return r.json()

    async def list_commits_by_author(self, full_name: str, author: str, per_page: int = 10) -> list[dict[str, Any]]:
        owner, repo = full_name.split("/", 1)
        async with httpx.AsyncClient(headers=self._headers(), timeout=30) as client:
            r = await client.get(
                f"https://api.github.com/repos/{owner}/{repo}/commits",
                params={"author": author, "per_page": per_page},
            )
            r.raise_for_status()
            return r.json()
