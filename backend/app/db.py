from sqlmodel import SQLModel, create_engine, Session
from .config import settings

import os
from pathlib import Path


def _ensure_sqlite_dir(db_url: str) -> None:
    u = (db_url or '').strip()
    if not u.startswith('sqlite:'):
        return

    # sqlite:///./data/app.db  -> ./data/app.db
    # sqlite:////abs/path.db   -> /abs/path.db
    path = ''
    if u.startswith('sqlite:////'):
        path = u[len('sqlite:////') - 1:]  # keep leading /
    elif u.startswith('sqlite:///'):
        path = u[len('sqlite:///'):]
    elif u.startswith('sqlite://'):
        path = u[len('sqlite://'):]

    path = (path or '').strip()
    if not path or path == ':memory:':
        return

    # Strip query params if any
    if '?' in path:
        path = path.split('?', 1)[0]

    p = Path(path)
    # Relative paths are relative to current working directory.
    # Ensure parent exists.
    try:
        parent = (p.parent if p.parent else Path('.'))
        parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        # best-effort
        return


_ensure_sqlite_dir(settings.db_url)
engine = create_engine(settings.db_url, echo=False)

def init_db() -> None:
    # Schema is managed by Alembic migrations.
    # We keep this as a no-op to avoid tables getting created outside migrations.
    return

def get_session() -> Session:
    return Session(engine)
