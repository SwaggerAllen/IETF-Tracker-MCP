"""Tests for quote/signature stripping."""

from __future__ import annotations

from wgtracker.ingest.clean import clean_body, strip_quoted_text, strip_signature


def test_strip_quoted_text_removes_quotes_and_attribution() -> None:
    body = "On Mon, Alice wrote:\n> old point one\n> old point two\nMy new reply.\n"
    cleaned = strip_quoted_text(body)
    assert "old point" not in cleaned
    assert "Alice wrote" not in cleaned
    assert "My new reply." in cleaned


def test_strip_original_message_block() -> None:
    body = "Reply text.\n-----Original Message-----\nquoted stuff\nmore"
    assert strip_quoted_text(body).strip() == "Reply text."


def test_strip_signature() -> None:
    body = "Real content.\n-- \nAlice\nExample Corp"
    assert strip_signature(body).strip() == "Real content."


def test_strip_signature_tolerates_no_trailing_space() -> None:
    body = "Real content.\n--\nAlice"
    assert strip_signature(body).strip() == "Real content."


def test_clean_body_full() -> None:
    body = "On Mon, Alice wrote:\n> quoted\nKeep this.\n\n\n\n-- \nsig"
    cleaned = clean_body(body)
    assert cleaned == "Keep this."
