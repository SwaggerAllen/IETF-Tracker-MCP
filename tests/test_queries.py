"""Tests for the shared query layer (topic filtering, recent, participants)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from wgtracker.config import AppConfig, LLMConfig, TopicConfig
from wgtracker.pipeline import ingest_mbox
from wgtracker.queries import (
    drafts_for_topic,
    list_threads,
    participants,
    recent_activity,
    topic_overview,
)

from tests.test_llm import FakeBatchClient

NOW = datetime(2025, 2, 20, tzinfo=UTC)


def _config() -> AppConfig:
    return AppConfig(
        llm=LLMConfig(
            model_summarization="claude-sonnet-4-6", model_categorization="claude-haiku-4-5"
        ),
        topics=[TopicConfig(name="extensions", description="Protocol extensions")],
    )


def _seed(session: Session, sample_mbox: bytes) -> AppConfig:
    """Ingest + summarize + categorize so topic/participant queries have data."""
    from wgtracker.llm.runner import run_blocking

    config = _config()
    ingest_mbox(session, sample_mbox, "mls", config=config, now=NOW)
    run_blocking(session, FakeBatchClient(), config, ceiling=1000.0, now=NOW)
    session.commit()
    return config


def test_list_threads_by_topic(session: Session, sample_mbox: bytes) -> None:
    _seed(session, sample_mbox)
    rows = list_threads(session, topic="extensions")
    assert rows  # fake categorizer tags every thread "extensions"
    assert list_threads(session, topic="nonexistent") == []


def test_recent_activity_window(session: Session, sample_mbox: bytes) -> None:
    _seed(session, sample_mbox)
    # Threads are from Jan/Feb 2025; a 1-day window ending at NOW finds none.
    assert recent_activity(session, days=1, now=NOW) == []
    assert recent_activity(session, days=400, now=NOW)


def test_participants(session: Session, sample_mbox: bytes) -> None:
    _seed(session, sample_mbox)
    rows = participants(session, working_group="mls")
    addrs = {addr for addr, _ in rows}
    assert "alice@example.com" in addrs
    assert all(count >= 1 for _, count in rows)


def test_topic_overview(session: Session, sample_mbox: bytes) -> None:
    _seed(session, sample_mbox)
    ov = topic_overview(session, "extensions", working_group="mls")
    assert ov["thread_count"] >= 1
    assert isinstance(ov["by_status"], dict)
    assert isinstance(ov["by_consensus"], dict)


def test_drafts_for_topic(session: Session, sample_mbox: bytes) -> None:
    _seed(session, sample_mbox)
    rows = drafts_for_topic(session, "extensions")
    names = {d.draft_name for d, _ in rows}
    assert "draft-ietf-mls-extensions" in names
