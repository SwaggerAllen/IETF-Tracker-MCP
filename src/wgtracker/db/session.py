"""Engine and session construction."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from wgtracker.db.base import Base


def make_engine(url: str) -> Engine:
    """Create an engine. Enables foreign-key enforcement on SQLite."""
    engine = create_engine(url, future=True)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def _fk_pragma(dbapi_connection: object, _record: object) -> None:
            cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def make_session_factory(url: str) -> sessionmaker[Session]:
    """Return a configured session factory for ``url``."""
    return sessionmaker(bind=make_engine(url), class_=Session, expire_on_commit=False)


def create_all(url: str) -> None:
    """Create all tables (dev/SQLite convenience; production uses Alembic)."""
    Base.metadata.create_all(make_engine(url))


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """Transactional scope around a series of operations."""
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
