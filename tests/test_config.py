"""Tests for loading the application config."""

from __future__ import annotations

from pathlib import Path

from wgtracker.config import load_config

REPO_ROOT = Path(__file__).parent.parent


def test_load_repo_config() -> None:
    config = load_config(REPO_ROOT / "config.yaml")
    wg_names = {wg.name for wg in config.working_groups}
    assert {"mls", "mimi", "cfrg"} <= wg_names
    assert config.llm.model_summarization == "claude-sonnet-4-6"
    assert config.llm.use_batch_api is True
    assert any(t.name == "federation" for t in config.topics)
    assert config.working_group("mls") is not None
    assert config.working_group("nope") is None
