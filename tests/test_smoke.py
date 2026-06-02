"""Smoke tests for the CLI scaffold."""

from click.testing import CliRunner

from wgtracker.cli import main


def test_cli_help() -> None:
    result = CliRunner().invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "Working Group Activity Tracker" in result.output


def test_pipeline_poll_stub() -> None:
    result = CliRunner().invoke(main, ["pipeline", "poll"])
    assert result.exit_code == 0
    assert "not yet implemented" in result.output
