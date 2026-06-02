"""IETF Datatracker metadata client and draft-sync logic.

NOTE: the Datatracker Tastypie response shape could not be validated live from
the build environment (ietf.org is blocked by the network policy). Parsing is
deliberately defensive (``.get`` everywhere, tolerate missing fields) and is
covered by fixture-based tests; field mapping should be confirmed against the
live API at runtime.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx

from wgtracker.db.models import Draft
from wgtracker.logging import get_logger

log = get_logger(__name__)


@dataclass
class DraftMetadata:
    name: str
    title: str | None = None
    current_version: str | None = None
    abstract: str | None = None
    working_group: str | None = None
    status: str | None = None
    rfc_number: str | None = None
    authors: list[str] = field(default_factory=list)
    datatracker_url: str = ""
    versions: list[dict[str, str]] = field(default_factory=list)


class DatatrackerClient(Protocol):
    def fetch(self, name: str) -> DraftMetadata | None: ...


def _slug_from_uri(uri: str | None) -> str | None:
    """Derive a slug from a Tastypie resource URI like ``/api/v1/group/mls/``."""
    if not uri:
        return None
    return uri.rstrip("/").rsplit("/", 1)[-1] or None


def parse_document(obj: dict[str, Any]) -> DraftMetadata:
    """Map a Datatracker document object to ``DraftMetadata`` (defensively)."""
    name = str(obj.get("name", ""))
    rev = obj.get("rev")
    rfc_number = name[3:] if name.startswith("rfc") and name[3:].isdigit() else None
    status = obj.get("std_level") or obj.get("intended_std_level")
    versions: list[dict[str, str]] = []
    if rev:
        versions.append({"version": str(rev)})
    return DraftMetadata(
        name=name,
        title=obj.get("title"),
        current_version=f"-{rev}" if rev else None,
        abstract=obj.get("abstract"),
        working_group=_slug_from_uri(obj.get("group")),
        status=str(status) if status else None,
        rfc_number=rfc_number,
        datatracker_url=f"https://datatracker.ietf.org/doc/{name}/" if name else "",
        versions=versions,
    )


class HttpxDatatrackerClient:
    """Fetches draft metadata from the Datatracker JSON API."""

    def __init__(
        self,
        api_base: str = "https://datatracker.ietf.org/api/v1/",
        *,
        client: httpx.Client | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._api_base = api_base.rstrip("/") + "/"
        self._client = client or httpx.Client(follow_redirects=True, timeout=timeout)

    def fetch(self, name: str) -> DraftMetadata | None:
        url = f"{self._api_base}doc/document/"
        try:
            resp = self._client.get(url, params={"name": name, "format": "json"})
            resp.raise_for_status()
            payload = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("datatracker_fetch_failed", name=name, error=str(exc))
            return None
        objects = payload.get("objects") if isinstance(payload, dict) else None
        if not objects:
            return None
        return parse_document(objects[0])


def ensure_drafts(
    session: Any,
    names: set[str],
    *,
    client: DatatrackerClient | None = None,
    refresh_days: int = 30,
    now: datetime | None = None,
) -> int:
    """Ensure a ``Draft`` row exists for each referenced name.

    Creates a stub row (name only) when no client is supplied or metadata is
    unavailable, so thread/draft links are recordable offline. Enriches from the
    Datatracker when a client is given, refreshing rows older than ``refresh_days``.
    """
    now = now or datetime.now(UTC)
    touched = 0
    for name in sorted(names):
        existing = session.get(Draft, name)
        needs_fetch = existing is None or (
            existing.last_checked is not None and (now - existing.last_checked).days >= refresh_days
        )
        meta = client.fetch(name) if (client and needs_fetch) else None

        if existing is None:
            existing = Draft(draft_name=name, first_seen=now)
            session.add(existing)
            touched += 1
        if meta is not None:
            _apply_metadata(existing, meta)
            existing.last_checked = now
        existing.first_seen = existing.first_seen or now
    return touched


def _apply_metadata(draft: Draft, meta: DraftMetadata) -> None:
    draft.title = meta.title
    draft.current_version = meta.current_version
    draft.abstract = meta.abstract
    draft.working_group = meta.working_group
    draft.status = meta.status
    draft.rfc_number = meta.rfc_number
    draft.authors = meta.authors
    draft.datatracker_url = meta.datatracker_url
    draft.versions = meta.versions
