"""Tests for datatracker metadata parsing and draft sync."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from wgtracker.drafts.datatracker import (
    DraftMetadata,
    ensure_drafts,
    parse_document,
)

NOW = datetime(2025, 2, 20, tzinfo=UTC)


def test_parse_document_draft() -> None:
    meta = parse_document(
        {
            "name": "draft-ietf-mls-extensions",
            "rev": "04",
            "title": "The Messaging Layer Security (MLS) Extensions",
            "abstract": "This document describes extensions.",
            "group": "/api/v1/group/mls/",
            "std_level": "Proposed Standard",
        }
    )
    assert meta.current_version == "-04"
    assert meta.working_group == "mls"
    assert meta.status == "Proposed Standard"
    assert meta.datatracker_url.endswith("/draft-ietf-mls-extensions/")


def test_parse_document_rfc() -> None:
    meta = parse_document({"name": "rfc9420", "title": "MLS Protocol"})
    assert meta.rfc_number == "9420"


class _FakeClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def fetch(self, name: str) -> DraftMetadata | None:
        self.calls.append(name)
        if name == "draft-ietf-mls-extensions":
            return DraftMetadata(name=name, title="MLS Extensions", current_version="-04")
        return None


def test_ensure_drafts_creates_and_enriches(session: Session) -> None:
    client = _FakeClient()
    touched = ensure_drafts(
        session,
        {"draft-ietf-mls-extensions", "rfc9420"},
        client=client,
        now=NOW,
    )
    session.commit()
    assert touched == 2
    from wgtracker.db.models import Draft

    enriched = session.get(Draft, "draft-ietf-mls-extensions")
    assert enriched is not None and enriched.title == "MLS Extensions"
    stub = session.get(Draft, "rfc9420")
    assert stub is not None and stub.title is None  # no metadata, stub row


def test_ensure_drafts_idempotent(session: Session) -> None:
    ensure_drafts(session, {"rfc9420"}, now=NOW)
    session.commit()
    touched = ensure_drafts(session, {"rfc9420"}, now=NOW)
    session.commit()
    assert touched == 0
