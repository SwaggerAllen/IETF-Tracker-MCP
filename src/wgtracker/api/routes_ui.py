"""JSON API consumed by the React debug SPA (read + re-trigger)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import desc, select

from wgtracker.api.deps import SessionDep, SettingsDep
from wgtracker.api.github import dispatch_pipeline
from wgtracker.db.models import BatchJob, ProcessingLog, Topic
from wgtracker.llm.cost import spend_by_stage, total_spend
from wgtracker.mcp_server import tools

router = APIRouter()


@router.get("/threads")
def list_threads(
    session: SessionDep,
    topic: str | None = None,
    working_group: str | None = None,
    status: str | None = None,
    limit: Annotated[int, Query(le=500)] = 50,
) -> list[dict[str, Any]]:
    return tools.search_threads(
        session, topic=topic, working_group=working_group, status=status, limit=limit
    )


@router.get("/threads/{thread_id}")
def get_thread(session: SessionDep, thread_id: str) -> dict[str, Any]:
    detail = tools.get_thread_detail(session, thread_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Thread not found")
    return detail


@router.get("/recent")
def recent(
    session: SessionDep,
    topic: str | None = None,
    working_group: str | None = None,
    days: int = 30,
) -> list[dict[str, Any]]:
    return tools.recent_activity(session, topic=topic, working_group=working_group, days=days)


@router.get("/topics")
def topics(session: SessionDep) -> list[dict[str, Any]]:
    rows = session.scalars(select(Topic).order_by(Topic.name))
    return [{"name": t.name, "description": t.description, "keywords": t.keywords} for t in rows]


@router.get("/topics/{topic}/overview")
def topic_overview(
    session: SessionDep, topic: str, working_group: str | None = None
) -> dict[str, Any]:
    return tools.topic_overview(session, topic, working_group=working_group)


@router.get("/drafts")
def list_drafts(
    session: SessionDep, topic: str | None = None, working_group: str | None = None
) -> list[dict[str, Any]]:
    return tools.list_drafts(session, topic=topic, working_group=working_group)


@router.get("/drafts/{draft_name}")
def get_draft(session: SessionDep, draft_name: str) -> dict[str, Any]:
    detail = tools.get_draft(session, draft_name)
    if detail is None:
        raise HTTPException(status_code=404, detail="Draft not found")
    return detail


@router.get("/cost")
def cost(session: SessionDep, settings: SettingsDep) -> dict[str, Any]:
    return {
        "total_usd": total_spend(session),
        "ceiling_usd": settings.cost_ceiling_usd,
        "by_stage": spend_by_stage(session),
    }


@router.get("/processing-log")
def processing_log(
    session: SessionDep, limit: Annotated[int, Query(le=500)] = 100
) -> list[dict[str, Any]]:
    rows = session.scalars(select(ProcessingLog).order_by(desc(ProcessingLog.date)).limit(limit))
    return [
        {
            "date": r.date.isoformat() if r.date else None,
            "stage": r.stage,
            "model": r.model,
            "status": r.status,
            "input_tokens": r.input_tokens,
            "output_tokens": r.output_tokens,
            "cost_usd": r.cost_usd,
            "thread_id": r.thread_id,
            "detail": r.detail,
        }
        for r in rows
    ]


@router.get("/batches")
def batches(session: SessionDep) -> list[dict[str, Any]]:
    rows = session.scalars(select(BatchJob).order_by(desc(BatchJob.id)).limit(100))
    return [
        {
            "id": b.id,
            "batch_id": b.batch_id,
            "stage": b.stage,
            "status": b.status.value,
            "item_count": b.item_count,
            "submitted_at": b.submitted_at.isoformat() if b.submitted_at else None,
            "retrieved_at": b.retrieved_at.isoformat() if b.retrieved_at else None,
        }
        for b in rows
    ]


@router.post("/retrigger/{stage}")
def retrigger(settings: SettingsDep, stage: str) -> dict[str, Any]:
    code, message = dispatch_pipeline(settings, stage)
    if code >= 400:
        raise HTTPException(status_code=code, detail=message)
    return {"status": "dispatched", "stage": stage, "detail": message}
