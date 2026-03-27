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
    """Initialize DB for local/demo builds.

    In dev, Alembic manages schema. In packaged desktop demos we don't want users
    to run migrations manually, so if we're on SQLite and the DB is empty, we
    create tables.
    """
    try:
        u = (settings.db_url or '').strip()
        if not u.startswith('sqlite:'):
            return

        # Best-effort: if any core table exists, assume schema is present.
        from sqlalchemy import inspect

        insp = inspect(engine)
        existing = set(insp.get_table_names() or [])
        if existing:
            return

        # Create all tables defined by SQLModel metadata.
        SQLModel.metadata.create_all(engine)
    except Exception:
        # Don't block app startup.
        return

def get_session() -> Session:
    return Session(engine)
