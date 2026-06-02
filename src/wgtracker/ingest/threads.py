"""Reconstruct threads from individual messages.

Primary grouping is by ``In-Reply-To`` / ``References`` headers (union-find over
the messages actually present). Broken In-Reply-To chains are optionally merged
by normalised subject within a time window. The thread id is derived from the
topological root (the original post), so it stays stable as replies are added.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from wgtracker.db.enums import ThreadStatus
from wgtracker.ingest.parse import ParsedMessage

_MIN_DT = datetime(1, 1, 1, tzinfo=UTC)
_RE_PREFIX = re.compile(r"^\s*(re|fwd|fw|aw|sv)\s*:\s*", re.IGNORECASE)
_RE_LISTTAG = re.compile(r"^\s*\[[^\]]+\]\s*")


@dataclass
class ReconstructedThread:
    thread_id: str
    subject: str
    working_group: str
    start_date: datetime | None
    last_activity_date: datetime | None
    message_count: int
    archive_url: str | None
    status: ThreadStatus
    participants: list[str]
    message_ids: list[str] = field(default_factory=list)


def normalize_subject(subject: str) -> str:
    """Strip Re:/Fwd: prefixes and leading [list] tags for grouping."""
    prev, cur = None, subject.strip()
    while cur != prev:
        prev = cur
        cur = _RE_LISTTAG.sub("", cur).strip()
        cur = _RE_PREFIX.sub("", cur).strip()
    return cur.lower()


class _UnionFind:
    def __init__(self, items: list[str]) -> None:
        self._parent = {item: item for item in items}

    def find(self, item: str) -> str:
        root = item
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[item] != root:
            self._parent[item], item = root, self._parent[item]
        return root

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._parent[ra] = rb


def _parent_in_set(msg: ParsedMessage, present: set[str]) -> str | None:
    """The in-set parent message id, if any."""
    if msg.in_reply_to and msg.in_reply_to in present:
        return msg.in_reply_to
    for ref in reversed(msg.references):
        if ref in present:
            return ref
    return None


def _sort_key(msg: ParsedMessage) -> tuple[bool, datetime, str]:
    return (msg.date is None, msg.date or _MIN_DT, msg.message_id)


def reconstruct_threads(
    messages: list[ParsedMessage],
    working_group: str,
    *,
    active_threshold_days: int = 90,
    subject_merge_window_days: int | None = 14,
    now: datetime | None = None,
) -> tuple[list[ReconstructedThread], dict[str, str]]:
    """Group messages into threads.

    Returns the reconstructed threads and a ``message_id -> thread_id`` map.
    """
    now = now or datetime.now(UTC)
    by_id = {m.message_id: m for m in messages}
    present = set(by_id)
    uf = _UnionFind(list(present))

    for msg in messages:
        parent = _parent_in_set(msg, present)
        if parent is not None:
            uf.union(msg.message_id, parent)

    if subject_merge_window_days is not None:
        _merge_by_subject(messages, by_id, uf, subject_merge_window_days)

    components: dict[str, list[ParsedMessage]] = {}
    for msg in messages:
        components.setdefault(uf.find(msg.message_id), []).append(msg)

    threads: list[ReconstructedThread] = []
    msg_to_thread: dict[str, str] = {}
    for members in components.values():
        thread = _build_thread(members, present, working_group, active_threshold_days, now)
        threads.append(thread)
        for mid in thread.message_ids:
            msg_to_thread[mid] = thread.thread_id
    return threads, msg_to_thread


def _merge_by_subject(
    messages: list[ParsedMessage],
    by_id: dict[str, ParsedMessage],
    uf: _UnionFind,
    window_days: int,
) -> None:
    """Merge same-subject components whose time spans are within the window."""
    window = timedelta(days=window_days)
    groups: dict[str, list[ParsedMessage]] = {}
    for msg in messages:
        key = normalize_subject(msg.subject)
        if key:
            groups.setdefault(key, []).append(msg)
    for group in groups.values():
        dated = sorted((m for m in group if m.date is not None), key=_sort_key)
        for prev, cur in zip(dated, dated[1:], strict=False):
            assert prev.date is not None and cur.date is not None
            if cur.date - prev.date <= window:
                uf.union(prev.message_id, cur.message_id)


def _build_thread(
    members: list[ParsedMessage],
    present: set[str],
    working_group: str,
    active_threshold_days: int,
    now: datetime,
) -> ReconstructedThread:
    roots = [m for m in members if _parent_in_set(m, present) is None]
    root = min(roots or members, key=_sort_key)
    dates = [m.date for m in members if m.date is not None]
    start = min(dates) if dates else None
    last = max(dates) if dates else None
    status = ThreadStatus.active
    if last is not None and last < now - timedelta(days=active_threshold_days):
        status = ThreadStatus.concluded
    participants = sorted({m.from_address for m in members if m.from_address})
    thread_id = "t-" + hashlib.sha1(root.message_id.encode("utf-8")).hexdigest()[:16]
    return ReconstructedThread(
        thread_id=thread_id,
        subject=root.subject,
        working_group=working_group,
        start_date=start,
        last_activity_date=last,
        message_count=len(members),
        archive_url=root.archive_url,
        status=status,
        participants=participants,
        message_ids=[m.message_id for m in members],
    )
