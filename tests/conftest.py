"""Shared test fixtures."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from wgtracker.config import AppConfig, LLMConfig
from wgtracker.db.session import create_all, make_session_factory

FIXTURES = Path(__file__).parent / "fixtures"
REPO_ROOT = Path(__file__).parent.parent


@pytest.fixture
def sample_mbox() -> bytes:
    return (FIXTURES / "sample.mbox").read_bytes()


@pytest.fixture
def config() -> AppConfig:
    return AppConfig(llm=LLMConfig(model_summarization="sonnet", model_categorization="haiku"))


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    url = f"sqlite:///{tmp_path / 'test.db'}"
    create_all(url)
    factory = make_session_factory(url)
    db = factory()
    try:
        yield db
    finally:
        db.close()
