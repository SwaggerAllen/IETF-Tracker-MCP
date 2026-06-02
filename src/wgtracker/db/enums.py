"""Enumerated domain values stored as native Postgres enums."""

from __future__ import annotations

import enum


class ThreadStatus(enum.StrEnum):
    active = "active"
    concluded = "concluded"
    abandoned = "abandoned"


class ConsensusState(enum.StrEnum):
    clear_consensus = "clear_consensus"
    emerging_consensus = "emerging_consensus"
    active_debate = "active_debate"
    no_consensus = "no_consensus"
    single_voice = "single_voice"


class BatchStatus(enum.StrEnum):
    pending = "pending"
    submitted = "submitted"
    completed = "completed"
    retrieved = "retrieved"
    failed = "failed"
