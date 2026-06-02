"""RFC 5322 / MIME parsing of mbox archives.

Defensive by design: malformed messages are skipped (logged by the caller) rather
than crashing the pipeline. Message-IDs are normalised (angle brackets stripped)
so they join consistently across ``Message-ID``/``In-Reply-To``/``References``.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email import message_from_bytes, policy
from email.message import EmailMessage
from email.utils import getaddresses, parsedate_to_datetime

# mbox messages are separated by lines beginning with "From " (the envelope line).
_FROM_SEPARATOR = re.compile(rb"(?m)^From .*\r?\n")
_MSGID = re.compile(r"<([^>]+)>")


@dataclass
class ParsedMessage:
    message_id: str
    subject: str
    from_address: str
    from_name: str
    date: datetime | None
    in_reply_to: str | None
    references: list[str] = field(default_factory=list)
    body_original: str = ""
    archive_url: str | None = None


def normalize_message_id(raw: str | None) -> str | None:
    """Extract the addr-spec from a Message-ID header value."""
    if not raw:
        return None
    match = _MSGID.search(raw)
    value = match.group(1) if match else raw.strip().strip("<>")
    value = value.strip()
    return value or None


def _extract_references(msg: EmailMessage) -> list[str]:
    refs: list[str] = []
    for header in ("References", "In-Reply-To"):
        raw = msg.get(header)
        if not raw:
            continue
        for found in _MSGID.findall(raw):
            cleaned = found.strip()
            if cleaned and cleaned not in refs:
                refs.append(cleaned)
    return refs


def _extract_date(msg: EmailMessage) -> datetime | None:
    raw = msg.get("Date")
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def _extract_body(msg: EmailMessage) -> str:
    """Best-effort plain-text body extraction, tolerant of broken encodings."""
    try:
        body = msg.get_body(preferencelist=("plain",))
    except Exception:
        body = None
    if body is not None:
        try:
            content = body.get_content()
            return content if isinstance(content, str) else str(content)
        except (LookupError, ValueError, UnicodeError):
            pass
    # Fallback: walk parts and concatenate any decodable text/plain payloads.
    chunks: list[str] = []
    for part in msg.walk():
        if part.get_content_maintype() != "text":
            continue
        payload = part.get_payload(decode=True)
        if isinstance(payload, bytes):
            charset = part.get_content_charset() or "utf-8"
            try:
                chunks.append(payload.decode(charset, errors="replace"))
            except LookupError:
                chunks.append(payload.decode("utf-8", errors="replace"))
    return "\n".join(chunks)


def _extract_archive_url(msg: EmailMessage) -> str | None:
    """Prefer the ``Archived-At`` header — the canonical per-message permalink."""
    raw = msg.get("Archived-At")
    if not raw:
        return None
    match = re.search(r"https?://\S+", raw)
    url = match.group(0) if match else raw.strip()
    return url.strip("<>").strip() or None


def parse_email_message(msg: EmailMessage) -> ParsedMessage | None:
    """Convert an ``EmailMessage`` to a ``ParsedMessage``; ``None`` if unusable."""
    message_id = normalize_message_id(msg.get("Message-ID"))
    if not message_id:
        return None

    name, address = "", ""
    addrs = getaddresses([str(msg.get("From", ""))])
    if addrs:
        name, address = addrs[0]

    refs = _extract_references(msg)
    in_reply_to = normalize_message_id(msg.get("In-Reply-To"))
    if in_reply_to is None and refs:
        in_reply_to = refs[-1]

    return ParsedMessage(
        message_id=message_id,
        subject=str(msg.get("Subject", "")).strip(),
        from_address=address.lower(),
        from_name=name,
        date=_extract_date(msg),
        in_reply_to=in_reply_to,
        references=refs,
        body_original=_extract_body(msg),
        archive_url=_extract_archive_url(msg),
    )


def iter_mbox_messages(data: bytes) -> Iterator[EmailMessage]:
    """Split raw mbox bytes into individual ``EmailMessage`` objects."""
    if not data:
        return
    # Ensure the first message is captured even without a leading separator.
    parts = _FROM_SEPARATOR.split(b"\n" + data)
    for raw in parts:
        chunk = raw.strip(b"\r\n")
        if not chunk:
            continue
        try:
            msg = message_from_bytes(chunk, policy=policy.default)
        except Exception:
            continue
        if isinstance(msg, EmailMessage):
            yield msg


def parse_mbox_bytes(data: bytes) -> Iterator[ParsedMessage]:
    """Yield parsed messages from raw mbox bytes, skipping unusable ones."""
    for msg in iter_mbox_messages(data):
        parsed = parse_email_message(msg)
        if parsed is not None:
            yield parsed
