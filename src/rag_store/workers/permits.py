"""Cluster-wide inference permits.

Per-pod semaphores are not enough. Permits live in PostgreSQL and are taken under
a transaction advisory lock. Bulk ingestion can use only the capacity that remains
after the interactive reservation. Expired permits are removed when a new permit
is requested.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from rag_store.common.errors import Unavailable
from rag_store.config.settings import Settings
from rag_store.database.models import InferencePermit

_LOCKS = {"embedding": 42001, "reranking": 42002}


def acquire_permit(session: Session, settings: Settings, *, kind: str, holder: str, priority: str) -> UUID:
    if kind not in _LOCKS:
        raise Unavailable(f"Unknown inference permit kind '{kind}'.")
    session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _LOCKS[kind]})
    now = datetime.now(timezone.utc)
    session.execute(delete(InferencePermit).where(InferencePermit.expires_at < now))
    active = session.scalar(select(func.count()).select_from(InferencePermit).where(InferencePermit.kind == kind)) or 0
    if kind == "embedding":
        limit = settings.concurrency.embedding_global_limit
        if priority != "interactive":
            limit -= settings.concurrency.embedding_reserved_interactive
    else:
        limit = settings.concurrency.rerank_global_limit
    if active >= limit:
        raise Unavailable(
            "Inference capacity is exhausted.",
            details={"kind": kind, "priority": priority, "limit": limit, "active": int(active)},
        )
    permit_id = uuid4()
    session.add(
        InferencePermit(
            id=permit_id,
            kind=kind,
            holder_id=holder,
            priority=10 if priority == "interactive" else 70,
            expires_at=now + timedelta(seconds=settings.concurrency.permit_ttl_seconds),
        )
    )
    session.flush()
    return permit_id


def release_permit(session: Session, permit_id: UUID) -> None:
    session.execute(delete(InferencePermit).where(InferencePermit.id == permit_id))
