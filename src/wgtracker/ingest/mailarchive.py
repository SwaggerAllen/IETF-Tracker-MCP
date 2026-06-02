"""Fetch mbox archives from the IETF mail archive (or a local file).

The mail archive exposes a per-list mbox export. Network access to ietf.org is
required at runtime; for offline development and the Milestone 1 spot-check, a
local mbox file path can be used instead.
"""

from __future__ import annotations

import time
from pathlib import Path

import httpx

from wgtracker.logging import get_logger

log = get_logger(__name__)

EXPORT_PATH = "arch/export/mbox/"
ARCHIVE_BASE = "https://mailarchive.ietf.org/"


def export_url(working_group: str, *, base: str = ARCHIVE_BASE) -> str:
    """Build the mbox export URL for a working-group list."""
    return f"{base.rstrip('/')}/{EXPORT_PATH}?email_list={working_group}"


def fetch_mbox_url(
    url: str,
    *,
    timeout: float = 60.0,
    retries: int = 4,
    client: httpx.Client | None = None,
) -> bytes:
    """GET an mbox export with exponential backoff on transient failures."""
    owns_client = client is None
    client = client or httpx.Client(follow_redirects=True, timeout=timeout)
    try:
        last_exc: Exception | None = None
        for attempt in range(retries):
            try:
                resp = client.get(url)
                resp.raise_for_status()
                return resp.content
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                last_exc = exc
                wait = 2**attempt
                log.warning("mailarchive_fetch_retry", url=url, attempt=attempt + 1, wait=wait)
                time.sleep(wait)
        assert last_exc is not None
        raise last_exc
    finally:
        if owns_client:
            client.close()


def read_mbox_file(path: str | Path) -> bytes:
    """Read an mbox file from disk (offline ingestion path)."""
    return Path(path).read_bytes()
