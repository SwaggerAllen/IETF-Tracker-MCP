"""MCP tool implementations as pure, serializable functions over the query layer.

Every record that carries a summary also carries a source ``archive_url`` (or
``datatracker_url`` for drafts) so Claude can cite it. These functions are kept
separate from the MCP transport wiring so they can be unit-tested offline.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from wgtracker import queries
from wgtracker.db.enums import ThreadStatus
from wgtracker.db.models import Thread, ThreadDraft


def _date_range(thread: Thread) -> str:
    start = thread.start_date.date().isoformat() if thread.start_date else "?"
    end = thread.last_activity_date.date().isoformat() if thread.last_activity_date else "?"
    return f"{start}..{end}"


def _brief(text: str | None, limit: int = 240) -> str:
    if not text:
        return ""
    text = text.strip()
    return text if len(text) <= limit else text[:limit] + "…"


def thread_brief(thread: Thread) -> dict[str, Any]:
    return {
        "thread_id": thread.thread_id,
        "subject": thread.subject,
        "working_group": thread.working_group,
        "date_range": _date_range(thread),
        "status": thread.status.value,
        "consensus_state": thread.consensus_state.value if thread.consensus_state else None,
        "summary_brief": _brief(thread.summary),
        "archive_url": thread.archive_url,
    }


def search_threads(
    session: Session,
    *,
    topic: str | None = None,
    working_group: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    rows = queries.list_threads(
        session,
        topic=topic,
        working_group=working_group,
        since=since,
        until=until,
        status=ThreadStatus(status) if status else None,
        limit=limit,
    )
    return [thread_brief(t) for t in rows]


def get_thread_detail(session: Session, thread_id: str) -> dict[str, Any] | None:
    thread = queries.get_thread(session, thread_id)
    if thread is None:
        return None
    return {
        "thread_id": thread.thread_id,
        "subject": thread.subject,
        "working_group": thread.working_group,
        "date_range": _date_range(thread),
        "status": thread.status.value,
        "consensus_state": thread.consensus_state.value if thread.consensus_state else None,
        "summary": thread.summary,
        "key_positions": thread.key_positions or [],
        "participants": list(thread.participants or []),
        "archive_url": thread.archive_url,
        "drafts": [
            {
                "draft_name": td.draft_name,
                "versions_referenced": td.versions_referenced,
                "datatracker_url": td.draft.datatracker_url,
            }
            for td in thread.drafts
        ],
    }


def recent_activity(
    session: Session,
    *,
    topic: str | None = None,
    working_group: str | None = None,
    days: int = 30,
) -> list[dict[str, Any]]:
    rows = queries.recent_activity(session, topic=topic, working_group=working_group, days=days)
    return [thread_brief(t) for t in rows]


def topic_overview(
    session: Session, topic: str, *, working_group: str | None = None
) -> dict[str, Any]:
    ov = queries.topic_overview(session, topic, working_group=working_group)
    recent = cast("list[Thread]", ov.pop("recent"))
    ov["recent"] = [thread_brief(t) for t in recent]
    return ov


def _draft_dict(draft: Any, thread_count: int) -> dict[str, Any]:
    return {
        "draft_name": draft.draft_name,
        "title": draft.title,
        "status": draft.status,
        "current_version": draft.current_version,
        "rfc_number": draft.rfc_number,
        "thread_count": thread_count,
        "datatracker_url": draft.datatracker_url,
    }


def list_drafts(
    session: Session,
    *,
    topic: str | None = None,
    working_group: str | None = None,
) -> list[dict[str, Any]]:
    rows = (
        queries.drafts_for_topic(session, topic)
        if topic
        else queries.list_drafts(session, working_group=working_group)
    )
    return [_draft_dict(d, count) for d, count in rows]


def _discussion_rows(session: Session, draft_name: str) -> list[ThreadDraft]:
    stmt = (
        select(ThreadDraft)
        .where(ThreadDraft.draft_name == draft_name)
        .order_by(ThreadDraft.first_referenced_in_thread.asc().nullslast())
    )
    return list(session.scalars(stmt))


def get_draft(session: Session, draft_name: str) -> dict[str, Any] | None:
    draft = queries.get_draft(session, draft_name)
    if draft is None:
        return None
    threads: list[dict[str, Any]] = []
    for td in _discussion_rows(session, draft_name):
        t = td.thread
        threads.append(
            {
                "thread_id": t.thread_id,
                "subject": t.subject,
                "versions_referenced": td.versions_referenced,
                "first_referenced": td.first_referenced_in_thread.isoformat()
                if td.first_referenced_in_thread
                else None,
                "summary_brief": _brief(t.summary),
                "archive_url": t.archive_url,
            }
        )
    return {
        **_draft_dict(draft, len(threads)),
        "abstract": draft.abstract,
        "versions": draft.versions or [],
        "threads": threads,
    }


def draft_discussion_history(session: Session, draft_name: str) -> list[dict[str, Any]]:
    rows = _discussion_rows(session, draft_name)
    return [
        {
            "thread_id": td.thread.thread_id,
            "subject": td.thread.subject,
            "versions_referenced": td.versions_referenced,
            "first_referenced": td.first_referenced_in_thread.isoformat()
            if td.first_referenced_in_thread
            else None,
            "consensus_state": td.thread.consensus_state.value
            if td.thread.consensus_state
            else None,
            "archive_url": td.thread.archive_url,
        }
        for td in rows
    ]
