"""Ingestion pipeline orchestration (Milestone 1 — no LLM).

Idempotent: messages dedupe by Message-ID; threads are recomputed from all
stored messages of a working group on each run, so re-ingesting the same archive
produces the same result and incremental archives extend existing threads.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from wgtracker.config import AppConfig
from wgtracker.db.models import Draft, Message, Thread, ThreadDraft
from wgtracker.drafts.datatracker import DatatrackerClient, ensure_drafts
from wgtracker.drafts.extract import DraftRef, extract_references
from wgtracker.ingest.clean import clean_body
from wgtracker.ingest.parse import ParsedMessage, parse_mbox_bytes
from wgtracker.ingest.threads import reconstruct_threads
from wgtracker.logging import get_logger

log = get_logger(__name__)


@dataclass
class IngestResult:
    new_messages: int
    threads: int
    drafts: int


@dataclass
class _DraftAccum:
    versions: set[str] = field(default_factory=set)
    first_date: datetime | None = None


def _as_utc(dt: datetime | None) -> datetime | None:
    """Coerce a possibly tz-naive datetime (e.g. read back from SQLite) to UTC."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def _to_parsed(m: Message) -> ParsedMessage:
    return ParsedMessage(
        message_id=m.message_id,
        subject=m.subject,
        from_address=m.from_address,
        from_name=m.from_name,
        date=_as_utc(m.date),
        in_reply_to=m.in_reply_to,
        references=list(m.references or []),
        body_original=m.body_original,
        archive_url=m.archive_url,
    )


def ingest_mbox(
    session: Session,
    data: bytes,
    working_group: str,
    *,
    config: AppConfig,
    draft_client: DatatrackerClient | None = None,
    now: datetime | None = None,
) -> IngestResult:
    """Ingest raw mbox bytes for one working group."""
    parsed_new = list(parse_mbox_bytes(data))
    existing_ids = set(
        session.scalars(select(Message.message_id).where(Message.working_group == working_group))
    )

    new_count = 0
    for pm in parsed_new:
        if pm.message_id in existing_ids:
            continue
        session.add(
            Message(
                message_id=pm.message_id,
                working_group=working_group,
                from_address=pm.from_address,
                from_name=pm.from_name,
                date=pm.date,
                archive_url=pm.archive_url,
                body_original=pm.body_original,
                body_cleaned=clean_body(pm.body_original),
                in_reply_to=pm.in_reply_to,
                references=pm.references,
                subject=pm.subject,
            )
        )
        new_count += 1
    session.flush()

    all_msgs = list(session.scalars(select(Message).where(Message.working_group == working_group)))
    threads, msg_to_thread = reconstruct_threads(
        [_to_parsed(m) for m in all_msgs],
        working_group,
        active_threshold_days=config.processing.active_threshold_days,
        now=now,
    )

    current_ids: set[str] = set()
    for rt in threads:
        current_ids.add(rt.thread_id)
        thread = session.get(Thread, rt.thread_id)
        if thread is None:
            thread = Thread(thread_id=rt.thread_id)
            session.add(thread)
        thread.subject = rt.subject
        thread.working_group = working_group
        thread.start_date = rt.start_date
        thread.last_activity_date = rt.last_activity_date
        thread.message_count = rt.message_count
        thread.archive_url = rt.archive_url
        thread.participants = rt.participants
        # Don't clobber an LLM-assigned status once a thread has been summarized;
        # before that, derive active/concluded from activity age.
        if thread.last_processed is None:
            thread.status = rt.status
    session.flush()

    # Assign each message to its thread now that the thread rows exist (FK-safe).
    msg_by_id = {m.message_id: m for m in all_msgs}
    for mid, tid in msg_to_thread.items():
        msg_by_id[mid].thread_id = tid
    session.flush()

    # Remove stale (now-empty) thread rows for this WG; messages were reassigned
    # above, so cascade deletes nothing real.
    stale = session.scalars(
        select(Thread).where(
            Thread.working_group == working_group,
            Thread.thread_id.notin_(current_ids),
        )
    ).all()
    for thread in stale:
        session.delete(thread)
    session.flush()

    refs_by_message: dict[str, list[DraftRef]] = {
        m.message_id: extract_references(m.body_original) for m in all_msgs
    }
    all_names = {r.name for refs in refs_by_message.values() for r in refs}
    drafts_touched = 0
    if all_names:
        drafts_touched = ensure_drafts(
            session,
            all_names,
            client=draft_client,
            refresh_days=config.processing.draft_metadata_refresh_days,
            now=now,
        )
        session.flush()

    _rebuild_thread_drafts(session, all_msgs, refs_by_message, current_ids)
    session.flush()

    log.info(
        "ingest_complete",
        working_group=working_group,
        new_messages=new_count,
        threads=len(threads),
        drafts=drafts_touched,
    )
    return IngestResult(new_messages=new_count, threads=len(threads), drafts=drafts_touched)


def _rebuild_thread_drafts(
    session: Session,
    messages: list[Message],
    refs_by_message: dict[str, list[DraftRef]],
    current_ids: set[str],
) -> None:
    """Recompute thread<->draft links (with per-thread versions) for current threads."""
    if current_ids:
        session.execute(delete(ThreadDraft).where(ThreadDraft.thread_id.in_(current_ids)))
    known_drafts = set(session.scalars(select(Draft.draft_name)))
    accum: dict[tuple[str, str], _DraftAccum] = {}
    for m in messages:
        if m.thread_id is None:
            continue
        for ref in refs_by_message.get(m.message_id, []):
            if ref.name not in known_drafts:
                continue
            entry = accum.setdefault((m.thread_id, ref.name), _DraftAccum())
            if ref.version:
                entry.versions.add(ref.version)
            if m.date is not None and (entry.first_date is None or m.date < entry.first_date):
                entry.first_date = m.date
    for (thread_id, draft_name), entry in accum.items():
        session.add(
            ThreadDraft(
                thread_id=thread_id,
                draft_name=draft_name,
                versions_referenced=sorted(entry.versions) or None,
                first_referenced_in_thread=entry.first_date,
            )
        )
