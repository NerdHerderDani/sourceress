from __future__ import annotations

from typing import Any, Tuple

from .fubuki_service import fubuki_call, fubuki_call_ex


DM_SYSTEM_PROMPT = (
    "Fubuki off the clock — casual DMs, 1-2 sentences max, dry and natural, "
    "same personality as always but not in work mode. "
    "No recruiting, no Ava Labs unless they bring it up."
)


def fubuki_dm(data: dict[str, Any]) -> Tuple[str | None, str | None]:
    """Handle a casual DM-style chat turn via Anthropic.

    Expects:
      - message: str
      - history: list[{role: 'user'|'assistant', content: str}]

    Returns: (response, error)
    """
    msg = (data.get('message') or '').strip()
    hist = data.get('history') or []

    if not msg:
        return None, 'missing message'

    messages: list[dict[str, str]] = []
    if isinstance(hist, list):
        for h in hist:
            if not isinstance(h, dict):
                continue
            r = (h.get('role') or '').strip()
            c = (h.get('content') or '').strip()
            if r in ('user', 'assistant') and c:
                messages.append({'role': r, 'content': c})

    messages.append({'role': 'user', 'content': msg})

    try:
        # Keep it short; DMs should be snappy.
        api_key = (data.get('_anthropic_api_key') or '').strip() or None
        text, meta = fubuki_call_ex(DM_SYSTEM_PROMPT, messages, max_tokens=120, api_key=api_key)
        # Stash meta so the route layer can log it (best-effort).
        data['_usage_meta'] = meta
    except Exception as e:
        return None, str(e)

    return (text or '').strip(), None
