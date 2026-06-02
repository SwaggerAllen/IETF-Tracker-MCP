"""Pydantic models and JSON schemas for structured LLM outputs.

The schemas are hand-written (rather than derived from the pydantic models) so
they stay within the structured-output subset the API supports
(``additionalProperties: false``, enums, no numeric/length constraints), and the
returned JSON is validated against the pydantic models before being persisted.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from wgtracker.db.enums import ConsensusState, ThreadStatus


class KeyPosition(BaseModel):
    position: str
    holder: str
    context: str = ""


class SummaryOutput(BaseModel):
    summary: str
    key_positions: list[KeyPosition] = Field(default_factory=list)
    consensus_state: ConsensusState
    status: ThreadStatus


class TopicScore(BaseModel):
    name: str
    confidence: float


class CategorizationOutput(BaseModel):
    topics: list[TopicScore] = Field(default_factory=list)


_CONSENSUS_VALUES = [s.value for s in ConsensusState]
_STATUS_VALUES = [s.value for s in ThreadStatus]

SUMMARY_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "summary": {"type": "string"},
        "key_positions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "position": {"type": "string"},
                    "holder": {"type": "string"},
                    "context": {"type": "string"},
                },
                "required": ["position", "holder", "context"],
            },
        },
        "consensus_state": {"type": "string", "enum": _CONSENSUS_VALUES},
        "status": {"type": "string", "enum": _STATUS_VALUES},
    },
    "required": ["summary", "key_positions", "consensus_state", "status"],
}

CATEGORY_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "topics": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["name", "confidence"],
            },
        }
    },
    "required": ["topics"],
}
