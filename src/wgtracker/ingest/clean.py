"""Strip quoted text and signature blocks before summarisation."""

from __future__ import annotations

import re

_QUOTE_PREFIX = re.compile(r"^\s*>+")
# "On <date>, <name> wrote:" attribution that precedes a quoted block.
_ATTRIBUTION = re.compile(r"^\s*On .+?(?:wrote|writes|said):\s*$", re.IGNORECASE)
# Outlook-style quoted reply header.
_ORIGINAL_MESSAGE = re.compile(r"^\s*-{2,}\s*Original Message\s*-{2,}\s*$", re.IGNORECASE)
# RFC 3676 signature delimiter is exactly "-- " on its own line.
_SIG_DELIMITER = re.compile(r"^-- ?$")


def strip_quoted_text(body: str) -> str:
    """Remove quoted lines and their attribution headers."""
    lines = body.splitlines()
    out: list[str] = []
    for i, line in enumerate(lines):
        if _ORIGINAL_MESSAGE.match(line):
            break  # everything after is the quoted original
        if _QUOTE_PREFIX.match(line):
            continue
        # Drop an attribution line only when a quote immediately follows it.
        if _ATTRIBUTION.match(line):
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            if _QUOTE_PREFIX.match(nxt) or _ATTRIBUTION.match(nxt):
                continue
        out.append(line)
    return "\n".join(out)


def strip_signature(body: str) -> str:
    """Remove a trailing signature block delimited by ``-- ``."""
    lines = body.splitlines()
    for i, line in enumerate(lines):
        if _SIG_DELIMITER.match(line):
            return "\n".join(lines[:i])
    return body


def _collapse_blank_lines(body: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", body).strip()


def clean_body(body: str) -> str:
    """Full cleaning pipeline: de-quote, de-sign, collapse whitespace."""
    return _collapse_blank_lines(strip_signature(strip_quoted_text(body)))
