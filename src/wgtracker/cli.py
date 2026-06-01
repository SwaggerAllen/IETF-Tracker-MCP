"""Command-line interface for the WG Activity Tracker.

The pipeline subcommands are the entry points invoked by the scheduled GitHub
Actions workflow (and by the debug UI's re-trigger buttons via workflow_dispatch).
They are stubs until Milestone 1/2 lands; the wiring exists now so the deployment
pipeline is ready ahead of the spot check.
"""

from __future__ import annotations

import click

from wgtracker import __version__


@click.group()
@click.version_option(__version__)
def main() -> None:
    """Working Group Activity Tracker."""


@main.group()
def pipeline() -> None:
    """Run pipeline stages."""


@pipeline.command()
def ingest() -> None:
    """Fetch new mail, reconstruct threads, sync drafts, submit LLM batches."""
    click.echo("pipeline ingest: not yet implemented (Milestone 1)")


@pipeline.command()
def poll() -> None:
    """Poll and retrieve completed Anthropic batches; write results."""
    click.echo("pipeline poll: not yet implemented (Milestone 2)")


@pipeline.command()
def recategorize() -> None:
    """Re-categorize threads against the current topic taxonomy."""
    click.echo("pipeline recategorize: not yet implemented (Milestone 2)")


if __name__ == "__main__":
    main()
