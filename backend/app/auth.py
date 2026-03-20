from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any, Optional

from fastapi import Request

from .config import settings


def _b64url_decode(s: str) -> bytes:
    s += '=' * (-len(s) % 4)
    return base64.urlsafe_b64decode(s.encode('utf-8'))


def verify_supabase_jwt(token: str) -> Optional[dict[str, Any]]:
    """Verify HS256 JWT issued by Supabase using SUPABASE_JWT_SECRET.

    Returns claims if valid, else None.
    """
    secret = settings.supabase_jwt_secret
    if not secret:
        return None

    try:
        header_b64, payload_b64, sig_b64 = token.split('.')
        signing_input = f"{header_b64}.{payload_b64}".encode('utf-8')
        sig = _b64url_decode(sig_b64)

        header = json.loads(_b64url_decode(header_b64))
        if header.get('alg') != 'HS256':
            return None

        expected = hmac.new(secret.encode('utf-8'), signing_input, hashlib.sha256).digest()
        if not hmac.compare_digest(expected, sig):
            return None

        claims = json.loads(_b64url_decode(payload_b64))

        # exp
        exp = claims.get('exp')
        if exp is not None:
            if int(exp) < int(time.time()):
                return None

        return claims
    except Exception:
        return None


def get_bearer_token(req: Request) -> Optional[str]:
    auth = req.headers.get('authorization') or req.headers.get('Authorization')
    if not auth:
        return None
    parts = auth.split(' ', 1)
    if len(parts) != 2:
        return None
    if parts[0].lower() != 'bearer':
        return None
    return parts[1].strip() or None


def email_allowed(email: str) -> bool:
    allow = [e.strip().lower() for e in (settings.allowlist_emails or '').split(',') if e.strip()]
    if not allow:
        return True
    return email.strip().lower() in allow
