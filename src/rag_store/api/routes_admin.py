"""Administrator operations.

Ordinary administration covers GLOBAL knowledge, accounts, and quotas. It does
not grant access to another user's LOCAL documents.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from rag_store.api.deps import db_session, require_admin, runtime
from rag_store.api.runtime import Runtime
from rag_store.auth.service import audit, create_api_key, create_user
from rag_store.database.models import (
    AuditEvent,
    Collection,
    Document,
    IngestionJob,
    User,
    UserQuota,
    WorkerHeartbeat,
)
from rag_store.database.session import Actor

router = APIRouter(prefix="/api/v1/admin")


class UserBody(BaseModel):
    username: str
    password: str | None = None
    role: str = "user"
    display_name: str = ""
    email: str | None = None


class UserPatch(BaseModel):
    role: str | None = None
    is_active: bool | None = None
    display_name: str | None = None


class QuotaPatch(BaseModel):
    max_bytes: int | None = None
    max_documents: int | None = None
    max_collections: int | None = None
    max_document_bytes: int | None = None
    max_concurrent_jobs: int | None = None
    search_requests_per_minute: int | None = None


class ApiKeyBody(BaseModel):
    name: str = "default"
    user_id: str | None = None


@router.get("/statistics")
def statistics(current: Actor = Depends(require_admin), session: Session = Depends(db_session)) -> dict:
    documents = session.scalar(select(func.count()).select_from(Document).where(Document.deleted_at.is_(None), Document.scope == "global"))
    collections = session.scalar(select(func.count()).select_from(Collection).where(Collection.scope == "global"))
    jobs = dict(session.execute(select(IngestionJob.state, func.count()).group_by(IngestionJob.state)).all())
    users = session.scalar(select(func.count()).select_from(User))
    return {
        "users": int(users or 0),
        "global_documents": int(documents or 0),
        "global_collections": int(collections or 0),
        "visible_jobs": {state: int(count) for state, count in jobs.items()},
        "note": "Job and document counts follow administrator visibility and exclude other users' local knowledge.",
    }


@router.get("/users")
def list_users(current: Actor = Depends(require_admin), session: Session = Depends(db_session)) -> dict:
    rows = session.scalars(select(User).order_by(User.username)).all()
    return {
        "users": [
            {
                "id": str(row.id),
                "username": row.username,
                "display_name": row.display_name,
                "role": row.role,
                "is_active": row.is_active,
                "storage_key": row.storage_key,
            }
            for row in rows
        ]
    }


@router.post("/users", status_code=201)
def add_user(body: UserBody, current: Actor = Depends(require_admin), session: Session = Depends(db_session), app: Runtime = Depends(runtime)) -> dict:
    user = create_user(
        session,
        app.settings,
        username=body.username,
        password=body.password,
        role=body.role,
        display_name=body.display_name,
        email=body.email,
        actor=current,
    )
    return {"id": str(user.id), "username": user.username, "role": user.role, "storage_key": user.storage_key}


@router.patch("/users/{user_id}")
def patch_user(user_id: UUID, body: UserPatch, current: Actor = Depends(require_admin), session: Session = Depends(db_session)) -> dict:
    user = session.get(User, user_id)
    if user is None:
        from rag_store.common.errors import NotFound

        raise NotFound("User not found.")
    if body.role is not None:
        if body.role not in {"admin", "user", "service"}:
            from rag_store.common.errors import ValidationFailed

            raise ValidationFailed("Role must be admin, user, or service.")
        user.role = body.role
    if body.is_active is not None:
        user.is_active = body.is_active
    if body.display_name is not None:
        user.display_name = body.display_name[:256]
    audit(session, current, "user_updated", target_type="user", target_id=str(user.id))
    return {"id": str(user.id), "username": user.username, "role": user.role, "is_active": user.is_active}


@router.patch("/users/{user_id}/quota")
def patch_quota(user_id: UUID, body: QuotaPatch, current: Actor = Depends(require_admin), session: Session = Depends(db_session)) -> dict:
    quota = session.get(UserQuota, user_id)
    if quota is None:
        from rag_store.common.errors import NotFound

        raise NotFound("Quota not found.")
    for field in ("max_bytes", "max_documents", "max_collections", "max_document_bytes", "max_concurrent_jobs", "search_requests_per_minute"):
        value = getattr(body, field)
        if value is not None:
            if value < 0:
                from rag_store.common.errors import ValidationFailed

                raise ValidationFailed("Quota values cannot be negative.")
            setattr(quota, field, value)
    audit(session, current, "quota_updated", target_type="user", target_id=str(user_id))
    return {"user_id": str(user_id), "max_bytes": quota.max_bytes, "max_documents": quota.max_documents, "used_bytes": quota.used_bytes}


@router.post("/api-keys", status_code=201)
def create_key(body: ApiKeyBody, current: Actor = Depends(require_admin), session: Session = Depends(db_session)) -> dict:
    target = session.get(User, UUID(body.user_id)) if body.user_id else None
    if body.user_id and target is None:
        from rag_store.common.errors import NotFound

        raise NotFound("User not found.")
    return create_api_key(session, current, body.name, target_user=target)


@router.get("/audit")
def audit_log(limit: int = 100, current: Actor = Depends(require_admin), session: Session = Depends(db_session)) -> dict:
    rows = session.scalars(select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(min(max(limit, 1), 500))).all()
    return {
        "events": [
            {
                "id": str(row.id),
                "actor_id": str(row.actor_id) if row.actor_id else None,
                "action": row.action,
                "scope": row.scope,
                "target_type": row.target_type,
                "target_id": row.target_id,
                "metadata": row.attributes,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]
    }


@router.get("/system-status")
def system_status(current: Actor = Depends(require_admin), session: Session = Depends(db_session), app: Runtime = Depends(runtime)) -> dict:
    database = True
    try:
        session.execute(text("SELECT 1"))
    except Exception:
        database = False
    heartbeats = session.scalars(select(WorkerHeartbeat)).all()
    leases = session.execute(text("SELECT name, holder_id, expires_at FROM ragstore.distributed_leases")).mappings().all()
    storage = app.layout.storage_status()
    artifacts = app.settings.docling.artifacts_path
    import os

    return {
        "maintenance": app.settings.maintenance.enabled,
        "database": database,
        "storage": storage,
        "workers": [
            {"worker_id": row.worker_id, "component": row.component, "last_seen": row.last_seen.isoformat() if row.last_seen else None}
            for row in heartbeats
        ],
        "leases": [{"name": row["name"], "holder_id": row["holder_id"], "expires_at": row["expires_at"].isoformat() if row["expires_at"] else None} for row in leases],
        "embedding": {
            "provider": app.settings.embedding.provider,
            "configured": bool(app.settings.embedding.base_url and app.settings.embedding.model) or app.settings.embedding.provider == "deterministic-test",
            "model": app.settings.embedding.model,
        },
        "reranking": {
            "enabled": app.settings.reranking.enabled,
            "provider": app.settings.reranking.provider,
            "configured": bool(app.settings.reranking.base_url and app.settings.reranking.model),
        },
        "docling": {
            "enabled": app.settings.docling.enabled,
            "ocr_enabled": app.settings.docling.ocr_enabled,
            "ocr_engine": app.settings.docling.ocr_engine,
            "artifacts_path": artifacts,
            "artifacts_present": os.path.isdir(artifacts) and bool(os.listdir(artifacts)) if os.path.isdir(artifacts) else False,
        },
    }
