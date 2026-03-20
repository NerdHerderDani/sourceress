from __future__ import annotations

import base64
import hashlib
from datetime import datetime
from typing import Optional

from cryptography.fernet import Fernet
from sqlmodel import select

from .config import settings
from .db import get_session
from .user_secret_model import UserSecret


def _fernet() -> Fernet:
    """Derive a stable Fernet key from APP_SECRET_KEY."""
    if not settings.app_secret_key:
        raise RuntimeError("APP_SECRET_KEY not set")
    digest = hashlib.sha256(settings.app_secret_key.encode('utf-8')).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def set_github_token(email: str, token: str) -> None:
    f = _fernet()
    enc = f.encrypt(token.encode('utf-8')).decode('utf-8')
    em = email.lower().strip()

    with get_session() as s:
        existing = s.exec(select(UserSecret).where(UserSecret.email == em)).first()
        if existing:
            existing.github_token_enc = enc
            existing.updated_at = datetime.utcnow()
            s.add(existing)
            s.commit()
            return

        us = UserSecret(email=em, github_token_enc=enc)
        s.add(us)
        s.commit()


def get_github_token(email: str) -> Optional[str]:
    f = _fernet()
    em = email.lower().strip()
    with get_session() as s:
        row = s.exec(select(UserSecret).where(UserSecret.email == em)).first()
        if not row or not row.github_token_enc:
            return None
        try:
            return f.decrypt(row.github_token_enc.encode('utf-8')).decode('utf-8')
        except Exception:
            return None
