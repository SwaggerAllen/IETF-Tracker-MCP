"""Extract draft / RFC references from message text.

Handles the five reference forms from the spec:
  - bare draft name:        draft-ietf-mls-extensions
  - versioned draft name:   draft-ietf-mls-extensions-04
  - RFC reference:          RFC 9420
  - datatracker URL:        https://datatracker.ietf.org/doc/draft-ietf-mls-extensions/
  - archived-id URL:        https://www.ietf.org/archive/id/draft-ietf-mls-extensions-04.html

References are canonicalised to a ``name`` (lowercase draft name, or ``rfcNNNN``)
with an optional two-digit ``version``. Version-specificity is preserved because
a discussion about ``-03`` differs from one about ``-04``. When both a bare and a
versioned reference to the same draft appear, the bare one is dropped as redundant.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# A draft token; an optional trailing -NN is treated as the version.
_DRAFT = re.compile(r"\bdraft-[a-z0-9]+(?:-[a-z0-9]+)+\b", re.IGNORECASE)
_VERSION_SUFFIX = re.compile(r"^(?P<base>.+)-(?P<version>\d{2})$")
_RFC = re.compile(r"\bRFC[\s-]?(\d{3,5})\b", re.IGNORECASE)
_ARCHIVE_ID = re.compile(
    r"ietf\.org/archive/id/(draft-[a-z0-9-]+?)-(\d{2})\.(?:txt|html|pdf)",
    re.IGNORECASE,
)
_DATATRACKER = re.compile(r"datatracker\.ietf\.org/doc/(draft-[a-z0-9-]+|rfc\d+)", re.IGNORECASE)


@dataclass(frozen=True)
class DraftRef:
    name: str
    version: str | None = None


def _split_version(token: str) -> tuple[str, str | None]:
    match = _VERSION_SUFFIX.match(token)
    if match:
        return match.group("base"), match.group("version")
    return token, None


def _normalize(name: str) -> str:
    return name.lower().rstrip("/-.")


def extract_references(text: str) -> list[DraftRef]:
    """Return unique draft/RFC references found in ``text`` (sorted, deterministic)."""
    refs: set[DraftRef] = set()

    for m in _ARCHIVE_ID.finditer(text):
        refs.add(DraftRef(_normalize(m.group(1)), m.group(2)))
    for m in _DATATRACKER.finditer(text):
        refs.add(DraftRef(_normalize(m.group(1)), None))
    for m in _DRAFT.finditer(text):
        base, version = _split_version(m.group(0))
        refs.add(DraftRef(_normalize(base), version))
    for m in _RFC.finditer(text):
        refs.add(DraftRef(f"rfc{int(m.group(1))}", None))

    # A bare reference is redundant when a versioned reference to the same draft exists.
    versioned = {r.name for r in refs if r.version is not None}
    result = [r for r in refs if not (r.version is None and r.name in versioned)]
    return sorted(result, key=lambda r: (r.name, r.version or ""))
