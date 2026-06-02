"""Tests for the FastAPI debug-UI JSON API (offline, in-process)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from wgtracker.api.app import create_app
from wgtracker.config import AppConfig, LLMConfig, TopicConfig
from wgtracker.db.session import create_all, make_session_factory, session_scope
from wgtracker.llm.runner import run_blocking
from wgtracker.pipeline import ingest_mbox
from wgtracker.settings import Settings

from tests.test_llm import FakeBatchClient

NOW = datetime(2025, 2, 20, tzinfo=UTC)


def _config() -> AppConfig:
    return AppConfig(
        llm=LLMConfig(
            model_summarization="claude-sonnet-4-6", model_categorization="claude-haiku-4-5"
        ),
        topics=[TopicConfig(name="extensions", description="Protocol extensions")],
    )


@pytest.fixture
def client(tmp_path: Path, sample_mbox: bytes) -> TestClient:
    url = f"sqlite:///{tmp_path / 'api.db'}"
    create_all(url)
    factory = make_session_factory(url)
    config = _config()
    with session_scope(factory) as session:
        ingest_mbox(session, sample_mbox, "mls", config=config, now=NOW)
        run_blocking(session, FakeBatchClient(), config, ceiling=1000.0, now=NOW)
    # No auth env set -> Basic auth disabled for the test.
    settings = Settings(database_url=url)
    return TestClient(create_app(settings=settings, session_factory=factory))


def test_health(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_list_and_get_thread(client: TestClient) -> None:
    rows = client.get("/api/threads").json()
    assert rows and all("archive_url" in r for r in rows)
    detail = client.get(f"/api/threads/{rows[0]['thread_id']}").json()
    assert detail["summary"]
    assert "archive_url" in detail
    assert client.get("/api/threads/nope").status_code == 404


def test_threads_by_topic(client: TestClient) -> None:
    rows = client.get("/api/threads", params={"topic": "extensions"}).json()
    assert rows


def test_drafts_and_cost(client: TestClient) -> None:
    drafts = client.get("/api/drafts").json()
    assert any(d["draft_name"] == "draft-ietf-mls-extensions" for d in drafts)
    cost = client.get("/api/cost").json()
    assert cost["total_usd"] > 0
    assert "by_stage" in cost


def test_topics_and_batches(client: TestClient) -> None:
    assert any(t["name"] == "extensions" for t in client.get("/api/topics").json())
    assert isinstance(client.get("/api/batches").json(), list)


def test_retrigger_unconfigured_returns_503(client: TestClient) -> None:
    resp = client.post("/api/retrigger/ingest")
    assert resp.status_code == 503


def test_basic_auth_enforced_when_configured(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'auth.db'}"
    create_all(url)
    factory = make_session_factory(url)
    settings = Settings(database_url=url, ui_basic_auth_user="admin", ui_basic_auth_pass="secret")
    client = TestClient(create_app(settings=settings, session_factory=factory))
    assert client.get("/api/threads").status_code == 401
    assert client.get("/api/threads", auth=("admin", "secret")).status_code == 200
    assert client.get("/health").status_code == 200  # health stays open
