"""Command-line interface for the WG Activity Tracker.

Milestone 1 provides offline-capable ingestion (from a local mbox file or the
IETF mail archive) plus sanity-check query commands. The ``pipeline`` subgroup
holds the entry points invoked by the scheduled GitHub Actions workflow.
"""

from __future__ import annotations

from datetime import UTC, datetime

import click

from wgtracker import __version__
from wgtracker.config import AppConfig, load_config
from wgtracker.db.enums import ThreadStatus
from wgtracker.db.session import create_all, make_session_factory, session_scope
from wgtracker.ingest.mailarchive import export_url, fetch_mbox_url, read_mbox_file
from wgtracker.logging import configure_logging, get_logger
from wgtracker.pipeline import ingest_mbox
from wgtracker.settings import Settings, get_settings

log = get_logger(__name__)


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    dt = datetime.fromisoformat(value)
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt


def _draft_client(config: AppConfig, settings: Settings, enabled: bool) -> object | None:
    if not enabled:
        return None
    from wgtracker.drafts.datatracker import HttpxDatatrackerClient

    return HttpxDatatrackerClient(config.drafts.datatracker_api_base)


@click.group()
@click.version_option(__version__)
@click.pass_context
def main(ctx: click.Context) -> None:
    """Working Group Activity Tracker."""
    settings = get_settings()
    configure_logging(settings.log_level)
    ctx.obj = {
        "settings": settings,
        "factory": make_session_factory(settings.database_url),
    }


@main.command("db-init")
@click.pass_context
def db_init(ctx: click.Context) -> None:
    """Create all tables (dev/SQLite; production uses Alembic migrations)."""
    settings: Settings = ctx.obj["settings"]
    create_all(settings.database_url)
    click.echo(f"Initialised schema at {settings.database_url}")


@main.command()
@click.option("--working-group", "-w", required=True, help="Working-group list name.")
@click.option("--file", "file_path", type=click.Path(exists=True), help="Local mbox file.")
@click.option("--url", help="mbox export URL (defaults to the archive export for the WG).")
@click.option("--fetch-drafts", is_flag=True, help="Fetch draft metadata from Datatracker.")
@click.pass_context
def ingest(
    ctx: click.Context,
    working_group: str,
    file_path: str | None,
    url: str | None,
    fetch_drafts: bool,
) -> None:
    """Ingest an mbox archive for a working group."""
    settings: Settings = ctx.obj["settings"]
    config = load_config(settings.config_path)

    if file_path:
        data = read_mbox_file(file_path)
    else:
        target = url or export_url(working_group)
        click.echo(f"Fetching {target}")
        data = fetch_mbox_url(target)

    client = _draft_client(config, settings, fetch_drafts)
    with session_scope(ctx.obj["factory"]) as session:
        result = ingest_mbox(
            session,
            data,
            working_group,
            config=config,
            draft_client=client,  # type: ignore[arg-type]
        )
    click.echo(
        f"Ingested: {result.new_messages} new messages, "
        f"{result.threads} threads, {result.drafts} drafts touched."
    )


@main.command("threads")
@click.option("--working-group", "-w")
@click.option("--since", help="ISO date lower bound on last activity.")
@click.option("--until", help="ISO date upper bound on last activity.")
@click.option("--status", type=click.Choice([s.value for s in ThreadStatus]))
@click.option("--subject", help="Case-insensitive subject substring.")
@click.option("--limit", default=50, show_default=True)
@click.pass_context
def list_threads_cmd(
    ctx: click.Context,
    working_group: str | None,
    since: str | None,
    until: str | None,
    status: str | None,
    subject: str | None,
    limit: int,
) -> None:
    """List threads."""
    from wgtracker.queries import list_threads

    with session_scope(ctx.obj["factory"]) as session:
        rows = list_threads(
            session,
            working_group=working_group,
            since=_parse_date(since),
            until=_parse_date(until),
            status=ThreadStatus(status) if status else None,
            subject_contains=subject,
            limit=limit,
        )
        if not rows:
            click.echo("No threads found.")
            return
        for t in rows:
            last = t.last_activity_date.date().isoformat() if t.last_activity_date else "?"
            click.echo(
                f"{t.thread_id}  [{t.working_group}] {last}  "
                f"({t.message_count} msgs, {t.status.value})  {t.subject}"
            )


@main.command("thread")
@click.argument("thread_id")
@click.pass_context
def show_thread_cmd(ctx: click.Context, thread_id: str) -> None:
    """Show a thread: metadata, referenced drafts, and messages."""
    from wgtracker.queries import get_thread, thread_messages

    with session_scope(ctx.obj["factory"]) as session:
        thread = get_thread(session, thread_id)
        if thread is None:
            raise click.ClickException(f"Thread {thread_id} not found.")
        click.echo(f"Subject : {thread.subject}")
        click.echo(f"WG      : {thread.working_group}")
        click.echo(f"Status  : {thread.status.value}")
        click.echo(f"Activity: {thread.start_date} .. {thread.last_activity_date}")
        click.echo(f"Source  : {thread.archive_url or '(none)'}")
        click.echo(f"People  : {', '.join(thread.participants) or '(none)'}")
        if thread.drafts:
            click.echo("Drafts  :")
            for td in thread.drafts:
                versions = ", ".join(td.versions_referenced or []) or "unspecified"
                click.echo(f"  - {td.draft_name} (versions: {versions})")
        click.echo("Messages:")
        for m in thread_messages(session, thread_id):
            when = m.date.isoformat() if m.date else "?"
            click.echo(f"  {when}  {m.from_address}  {m.archive_url or ''}")


@main.command("drafts")
@click.option("--working-group", "-w")
@click.pass_context
def list_drafts_cmd(ctx: click.Context, working_group: str | None) -> None:
    """List referenced drafts with thread counts."""
    from wgtracker.queries import list_drafts

    with session_scope(ctx.obj["factory"]) as session:
        rows = list_drafts(session, working_group=working_group)
        if not rows:
            click.echo("No drafts found.")
            return
        for draft, count in rows:
            ver = draft.current_version or "?"
            title = draft.title or "(metadata not fetched)"
            click.echo(f"{draft.draft_name} {ver}  ({count} threads)  {title}")


@main.command("draft")
@click.argument("draft_name")
@click.pass_context
def show_draft_cmd(ctx: click.Context, draft_name: str) -> None:
    """Show draft metadata and threads referencing it."""
    from wgtracker.queries import get_draft, threads_for_draft

    with session_scope(ctx.obj["factory"]) as session:
        draft = get_draft(session, draft_name)
        if draft is None:
            raise click.ClickException(f"Draft {draft_name} not found.")
        click.echo(f"Name    : {draft.draft_name}")
        click.echo(f"Version : {draft.current_version or '?'}")
        click.echo(f"Title   : {draft.title or '(metadata not fetched)'}")
        click.echo(f"WG      : {draft.working_group or '?'}")
        click.echo(f"Status  : {draft.status or '?'}")
        click.echo(f"RFC     : {draft.rfc_number or '-'}")
        click.echo(f"Source  : {draft.datatracker_url or '?'}")
        click.echo("Threads :")
        for t in threads_for_draft(session, draft_name):
            click.echo(f"  {t.thread_id}  {t.subject}")


@main.group()
def pipeline() -> None:
    """Run pipeline stages (invoked by the scheduled GitHub Actions workflow)."""


@pipeline.command("ingest")
@click.option("--fetch-drafts/--no-fetch-drafts", default=True)
@click.pass_context
def pipeline_ingest(ctx: click.Context, fetch_drafts: bool) -> None:
    """Fetch + ingest all configured working groups from the IETF archive."""
    settings: Settings = ctx.obj["settings"]
    config = load_config(settings.config_path)
    client = _draft_client(config, settings, fetch_drafts)
    for wg in config.working_groups:
        url = export_url(wg.name)
        try:
            data = fetch_mbox_url(url)
        except Exception as exc:  # network/archive failure: log and continue
            log.warning("ingest_fetch_failed", working_group=wg.name, error=str(exc))
            continue
        with session_scope(ctx.obj["factory"]) as session:
            result = ingest_mbox(
                session,
                data,
                wg.name,
                config=config,
                draft_client=client,  # type: ignore[arg-type]
            )
        log.info("pipeline_ingest_wg", working_group=wg.name, **vars(result))


@pipeline.command("poll")
def pipeline_poll() -> None:
    """Poll and retrieve completed Anthropic batches; write results."""
    click.echo("pipeline poll: not yet implemented (Milestone 2)")


@pipeline.command("recategorize")
def pipeline_recategorize() -> None:
    """Re-categorize threads against the current topic taxonomy."""
    click.echo("pipeline recategorize: not yet implemented (Milestone 2)")


if __name__ == "__main__":
    main()
