"""Declarative base, naming convention, and a cross-dialect JSON type.

JSON columns use Postgres ``JSONB`` in production and fall back to generic
``JSON`` on SQLite, so the same models run in dev/test (SQLite) and prod
(Postgres). Postgres-only features (tsvector + GIN full-text index) are added
in the Alembic migration rather than the ORM.
"""

from __future__ import annotations

from sqlalchemy import JSON, MetaData
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# JSONB on Postgres, JSON elsewhere (SQLite for dev/test).
JSONType = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
