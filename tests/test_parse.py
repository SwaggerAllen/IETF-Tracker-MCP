"""Tests for RFC 5322 / mbox parsing."""

from __future__ import annotations

from wgtracker.ingest.parse import normalize_message_id, parse_mbox_bytes


def test_normalize_message_id() -> None:
    assert normalize_message_id("<abc@x.com>") == "abc@x.com"
    assert normalize_message_id("  abc@x.com ") == "abc@x.com"
    assert normalize_message_id(None) is None
    assert normalize_message_id("") is None


def test_parse_sample(sample_mbox: bytes) -> None:
    msgs = list(parse_mbox_bytes(sample_mbox))
    # Six messages in the file, one with no Message-ID is skipped.
    assert len(msgs) == 5
    by_id = {m.message_id: m for m in msgs}

    m1 = by_id["msg1@example.com"]
    assert m1.from_address == "alice@example.com"
    assert m1.from_name == "Alice Example"
    assert m1.subject == "Extensions format"
    assert m1.date is not None and m1.date.tzinfo is not None
    assert m1.archive_url == "https://mailarchive.ietf.org/arch/msg/mls/AAA1"

    # References parsed, and in_reply_to falls back to the last reference.
    m3 = by_id["msg3@example.com"]
    assert m3.references == ["msg1@example.com", "msg2@example.com"]
    assert m3.in_reply_to == "msg2@example.com"


def test_malformed_skipped(sample_mbox: bytes) -> None:
    ids = {m.message_id for m in parse_mbox_bytes(sample_mbox)}
    assert "No message id here" not in ids
