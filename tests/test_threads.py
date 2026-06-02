"""Tests for thread reconstruction."""

from __future__ import annotations

from datetime import UTC, datetime

from wgtracker.ingest.parse import parse_mbox_bytes
from wgtracker.ingest.threads import normalize_subject, reconstruct_threads

NOW = datetime(2025, 2, 20, tzinfo=UTC)


def test_normalize_subject() -> None:
    assert normalize_subject("Re: [MLS] Extensions format") == "extensions format"
    assert normalize_subject("Fwd: Re: Hello") == "hello"


def test_header_based_grouping(sample_mbox: bytes) -> None:
    msgs = list(parse_mbox_bytes(sample_mbox))
    threads, mapping = reconstruct_threads(msgs, "mls", now=NOW)
    # Thread A (3 msgs via headers) + Thread B (2 msgs via subject merge).
    assert len(threads) == 2
    sizes = sorted(t.message_count for t in threads)
    assert sizes == [2, 3]
    assert all(tid.startswith("t-") for tid in mapping.values())


def test_subject_merge_can_be_disabled(sample_mbox: bytes) -> None:
    msgs = list(parse_mbox_bytes(sample_mbox))
    threads, _ = reconstruct_threads(msgs, "mls", subject_merge_window_days=None, now=NOW)
    # Without the fallback, the orphaned post-quantum reply is its own thread.
    assert len(threads) == 3


def test_thread_id_stable_when_replies_added(sample_mbox: bytes) -> None:
    msgs = list(parse_mbox_bytes(sample_mbox))
    full, _ = reconstruct_threads(msgs, "mls", now=NOW)
    # Reconstruct from just the root of thread A; its id must match.
    root_only = [m for m in msgs if m.message_id == "msg1@example.com"]
    partial, _ = reconstruct_threads(root_only, "mls", now=NOW)
    a_full = next(t for t in full if "msg1@example.com" in t.message_ids)
    assert partial[0].thread_id == a_full.thread_id


def test_status_active(sample_mbox: bytes) -> None:
    msgs = list(parse_mbox_bytes(sample_mbox))
    threads, _ = reconstruct_threads(msgs, "mls", now=NOW)
    assert all(t.status.value == "active" for t in threads)
