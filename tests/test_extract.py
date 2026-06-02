"""Tests for draft / RFC reference extraction."""

from __future__ import annotations

from wgtracker.drafts.extract import DraftRef, extract_references


def test_versioned_draft() -> None:
    refs = extract_references("see draft-ietf-mls-extensions-04 please")
    assert refs == [DraftRef("draft-ietf-mls-extensions", "04")]


def test_bare_draft_and_rfc() -> None:
    refs = set(extract_references("draft-ietf-mls-protocol and RFC 9420"))
    assert DraftRef("draft-ietf-mls-protocol", None) in refs
    assert DraftRef("rfc9420", None) in refs


def test_multiple_versions_preserved() -> None:
    refs = extract_references("draft-ietf-mls-extensions-04 vs draft-ietf-mls-extensions-03")
    assert set(refs) == {
        DraftRef("draft-ietf-mls-extensions", "03"),
        DraftRef("draft-ietf-mls-extensions", "04"),
    }


def test_datatracker_url() -> None:
    refs = extract_references("https://datatracker.ietf.org/doc/draft-ietf-mls-extensions/")
    assert refs == [DraftRef("draft-ietf-mls-extensions", None)]


def test_archive_id_url() -> None:
    refs = extract_references("https://www.ietf.org/archive/id/draft-ietf-mls-extensions-04.html")
    assert refs == [DraftRef("draft-ietf-mls-extensions", "04")]


def test_bare_dropped_when_versioned_present() -> None:
    text = "draft-ietf-mls-extensions and draft-ietf-mls-extensions-04"
    refs = extract_references(text)
    assert refs == [DraftRef("draft-ietf-mls-extensions", "04")]
