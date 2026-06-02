"""Shared read queries used by the CLI (and later the MCP server and UI)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from wgtracker.db.enums import ThreadStatus
from wgtracker.db.models import Draft, Message, Thread, ThreadDraft


def list_threads(
    session: Session,
    *,
    working_group: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    status: ThreadStatus | None = None,
    subject_contains: str | None = None,
    limit: int = 50,
) -> list[Thread]:
    """List threads matching the given filters, most-recent activity first."""
    stmt = select(Thread)
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
