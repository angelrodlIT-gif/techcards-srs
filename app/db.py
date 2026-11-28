from functools import lru_cache

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session

from app.config import get_settings


@lru_cache
def get_engine():
    engine = create_engine(get_settings().database_url, pool_pre_ping=True, hide_parameters=True)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def enable_foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

    return engine


def lock_sqlite_write(db: Session) -> None:
    if db.get_bind().dialect.name == "sqlite":
        db.execute(text("BEGIN IMMEDIATE"))


def lock_personal_write(db: Session) -> None:
    # Take one transaction lock before touching any row involved in multi-table writes.
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(1626040207)"))
    else:
        lock_sqlite_write(db)


def get_db():
    with Session(get_engine()) as session:
        yield session
