"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-06-02

Builds the baseline schema directly from the SQLAlchemy models so the migration
cannot drift from the ORM. The Postgres-only full-text index (tsvector + GIN) is
added separately and skipped on other dialects (e.g. SQLite in dev/test). This is
full-text search, not vector search.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

import wgtracker.db.models  # noqa: F401  (register tables on the metadata)
from wgtracker.db.base import Base

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FTS_COLUMN = (
    "ALTER TABLE threads ADD COLUMN search_tsv tsvector "
    "GENERATED ALWAYS AS ("
    "to_tsvector('english', coalesce(subject, '') || ' ' || coalesce(summary, ''))"
    ") STORED"
)
_FTS_INDEX = "CREATE INDEX ix_threads_search_tsv ON threads USING GIN (search_tsv)"


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind)
    if bind.dialect.name == "postgresql":
        op.execute(_FTS_COLUMN)
        op.execute(_FTS_INDEX)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_threads_search_tsv")
    Base.metadata.drop_all(bind)
