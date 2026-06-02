"""Smoke tests for the CLI scaffold."""

from click.testing import CliRunner

from wgtracker.cli import main


def test_cli_help() -> None:
    result = CliRunner().invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "Working Group Activity Tracker" in result.output


def test_pipeline_help_lists_stages() -> None:
    result = CliRunner().invoke(main, ["pipeline", "--help"])
    assert result.exit_code == 0
    for stage in ("ingest", "poll", "recategorize"):
        assert stage in result.output
