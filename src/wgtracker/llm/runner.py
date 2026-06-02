"""Async batch orchestration: submit, poll, retrieve, apply.

The pipeline submits batches and records them in ``batch_jobs``; a later poll
retrieves completed batches and applies results. This matches the Batch API's
asynchronous turnaround (up to ~24h) and the GitHub Actions schedule (weekly
submit + frequent poll). A budget guardrail refuses to submit once spend reaches
the configured ceiling unless explicitly overridden.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from wgtracker.config import AppConfig
from wgtracker.db.enums import BatchStatus
from wgtracker.db.models import BatchJob
from wgtracker.llm import categorize, summarize
from wgtracker.llm.batch import BatchClient, BatchRequest, BatchResultItem
from wgtracker.llm.cost import total_spend
from wgtracker.logging import get_logger

log = get_logger(__name__)


@dataclass
class PollReport:
    summaries_applied: int = 0
    categories_applied: int = 0
    cost_usd: float = 0.0
    batches_retrieved: int = 0


def _within_budget(session: Session, config: AppConfig, ceiling: float, *, override: bool) -> bool:
    if override:
        return True
    spent = total_spend(session)
    if spent >= ceiling:
        log.warning("budget_ceiling_reached", spent=spent, ceiling=ceiling)
        return False
    return True


def _submit(
    session: Session,
    client: BatchClient,
    requests: list[BatchRequest],
    stage: str,
    *,
    now: datetime,
) -> BatchJob | None:
    if not requests:
        return None
    batch_id = client.submit(requests)
    job = BatchJob(
        batch_id=batch_id,
        stage=stage,
        status=BatchStatus.submitted,
        submitted_at=now,
        item_count=len(requests),
    )
    session.add(job)
    session.flush()
    log.info("batch_submitted", stage=stage, batch_id=batch_id, items=len(requests))
    return job


def submit_summarization(
    session: Session,
    client: BatchClient,
    config: AppConfig,
    *,
    ceiling: float,
    override: bool = False,
    limit: int | None = None,
    now: datetime | None = None,
) -> BatchJob | None:
    now = now or datetime.now(UTC)
    if not _within_budget(session, config, ceiling, override=override):
        return None
    return _submit(
        session,
        client,
        summarize.build_requests(session, config, limit=limit),
        summarize.STAGE,
        now=now,
    )


def submit_categorization(
    session: Session,
    client: BatchClient,
    config: AppConfig,
    *,
    ceiling: float,
    override: bool = False,
    recategorize: bool = False,
    limit: int | None = None,
    now: datetime | None = None,
) -> BatchJob | None:
    now = now or datetime.now(UTC)
    if not _within_budget(session, config, ceiling, override=override):
        return None
    requests = categorize.build_requests(session, config, recategorize=recategorize, limit=limit)
    return _submit(session, client, requests, categorize.STAGE, now=now)


def _apply(
    session: Session, stage: str, items: list[BatchResultItem], config: AppConfig, now: datetime
) -> tuple[int, float]:
    if stage == summarize.STAGE:
        return summarize.apply_results(session, items, config, now=now)
    if stage == categorize.STAGE:
        return categorize.apply_results(session, items, config, now=now)
    return 0, 0.0


def poll_batches(
    session: Session,
    client: BatchClient,
    config: AppConfig,
    *,
    ceiling: float,
    override: bool = False,
    now: datetime | None = None,
) -> PollReport:
    """Retrieve completed batches, apply results, then submit follow-on stages.

    After summaries are applied, automatically submits categorization for the
    newly-summarized threads (the next poll applies it).
    """
    now = now or datetime.now(UTC)
    report = PollReport()
    pending = session.scalars(
        select(BatchJob).where(BatchJob.status == BatchStatus.submitted)
    ).all()
    for job in pending:
        if not job.batch_id or client.status(job.batch_id) != "ended":
            continue
        items = list(client.results(job.batch_id))
        applied, cost = _apply(session, job.stage, items, config, now)
        job.status = BatchStatus.retrieved
        job.retrieved_at = now
        report.cost_usd += cost
        report.batches_retrieved += 1
        if job.stage == summarize.STAGE:
            report.summaries_applied += applied
        elif job.stage == categorize.STAGE:
            report.categories_applied += applied
    session.flush()

    if report.summaries_applied:
        submit_categorization(session, client, config, ceiling=ceiling, override=override, now=now)
    return report


def run_blocking(
    session: Session,
    client: BatchClient,
    config: AppConfig,
    *,
    ceiling: float,
    override: bool = False,
    now: datetime | None = None,
) -> PollReport:
    """Submit summarization then drive polling to completion.

    Useful for local/offline runs and tests where the client completes batches
    synchronously. With the real (asynchronous) client, use submit + poll instead.
    """
    now = now or datetime.now(UTC)
    submit_summarization(session, client, config, ceiling=ceiling, override=override, now=now)
    report = PollReport()
    for _ in range(10):  # bounded: summarize -> categorize -> done
        if not session.scalars(
            select(BatchJob).where(BatchJob.status == BatchStatus.submitted)
        ).first():
            break
        sub = poll_batches(session, client, config, ceiling=ceiling, override=override, now=now)
        report.summaries_applied += sub.summaries_applied
        report.categories_applied += sub.categories_applied
        report.cost_usd += sub.cost_usd
        report.batches_retrieved += sub.batches_retrieved
    return report
