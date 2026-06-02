"""Token usage and cost accounting.

Pricing is per 1M tokens (input, output). Cache reads bill at ~0.1x input,
cache writes at ~1.25x input. The Batch API applies a 50% discount to everything.
Every call is logged to ``processing_log`` so spend can be reported by stage.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from wgtracker.db.models import ProcessingLog

# model -> (input $/1M, output $/1M)
PRICING: dict[str, tuple[float, float]] = {
    "claude-opus-4-8": (5.0, 25.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
}


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


def estimate_cost(model: str, usage: Usage, *, batch: bool = True) -> float:
    """Estimate USD cost for a single call's usage."""
    price_in, price_out = PRICING.get(model, (0.0, 0.0))
    dollars = (
        usage.input_tokens * price_in
        + usage.cache_creation_input_tokens * price_in * 1.25
        + usage.cache_read_input_tokens * price_in * 0.10
        + usage.output_tokens * price_out
    ) / 1_000_000
    return dollars * 0.5 if batch else dollars


def log_call(
    session: Session,
    *,
    stage: str,
    model: str,
    usage: Usage,
    cost_usd: float,
    thread_id: str | None = None,
    status: str = "ok",
    detail: str | None = None,
    now: datetime | None = None,
) -> None:
    session.add(
        ProcessingLog(
            date=now or datetime.now(UTC),
            stage=stage,
            model=model,
            input_tokens=usage.input_tokens
            + usage.cache_creation_input_tokens
            + usage.cache_read_input_tokens,
            output_tokens=usage.output_tokens,
            cost_usd=cost_usd,
            status=status,
            detail=detail,
            thread_id=thread_id,
        )
    )


def total_spend(session: Session) -> float:
    return float(
        session.scalar(select(func.coalesce(func.sum(ProcessingLog.cost_usd), 0.0))) or 0.0
    )


def spend_by_stage(session: Session) -> dict[str, float]:
    rows = session.execute(
        select(ProcessingLog.stage, func.coalesce(func.sum(ProcessingLog.cost_usd), 0.0)).group_by(
            ProcessingLog.stage
        )
    ).all()
    return {stage: float(total) for stage, total in rows}
