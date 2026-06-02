"""Stage 4: per-thread summarization (Sonnet 4.6 via Batch API)."""

from __future__ import annotations

import re
from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from wgtracker.config import AppConfig
from wgtracker.db.models import Message, Thread
from wgtracker.llm import prompts
from wgtracker.llm.batch import BatchRequest, BatchResultItem
from wgtracker.llm.cost import estimate_cost, log_call
from wgtracker.llm.schemas import SUMMARY_SCHEMA, SummaryOutput
from wgtracker.logging import get_logger

log = get_logger(__name__)

STAGE = "summarize"
_SUMMARY_EFFORT = "low"  # extraction-style work; keep token spend bounded

_ADMIN_SUBJECT = re.compile(
    r"\b(agenda|minutes|reminder|interim|meeting|action items?|i-?d action|"
    r"new version|uploaded|call for adoption deadline|wglc)\b",
    re.IGNORECASE,
)
_TRIVIAL_BODY = re.compile(r"^\s*(\+1|-1|thanks?|ack|agreed|same here)\b", re.IGNORECASE)


def is_admin_thread(thread: Thread, messages: list[Message]) -> bool:
    """Heuristic pre-filter for administrative / no-content threads.

    A stand-in for the Haiku-based filter in the spec; conservative to avoid
    dropping substantive threads.
    """
    if _ADMIN_SUBJECT.search(thread.subject or ""):
        return True
    if len(messages) <= 1:
        body = (messages[0].body_cleaned if messages else "").strip()
        if not body or (_TRIVIAL_BODY.match(body) and len(body) < 40):
            return True
    return False


def select_threads_for_summary(session: Session, *, limit: int | None = None) -> list[Thread]:
    """Threads that are unprocessed or have new activity since last summary."""
    stmt = (
        select(Thread)
        .where(
            or_(
                Thread.last_processed.is_(None),
                Thread.last_activity_date > Thread.last_processed,
            )
        )
        .options(selectinload(Thread.messages), selectinload(Thread.drafts))
        .order_by(Thread.last_activity_date.desc().nullslast())
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(session.scalars(stmt))


def _ordered_messages(thread: Thread) -> list[Message]:
    return sorted(
        thread.messages, key=lambda m: (m.date is None, m.date or datetime.min.replace(tzinfo=UTC))
    )


def build_summary_request(thread: Thread, config: AppConfig) -> BatchRequest:
    messages = _ordered_messages(thread)
    return BatchRequest(
        custom_id=thread.thread_id,
        model=config.llm.model_summarization,
        system=prompts.summary_system(),
        user_content=prompts.summary_user(thread, messages, list(thread.drafts)),
        schema=SUMMARY_SCHEMA,
        max_tokens=2048,
        effort=_SUMMARY_EFFORT,
    )


def build_requests(
    session: Session, config: AppConfig, *, limit: int | None = None
) -> list[BatchRequest]:
    requests: list[BatchRequest] = []
    for thread in select_threads_for_summary(session, limit=limit):
        if is_admin_thread(thread, list(thread.messages)):
            continue
        requests.append(build_summary_request(thread, config))
    return requests


def apply_results(
    session: Session,
    items: list[BatchResultItem],
    config: AppConfig,
    *,
    now: datetime | None = None,
) -> tuple[int, float]:
    """Validate and persist summaries; log cost. Returns (applied, cost_usd)."""
    now = now or datetime.now(UTC)
    model = config.llm.model_summarization
    applied = 0
    total = 0.0
    for item in items:
        thread = session.get(Thread, item.custom_id)
        if thread is None:
            continue
        if item.status != "succeeded" or not item.text:
            log_call(
                session,
                stage=STAGE,
                model=model,
                usage=item.usage,
                cost_usd=0.0,
                thread_id=item.custom_id,
                status="error",
                detail=item.error or item.status,
                now=now,
            )
            continue
        try:
            out = SummaryOutput.model_validate_json(item.text)
        except ValidationError as exc:
            log_call(
                session,
                stage=STAGE,
                model=model,
                usage=item.usage,
                cost_usd=0.0,
                thread_id=item.custom_id,
                status="invalid_output",
                detail=str(exc)[:500],
                now=now,
            )
            continue
        thread.summary = out.summary
        thread.key_positions = [kp.model_dump() for kp in out.key_positions]
        thread.consensus_state = out.consensus_state
        thread.status = out.status
        thread.last_processed = now
        cost = estimate_cost(model, item.usage)
        total += cost
        log_call(
            session,
            stage=STAGE,
            model=model,
            usage=item.usage,
            cost_usd=cost,
            thread_id=thread.thread_id,
            now=now,
        )
        applied += 1
    return applied, total
