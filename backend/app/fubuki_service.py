from __future__ import annotations

import os
from typing import Any

import httpx


ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-4-20250514"


def _api_key() -> str:
    # Prefer explicit env var. (Never store in frontend.)
    return (os.environ.get('ANTHROPIC_API_KEY') or '').strip()


def fubuki_call(system: str, messages: list[dict[str, Any]], max_tokens: int = 1200) -> str:
    key = _api_key()
    if not key:
        raise RuntimeError("Missing ANTHROPIC_API_KEY env var")

    headers = {
        "Content-Type": "application/json",
        "x-api-key": key,
        "anthropic-version": "2023-06-01",
    }

    payload = {
        "model": MODEL,
        "max_tokens": int(max_tokens),
        "system": system,
        "messages": messages,
    }

    with httpx.Client(timeout=30.0) as client:
        r = client.post(ANTHROPIC_URL, headers=headers, json=payload)
        r.raise_for_status()
        data = r.json() if r.content else {}

    # Anthropic returns content: [{type:'text', text:'...'}]
    parts = data.get('content') or []
    for p in parts:
        if isinstance(p, dict) and p.get('type') == 'text':
            return (p.get('text') or '').strip()

    return ""
