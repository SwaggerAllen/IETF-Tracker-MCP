"""Tests for the LLM batch layer (offline, with a fake batch client)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from wgtracker.config import AppConfig, LLMConfig, TopicConfig
from wgtracker.db.models import Message, Thread, ThreadTopic
from wgtracker.llm import summarize
from wgtracker.llm.batch import BatchRequest, BatchResultItem
from wgtracker.llm.cost import Usage, estimate_cost, total_spend
from wgtracker.llm.runner import poll_batches, run_blocking, submit_summarization
from wgtracker.pipeline import ingest_mbox

NOW = datetime(2025, 2, 20, tzinfo=UTC)
HIGH_CEILING = 1000.0

SUMMARY_JSON = json.dumps(
    {
        "summary": "Bob and Carol disagreed on the extensions format version.",
        "key_positions": [
            {"position": "prefer -03", "holder": "bob@example.com", "context": "cleaner"}
        ],
        "consensus_state": "active_debate",
        "status": "active",
    }
)
CATEGORY_JSON = json.dumps({"topics": [{"name": "extensions", "confidence": 0.9}]})


class FakeBatchClient:
    """Completes batches synchronously with canned, schema-appropriate JSON."""

    def __init__(self) -> None:
        self._batches: dict[str, list[BatchRequest]] = {}
        self._n = 0

    def submit(self, requests: list[BatchRequest]) -> str:
        self._n += 1
        batch_id = f"batch-{self._n}"
        self._batches[batch_id] = requests
        return batch_id

    def status(self, batch_id: str) -> str:
        return "ended"

    def results(self, batch_id: str) -> Iterator[BatchResultItem]:
        for req in self._batches[batch_id]:
            props = req.schema["properties"]  # type: ignore[index]
            text = SUMMARY_JSON if "summary" in props else CATEGORY_JSON
            yield BatchResultItem(
                custom_id=req.custom_id,
                status="succeeded",
                text=text,
                usage=Usage(input_tokens=1000, output_tokens=100, cache_read_input_tokens=500),
            )


@pytest.fixture
def llm_config() -> AppConfig:
    return AppConfig(
        llm=LLMConfig(
            model_summarization="claude-sonnet-4-6", model_categorization="claude-haiku-4-5"
        ),
        topics=[
            TopicConfig(name="extensions", description="Protocol extensions"),
            TopicConfig(name="post_quantum", description="PQ crypto"),
        ],
    )


def _ingest(session: Session, sample_mbox: bytes, config: AppConfig) -> None:
    ingest_mbox(session, sample_mbox, "mls", config=config, now=NOW)
    session.commit()


def test_estimate_cost_batch_discount() -> None:
    usage = Usage(input_tokens=1000, output_tokens=100)
    # (1000*3 + 100*15) / 1e6 * 0.5
    assert estimate_cost("claude-sonnet-4-6", usage, batch=True) == pytest.approx(0.00225)
    assert estimate_cost("claude-sonnet-4-6", usage, batch=False) == pytest.approx(0.0045)


def test_admin_filter() -> None:
    thread = Thread(thread_id="t1", subject="MLS interim meeting agenda", working_group="mls")
    assert summarize.is_admin_thread(thread, [])
    plus_one = Message(message_id="m", from_address="x@y", body_cleaned="+1")
    thread2 = Thread(thread_id="t2", subject="Extensions format", working_group="mls")
    assert summarize.is_admin_thread(thread2, [plus_one])
    assert not summarize.is_admin_thread(
        thread2, [Message(body_cleaned="A substantive point " * 5)]
    )


def test_run_blocking_summarizes_and_categorizes(
    session: Session, sample_mbox: bytes, llm_config: AppConfig
) -> None:
    _ingest(session, sample_mbox, llm_config)
    client = FakeBatchClient()

    report = run_blocking(session, client, llm_config, ceiling=HIGH_CEILING, now=NOW)
    session.commit()

    assert report.summaries_applied == 2
    assert report.categories_applied == 2
    assert report.cost_usd > 0

    threads = list(session.scalars(select(Thread)))
    assert all(t.summary for t in threads)
    assert all(t.consensus_state is not None for t in threads)
    assert all(t.last_processed is not None for t in threads)

    links = list(session.scalars(select(ThreadTopic)))
    assert links and all(link.confidence == pytest.approx(0.9) for link in links)
    assert total_spend(session) > 0


def test_resummarize_skips_unchanged(
    session: Session, sample_mbox: bytes, llm_config: AppConfig
) -> None:
    _ingest(session, sample_mbox, llm_config)
    client = FakeBatchClient()
    run_blocking(session, client, llm_config, ceiling=HIGH_CEILING, now=NOW)
    session.commit()
    # Nothing changed since last summary -> no new summarization requests.
    assert summarize.build_requests(session, llm_config) == []


def test_budget_ceiling_blocks_submission(
    session: Session, sample_mbox: bytes, llm_config: AppConfig
) -> None:
    _ingest(session, sample_mbox, llm_config)
    job = submit_summarization(session, FakeBatchClient(), llm_config, ceiling=0.0, now=NOW)
    assert job is None
    assert not list(session.scalars(select(Thread).where(Thread.summary.isnot(None))))


def test_invalid_output_is_logged_not_applied(
    session: Session, sample_mbox: bytes, llm_config: AppConfig
) -> None:
    _ingest(session, sample_mbox, llm_config)
    thread = session.scalars(select(Thread)).first()
    assert thread is not None
    item = BatchResultItem(custom_id=thread.thread_id, status="succeeded", text="not json")
    applied, cost = summarize.apply_results(session, [item], llm_config, now=NOW)
    assert applied == 0
    assert cost == 0.0
    assert thread.summary is None


def test_poll_is_noop_without_batches(session: Session, llm_config: AppConfig) -> None:
    report = poll_batches(session, FakeBatchClient(), llm_config, ceiling=HIGH_CEILING, now=NOW)
    assert report.batches_retrieved == 0
