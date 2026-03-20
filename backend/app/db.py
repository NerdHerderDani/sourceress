from sqlmodel import SQLModel, create_engine, Session
from .config import settings

engine = create_engine(settings.db_url, echo=False)

def init_db() -> None:
    # Schema is managed by Alembic migrations.
    # We keep this as a no-op to avoid tables getting created outside migrations.
    return

def get_session() -> Session:
    return Session(engine)
