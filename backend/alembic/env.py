from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Alembic Config object
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ---- target metadata (SQLModel) ----
from app.models import SQLModel  # noqa: E402
from app.config import settings  # noqa: E402


def _ensure_sqlite_dir(db_url: str) -> None:
    u = (db_url or '').strip()
    if not u.startswith('sqlite:'):
        return

    path = ''
    if u.startswith('sqlite:////'):
        path = u[len('sqlite:////') - 1:]
    elif u.startswith('sqlite:///'):
        path = u[len('sqlite:///'):]
    elif u.startswith('sqlite://'):
        path = u[len('sqlite://'):]

    path = (path or '').strip()
    if not path or path == ':memory:':
        return
    if '?' in path:
        path = path.split('?', 1)[0]

    try:
        from pathlib import Path
        p = Path(path)
        parent = (p.parent if p.parent else Path('.'))
        parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        return


def get_url() -> str:
    # Prefer DATABASE_URL (hosting), then DB_URL, then settings
    url = os.getenv("DATABASE_URL", "") or os.getenv("DB_URL", "") or settings.db_url
    _ensure_sqlite_dir(url)
    return url


target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = get_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
