"""Stage 5: topic categorization (Haiku 4.5 via Batch API).

Categorization is cheap and re-runnable: when the taxonomy changes, threads are
re-categorized without re-summarization.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from wgtracker.config import AppConfig
from wgtracker.db.models import Thread, ThreadTopic, Topic
from wgtracker.llm import prompts
from wgtracker.llm.batch import BatchRequest, BatchResultItem
from wgtracker.llm.cost import estimate_cost, log_call
from wgtracker.llm.schemas import CATEGORY_SCHEMA, CategorizationOutput
from wgtracker.logging import get_logger

log = get_logger(__name__)

STAGE = "categorize"


def sync_topics(session: Session, config: AppConfig) -> dict[str, int]:
    """Upsert the configured taxonomy into the topics table; return name->id."""
    existing = {t.name: t for t in session.scalars(select(Topic))}
    for tc in config.topics:
        topic = existing.get(tc.name)
        if topic is None:
            topic = Topic(name=tc.name)
            session.add(topic)
            existing[tc.name] = topic
        topic.description = tc.description
        topic.keywords = list(tc.keywords)
    session.flush()
    return {t.name: t.topic_id for t in session.scalars(select(Topic))}


def select_threads_for_categorization(
    session: Session, *, recategorize: bool = False, limit: int | None = None
) -> list[Thread]:
    """Summarized threads that are not yet categorized (or all, if recategorize)."""
    stmt = select(Thread).where(Thread.summary.isnot(None))
    if not recategorize:
        categorized = select(ThreadTopic.thread_id).distinct()
        stmt = stmt.where(Thread.thread_id.notin_(categorized))
    stmt = stmt.order_by(Thread.last_activity_date.desc().nullslast())
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(session.scalars(stmt))


def build_requests(
    session: Session, config: AppConfig, *, recategorize: bool = False, limit: int | None = None
) -> list[BatchRequest]:
    system = prompts.categorization_system(config)
    requests: list[BatchRequest] = []
    for thread in select_threads_for_categorization(
        session, recategorize=recategorize, limit=limit
    ):
        requests.append(
            BatchRequest(
                custom_id=thread.thread_id,
                model=config.llm.model_categorization,
                system=system,
                user_content=prompts.categorization_user(thread),
                schema=CATEGORY_SCHEMA,
                max_tokens=512,
            )
        )
    return requests


def apply_results(
    session: Session,
    items: list[BatchResultItem],
    config: AppConfig,
    *,
    now: datetime | None = None,
) -> tuple[int, float]:
    """Validate and persist topic assignments; log cost. Returns (applied, cost)."""
    now = now or datetime.now(UTC)
    model = config.llm.model_categorization
    name_to_id = sync_topics(session, config)
    applied = 0
    total = 0.0
    for item in items:
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
            out = CategorizationOutput.model_validate_json(item.text)
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
        session.execute(delete(ThreadTopic).where(ThreadTopic.thread_id == item.custom_id))
        for score in out.topics:
            topic_id = name_to_id.get(score.name)
            if topic_id is None:
                continue  # ignore topics outside the taxonomy
            session.add(
                ThreadTopic(
                    thread_id=item.custom_id,
                    topic_id=topic_id,
                    confidence=max(0.0, min(1.0, score.confidence)),
                )
            )
        cost = estimate_cost(model, item.usage)
        total += cost
        log_call(
            session,
            stage=STAGE,
            model=model,
            usage=item.usage,
            cost_usd=cost,
            thread_id=item.custom_id,
            now=now,
        )
        applied += 1
    return applied, total
