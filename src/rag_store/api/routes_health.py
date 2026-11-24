"""Health, readiness, and metrics."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import Response
from sqlalchemy import func, select, text

from rag_store.database.models import IngestionJob
from rag_store.database.session import session_scope
from rag_store.monitoring import metrics

router = APIRouter()


@router.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@router.get("/readyz")
def readyz(request: Request) -> dict:
    runtime = request.app.state.runtime
    try:
        with session_scope(runtime.sessions) as session:
            session.execute(text("SELECT 1"))
        metrics.DB_UP.set(1)
    except Exception as exc:
        metrics.DB_UP.set(0)
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=503, content={"status": "not_ready", "database": exc.__class__.__name__})
    problems = []
    if runtime.settings.component == "docling":
        from rag_store.docling.adapter import DoclingAdapter

        try:
            DoclingAdapter(runtime.settings).validate()
            metrics.MODEL_READY.set(1)
        except Exception as exc:
            metrics.MODEL_READY.set(0)
            problems.append(str(exc))
    if problems:
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=503, content={"status": "not_ready", "problems": problems})
    return {"status": "ready", "component": runtime.settings.component, "maintenance": runtime.settings.maintenance.enabled}


@router.get("/metrics")
def prometheus(request: Request) -> Response:
    runtime = request.app.state.runtime
    try:
        with session_scope(runtime.sessions) as session:
            session.execute(text("SELECT 1"))
            metrics.DB_UP.set(1)
            _refresh_jobs(session)
            storage = runtime.layout.storage_status()
            for scope, info in storage.items():
                if info.get("available") and "free_bytes" in info:
                    metrics.STORAGE_FREE_BYTES.labels(scope=scope).set(info["free_bytes"])
    except Exception:
        metrics.DB_UP.set(0)
    body, content_type = metrics.render()
    return Response(content=body, media_type=content_type)


def _refresh_jobs(session) -> None:
    rows = session.execute(select(IngestionJob.state, func.count()).group_by(IngestionJob.state)).all()
    seen = {state: count for state, count in rows}
    for state in (
        "queued",
        "retry_pending",
        "validating",
        "converting",
        "ocr_processing",
        "chunking",
        "embedding",
        "indexing",
        "publishing",
        "completed",
        "failed",
        "cancelled",
        "conversion_completed",
    ):
        metrics.JOBS_PENDING.labels(state=state).set(seen.get(state, 0))
    oldest = session.scalar(
        select(func.min(IngestionJob.created_at)).where(IngestionJob.state.in_(("queued", "retry_pending")))
    )
    if oldest is None:
        metrics.OLDEST_PENDING_SECONDS.set(0)
    else:
        metrics.OLDEST_PENDING_SECONDS.set(max(0, (datetime.now(timezone.utc) - oldest).total_seconds()))
