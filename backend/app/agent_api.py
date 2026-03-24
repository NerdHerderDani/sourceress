from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from .agent_key import get_agent_key


AGENT_KEY_HEADER = 'X-Sourceress-Agent-Key'


def require_agent_key(request: Request):
    """Enforce a per-machine local agent key for write endpoints."""
    expected = get_agent_key()
    if not expected:
        return JSONResponse({
            'ok': False,
            'error': 'agent key not configured (run connector install / set key)',
        }, status_code=401)

    got = (request.headers.get(AGENT_KEY_HEADER) or '').strip()
    if not got or got != expected:
        return JSONResponse({'ok': False, 'error': 'invalid agent key'}, status_code=403)

    return None
