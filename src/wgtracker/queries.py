"""Shared read queries used by the CLI (and later the MCP server and UI)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, selectinload

from wgtracker.db.enums import ConsensusState, ThreadStatus
from wgtracker.db.models import Draft, Message, Thread, ThreadDraft, ThreadTopic, Topic


def _by_topic(stmt: Select[tuple[Thread]], topic: str) -> Select[tuple[Thread]]:
    return (
        stmt.join(ThreadTopic, ThreadTopic.thread_id == Thread.thread_id)
        .join(Topic, Topic.topic_id == ThreadTopic.topic_id)
        .where(Topic.name == topic)
    )


def list_threads(
    session: Session,
    *,
    topic: str | None = None,
    working_group: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    status: ThreadStatus | None = None,
    subject_contains: str | None = None,
    limit: int = 50,
) -> list[Thread]:
    """List threads matching the given filters, most-recent activity first."""
    stmt = select(Thread)
    if topic:
        stmt = _by_topic(stmt, topic)
    if working_group:
        stmt = stmt.where(Thread.working_group == working_group)
    if since:
        stmt = stmt.where(Thread.last_activity_date >= since)
    if until:
        stmt = stmt.where(Thread.last_activity_date <= until)
    if status:
        stmt = stmt.where(Thread.status == status)
    if subject_contains:
        stmt = stmt.where(Thread.subject.ilike(f"%{subject_contains}%"))
    stmt = stmt.order_by(Thread.last_activity_date.desc().nullslast()).limit(limit)
    return list(session.scalars(stmt))


def recent_activity(
    session: Session,
    *,
    topic: str | None = None,
    working_group: str | None = None,
    days: int = 30,
    limit: int = 50,
    now: datetime | None = None,
) -> list[Thread]:
    """Threads with activity in the last ``days`` days."""
    since = (now or datetime.now(UTC)) - timedelta(days=days)
    return list_threads(session, topic=topic, working_group=working_group, since=since, limit=limit)


def participants(
    session: Session,
    *,
    topic: str | None = None,
    working_group: str | None = None,
    limit: int = 50,
) -> list[tuple[str, int]]:
    """Most active participants (by message count) over the matching threads."""
    stmt = (
        select(Message.from_address, func.count(Message.message_id))
        .join(Thread, Thread.thread_id == Message.thread_id)
        .where(Message.from_address != "")
    )
    if working_group:
        stmt = stmt.where(Thread.working_group == working_group)
    if topic:
        stmt = (
            stmt.join(ThreadTopic, ThreadTopic.thread_id == Thread.thread_id)
            .join(Topic, Topic.topic_id == ThreadTopic.topic_id)
            .where(Topic.name == topic)
        )
    stmt = (
        stmt.group_by(Message.from_address)
        .order_by(func.count(Message.message_id).desc())
        .limit(limit)
    )
    return [(addr, int(count)) for addr, count in session.execute(stmt).all()]


def topic_overview(
    session: Session, topic: str, *, working_group: str | None = None
) -> dict[str, object]:
    """Aggregate state of discussion for a topic: counts by status and consensus."""
    threads = list_threads(session, topic=topic, working_group=working_group, limit=10_000)
    by_status: dict[str, int] = {s.value: 0 for s in ThreadStatus}
    by_consensus: dict[str, int] = {c.value: 0 for c in ConsensusState}
    for t in threads:
        by_status[t.status.value] += 1
        if t.consensus_state is not None:
            by_consensus[t.consensus_state.value] += 1
    return {
        "topic": topic,
        "thread_count": len(threads),
        "by_status": by_status,
        "by_consensus": by_consensus,
        "recent": threads[:10],
    }


def get_thread(session: Session, thread_id: str) -> Thread | None:
    """Fetch a thread with its messages and draft links eagerly loaded."""
    stmt = (
        select(Thread)
        .where(Thread.thread_id == thread_id)
        .options(selectinload(Thread.messages), selectinload(Thread.drafts))
    )
    return session.scalars(stmt).first()


def thread_messages(session: Session, thread_id: str) -> list[Message]:
    stmt = (
        select(Message)
        .where(Message.thread_id == thread_id)
        .order_by(Message.date.asc().nullslast())
    )
    return list(session.scalars(stmt))


def list_drafts(session: Session, *, working_group: str | None = None) -> list[tuple[Draft, int]]:
    """List drafts with the count of threads referencing each."""
    counts: dict[str, int] = {
        name: int(count)
        for name, count in session.execute(
            select(ThreadDraft.draft_name, func.count(ThreadDraft.thread_id)).group_by(
                ThreadDraft.draft_name
            )
        ).all()
    }
    stmt = select(Draft)
    if working_group:
        stmt = stmt.where(Draft.working_group == working_group)
    stmt = stmt.order_by(Draft.draft_name)
    return [(d, int(counts.get(d.draft_name, 0))) for d in session.scalars(stmt)]


def drafts_for_topic(session: Session, topic: str) -> list[tuple[Draft, int]]:
    """Drafts referenced in threads categorized under ``topic``."""
    stmt = (
        select(Draft, func.count(func.distinct(ThreadDraft.thread_id)))
        .join(ThreadDraft, ThreadDraft.draft_name == Draft.draft_name)
        .join(ThreadTopic, ThreadTopic.thread_id == ThreadDraft.thread_id)
        .join(Topic, Topic.topic_id == ThreadTopic.topic_id)
        .where(Topic.name == topic)
        .group_by(Draft.draft_name)
        .order_by(func.count(func.distinct(ThreadDraft.thread_id)).desc())
    )
    return [(draft, int(count)) for draft, count in session.execute(stmt).all()]


def get_draft(session: Session, draft_name: str) -> Draft | None:
    return session.get(Draft, draft_name)


def threads_for_draft(session: Session, draft_name: str) -> list[Thread]:
    """Threads referencing a draft, earliest reference first."""
    stmt = (
        select(Thread)
        .join(ThreadDraft, ThreadDraft.thread_id == Thread.thread_id)
        .where(ThreadDraft.draft_name == draft_name)
        .order_by(ThreadDraft.first_referenced_in_thread.asc().nullslast())
    )
    return list(session.scalars(stmt))
