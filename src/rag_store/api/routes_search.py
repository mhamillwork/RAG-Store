"""Search endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from rag_store.api.deps import actor, db_session, limit_search, runtime
from rag_store.api.runtime import Runtime
from rag_store.database.session import Actor

router = APIRouter(prefix="/api/v1")


@router.post("/search")
def search(body: dict, current: Actor = Depends(actor), session: Session = Depends(db_session), app: Runtime = Depends(runtime)) -> dict:
    limit_search(session, current, app.settings)
    return app.search.search(session, current, body)
