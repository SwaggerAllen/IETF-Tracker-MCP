"""End-to-end ingestion tests against SQLite."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from wgtracker.config import AppConfig
from wgtracker.db.models import Draft, Message, Thread, ThreadDraft
from wgtracker.pipeline import ingest_mbox

NOW = datetime(2025, 2, 20, tzinfo=UTC)


def test_ingest_end_to_end(session: Session, sample_mbox: bytes, config: AppConfig) -> None:
    result = ingest_mbox(session, sample_mbox, "mls", config=config, now=NOW)
    session.commit()

    assert result.new_messages == 5
    assert result.threads == 2

    # Every stored message is assigned to a thread.
    messages = list(session.scalars(select(Message)))
    assert len(messages) == 5
    assert all(m.thread_id is not None for m in messages)
    assert all(m.working_group == "mls" for m in messages)

    # Drafts: the extensions draft and the RFC are recorded (stubs, offline).
    names = set(session.scalars(select(Draft.draft_name)))
    assert {"draft-ietf-mls-extensions", "rfc9420"} <= names


def test_cleaning_applied(session: Session, sample_mbox: bytes, config: AppConfig) -> None:
    ingest_mbox(session, sample_mbox, "mls", config=config, now=NOW)
    session.commit()
    bob = session.get(Message, "msg2@example.com")
    assert bob is not None
    assert ">" not in bob.body_cleaned
    assert "wrote:" not in bob.body_cleaned
    assert "draft-ietf-mls-extensions-03" in bob.body_cleaned


def test_thread_draft_versions(session: Session, sample_mbox: bytes, config: AppConfig) -> None:
    ingest_mbox(session, sample_mbox, "mls", config=config, now=NOW)
    session.commit()
    links = list(
        session.scalars(
            select(ThreadDraft).where(ThreadDraft.draft_name == "draft-ietf-mls-extensions")
        )
    )
    # One link carries the version-specific references (-03 and -04).
    versioned = [link for link in links if link.versions_referenced]
    assert versioned, "expected version-specific references on the extensions thread"
    assert set(versioned[0].versions_referenced or []) == {"03", "04"}


def test_ingest_idempotent(session: Session, sample_mbox: bytes, config: AppConfig) -> None:
    ingest_mbox(session, sample_mbox, "mls", config=config, now=NOW)
    session.commit()
    again = ingest_mbox(session, sample_mbox, "mls", config=config, now=NOW)
    session.commit()
    assert again.new_messages == 0
    assert again.threads == 2
    assert session.scalar(select(Thread).where(Thread.thread_id.isnot(None))) is not None
    assert len(list(session.scalars(select(Message)))) == 5
