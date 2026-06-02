"""Prompt construction for summarization and categorization.

Stable instruction blocks (the summarization rubric, the topic taxonomy) are
returned as cacheable system blocks — ``cache_control`` on the last block caches
the whole prefix across every request in a batch. Per-thread content (cleaned
messages, draft metadata, the summary to categorize) is volatile and goes in the
user turn, after the cached prefix.
"""

from __future__ import annotations

from wgtracker.config import AppConfig
from wgtracker.db.models import Message, Thread, ThreadDraft

SystemBlocks = list[dict[str, object]]

_SUMMARY_INSTRUCTIONS = """\
You summarize a single IETF mailing-list thread for a structured archive. Produce \
JSON matching the provided schema. Be precise and verifiable.

Rules:
- Describe what was discussed and the key positions taken, attributing each to the \
person who held it: "Position X was advocated by <name>, with <name> raising <concern>". \
Do NOT write "the working group decided X" unless there is a clear consensus signal in \
the thread (an explicit call for consensus, a chair declaration, broad agreement).
- Choose consensus_state honestly:
  - clear_consensus: explicit agreement or a chair confirming consensus
  - emerging_consensus: trending toward agreement, not yet confirmed
  - active_debate: substantive disagreement still open
  - no_consensus: discussed but no agreement reached
  - single_voice: essentially one participant; no real discussion
- Choose status: active (ongoing), concluded (resolved/wrapped up), or abandoned \
(petered out with no resolution).
- When drafts are referenced, ground the summary in what the thread argued ABOUT the \
draft, using the provided draft metadata. Do not invent draft contents.
- key_positions: list the distinct positions; holder is a name or email; context is a \
one-line elaboration. Empty list if there were no distinct positions.
- Keep the summary factual and concise. Do not speculate beyond the messages."""


def summary_system() -> SystemBlocks:
    return [{"type": "text", "text": _SUMMARY_INSTRUCTIONS, "cache_control": {"type": "ephemeral"}}]


def _draft_context(drafts: list[ThreadDraft]) -> str:
    lines: list[str] = []
    for td in drafts:
        d = td.draft
        versions = ", ".join(td.versions_referenced or []) or "unspecified"
        title = d.title or "(title unknown)"
        abstract = (d.abstract or "").strip()
        if len(abstract) > 500:
            abstract = abstract[:500] + "…"
        lines.append(
            f"- {d.draft_name} (versions discussed: {versions})\n"
            f"  title: {title}\n"
            f"  abstract: {abstract or '(none)'}"
        )
    return "\n".join(lines) if lines else "(none referenced)"


def summary_user(thread: Thread, messages: list[Message], drafts: list[ThreadDraft]) -> str:
    parts = [
        f"Working group: {thread.working_group}",
        f"Subject: {thread.subject}",
        "",
        "Referenced drafts:",
        _draft_context(drafts),
        "",
        f"Messages ({len(messages)}):",
    ]
    for m in messages:
        when = m.date.isoformat() if m.date else "unknown date"
        who = m.from_name or m.from_address or "unknown"
        body = m.body_cleaned.strip() or "(empty after cleaning)"
        parts.append(f"\n--- {who} <{m.from_address}> @ {when} ---\n{body}")
    return "\n".join(parts)


def categorization_system(config: AppConfig) -> SystemBlocks:
    taxonomy = "\n".join(
        f"- {t.name}: {t.description}"
        + (f" (keywords: {', '.join(t.keywords)})" if t.keywords else "")
        for t in config.topics
    )
    instructions = (
        "You categorize an IETF mailing-list thread against a fixed topic taxonomy. "
        "Return JSON matching the schema: a list of relevant topics, each with a "
        "confidence in [0,1]. Only use topic names from the taxonomy below; omit "
        "topics that do not apply. It is fine to return an empty list if none apply.\n\n"
        "Topic taxonomy:\n" + taxonomy
    )
    return [{"type": "text", "text": instructions, "cache_control": {"type": "ephemeral"}}]


def categorization_user(thread: Thread) -> str:
    return (
        f"Subject: {thread.subject}\n"
        f"Working group: {thread.working_group}\n\n"
        f"Summary:\n{thread.summary or '(no summary)'}"
    )
