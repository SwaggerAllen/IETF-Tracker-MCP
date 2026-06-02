"""SQLAlchemy models for the WG Activity Tracker.

Mirrors the data model in the build spec: threads, messages, topics,
thread_topics, drafts, thread_drafts, processing_log, plus a batch_jobs table
for tracking asynchronous Anthropic Batch API submissions.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from wgtracker.db.base import Base, JSONType
from wgtracker.db.enums import BatchStatus, ConsensusState, ThreadStatus


class Thread(Base):
    __tablename__ = "threads"

    thread_id: Mapped[str] = mapped_column(String, primary_key=True)
    subject: Mapped[str] = mapped_column(String, index=True)
    working_group: Mapped[str] = mapped_column(String, index=True)
    start_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_activity_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    archive_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[ThreadStatus] = mapped_column(
        Enum(ThreadStatus, name="thread_status"), default=ThreadStatus.active
    )
    summary: Mapped[str | None] = mapped_column(Text)
    key_positions: Mapped[list[dict[str, str]] | None] = mapped_column(JSONType)
    consensus_state: Mapped[ConsensusState | None] = mapped_column(
        Enum(ConsensusState, name="consensus_state")
    )
    participants: Mapped[list[str]] = mapped_column(JSONType, default=list)
    last_processed: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    messages: Mapped[list[Message]] = relationship(
        back_populates="thread", cascade="all, delete-orphan"
    )
    topics: Mapped[list[ThreadTopic]] = relationship(
        back_populates="thread", cascade="all, delete-orphan"
    )
    drafts: Mapped[list[ThreadDraft]] = relationship(
        back_populates="thread", cascade="all, delete-orphan"
    )


class Message(Base):
    __tablename__ = "messages"

    message_id: Mapped[str] = mapped_column(String, primary_key=True)
    thread_id: Mapped[str | None] = mapped_column(
        ForeignKey("threads.thread_id", ondelete="CASCADE"), index=True
    )
    working_group: Mapped[str] = mapped_column(String, index=True, default="")
    from_address: Mapped[str] = mapped_column(String, index=True)
    from_name: Mapped[str] = mapped_column(String, default="")
    date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archive_url: Mapped[str | None] = mapped_column(Text)
    body_cleaned: Mapped[str] = mapped_column(Text, default="")
    body_original: Mapped[str] = mapped_column(Text, default="")
    in_reply_to: Mapped[str | None] = mapped_column(String)
    references: Mapped[list[str]] = mapped_column(JSONType, default=list)
    subject: Mapped[str] = mapped_column(String, default="")

    thread: Mapped[Thread | None] = relationship(back_populates="messages")


class Topic(Base):
    __tablename__ = "topics"

    topic_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    keywords: Mapped[list[str]] = mapped_column(JSONType, default=list)

    threads: Mapped[list[ThreadTopic]] = relationship(back_populates="topic")


class ThreadTopic(Base):
    __tablename__ = "thread_topics"

    thread_id: Mapped[str] = mapped_column(
        ForeignKey("threads.thread_id", ondelete="CASCADE"), primary_key=True
    )
    topic_id: Mapped[int] = mapped_column(
        ForeignKey("topics.topic_id", ondelete="CASCADE"), primary_key=True
    )
    confidence: Mapped[float] = mapped_column(Float, default=0.0)

    thread: Mapped[Thread] = relationship(back_populates="topics")
    topic: Mapped[Topic] = relationship(back_populates="threads")


class Draft(Base):
    __tablename__ = "drafts"

    draft_name: Mapped[str] = mapped_column(String, primary_key=True)
    current_version: Mapped[str | None] = mapped_column(String)
    title: Mapped[str | None] = mapped_column(Text)
    working_group: Mapped[str | None] = mapped_column(String, index=True)
    status: Mapped[str | None] = mapped_column(String)
    rfc_number: Mapped[str | None] = mapped_column(String)
    authors: Mapped[list[str]] = mapped_column(JSONType, default=list)
    first_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_checked: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    datatracker_url: Mapped[str | None] = mapped_column(Text)
    abstract: Mapped[str | None] = mapped_column(Text)
    versions: Mapped[list[dict[str, str]]] = mapped_column(JSONType, default=list)

    threads: Mapped[list[ThreadDraft]] = relationship(back_populates="draft")


class ThreadDraft(Base):
    __tablename__ = "thread_drafts"

    thread_id: Mapped[str] = mapped_column(
        ForeignKey("threads.thread_id", ondelete="CASCADE"), primary_key=True
    )
    draft_name: Mapped[str] = mapped_column(
        ForeignKey("drafts.draft_name", ondelete="CASCADE"), primary_key=True
    )
    versions_referenced: Mapped[list[str] | None] = mapped_column(JSONType)
    first_referenced_in_thread: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    thread: Mapped[Thread] = relationship(back_populates="drafts")
    draft: Mapped[Draft] = relationship(back_populates="threads")


class ProcessingLog(Base):
    __tablename__ = "processing_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    stage: Mapped[str] = mapped_column(String)
    model: Mapped[str | None] = mapped_column(String)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String, default="ok")
    detail: Mapped[str | None] = mapped_column(Text)
    thread_id: Mapped[str | None] = mapped_column(String)


class BatchJob(Base):
    __tablename__ = "batch_jobs"
    __table_args__ = (UniqueConstraint("batch_id", name="uq_batch_jobs_batch_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[str | None] = mapped_column(String)
    stage: Mapped[str] = mapped_column(String)
    status: Mapped[BatchStatus] = mapped_column(
        Enum(BatchStatus, name="batch_status"), default=BatchStatus.pending
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    item_count: Mapped[int] = mapped_column(Integer, default=0)
    meta: Mapped[dict[str, object]] = mapped_column(JSONType, default=dict)
