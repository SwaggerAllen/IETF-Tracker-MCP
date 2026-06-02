"""FastMCP wiring: registers the query tools for MCP-over-HTTP.

The tool *logic* lives in ``tools.py`` (unit-tested offline); this module is the
thin transport layer that registers them with FastMCP. Every tool opens a short
DB session and returns serializable records that include source URLs.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from wgtracker.db.session import session_scope
from wgtracker.logging import get_logger
from wgtracker.mcp_server import tools

log = get_logger(__name__)


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    dt = datetime.fromisoformat(value)
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt


def build_mcp(session_factory: sessionmaker[Session]) -> Any:
    """Build a FastMCP server exposing the query tools."""
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("wgtracker", stateless_http=True)

    @mcp.tool()
    def search_threads(
        topic: str | None = None,
        working_group: str | None = None,
        since: str | None = None,
        until: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Search summarized threads by topic/WG/date/status. Includes archive_url."""
        with session_scope(session_factory) as s:
            return tools.search_threads(
                s,
                topic=topic,
                working_group=working_group,
                since=_parse(since),
                until=_parse(until),
                status=status,
                limit=limit,
            )

    @mcp.tool()
    def get_thread_detail(thread_id: str) -> dict[str, Any] | None:
        """Full summary, key positions, consensus, participants, drafts, archive_url."""
        with session_scope(session_factory) as s:
            return tools.get_thread_detail(s, thread_id)

    @mcp.tool()
    def recent_activity(
        topic: str | None = None, working_group: str | None = None, days: int = 30
    ) -> list[dict[str, Any]]:
        """Threads with recent activity in a topic / working group."""
        with session_scope(session_factory) as s:
            return tools.recent_activity(s, topic=topic, working_group=working_group, days=days)

    @mcp.tool()
    def topic_overview(topic: str, working_group: str | None = None) -> dict[str, Any]:
        """Aggregated state of discussion for a topic (status + consensus breakdown)."""
        with session_scope(session_factory) as s:
            return tools.topic_overview(s, topic, working_group=working_group)

    @mcp.tool()
    def list_drafts(
        topic: str | None = None, working_group: str | None = None
    ) -> list[dict[str, Any]]:
        """List drafts with thread counts and datatracker_url."""
        with session_scope(session_factory) as s:
            return tools.list_drafts(s, topic=topic, working_group=working_group)

    @mcp.tool()
    def get_draft(draft_name: str) -> dict[str, Any] | None:
        """Draft metadata plus the threads referencing it (with version specifics)."""
        with session_scope(session_factory) as s:
            return tools.get_draft(s, draft_name)

    @mcp.tool()
    def draft_discussion_history(draft_name: str) -> list[dict[str, Any]]:
        """Chronological threads about a draft, with which version each discussed."""
        with session_scope(session_factory) as s:
            return tools.draft_discussion_history(s, draft_name)

    return mcp


@contextlib.asynccontextmanager
async def mcp_lifespan(mcp: Any) -> AsyncIterator[None]:
    """Run the FastMCP session manager for the lifetime of the host app."""
    async with mcp.session_manager.run():
        yield
