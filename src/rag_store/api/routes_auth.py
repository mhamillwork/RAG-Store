"""Login, refresh, and the current account."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from rag_store.api.deps import actor, db_session, runtime
from rag_store.api.runtime import Runtime
from rag_store.auth.service import login, logout, refresh_session
from rag_store.database.session import Actor

router = APIRouter(prefix="/api/v1/auth")


class LoginBody(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=1024)


class RefreshBody(BaseModel):
    refresh_token: str = Field(min_length=10, max_length=512)


@router.post("/login")
def login_route(body: LoginBody, session: Session = Depends(db_session), app: Runtime = Depends(runtime)) -> dict:
    return login(session, app.settings, body.username, body.password)


@router.post("/refresh")
def refresh_route(body: RefreshBody, session: Session = Depends(db_session), app: Runtime = Depends(runtime)) -> dict:
    return refresh_session(session, app.settings, body.refresh_token)


@router.post("/logout")
def logout_route(body: RefreshBody, session: Session = Depends(db_session)) -> dict:
    logout(session, body.refresh_token)
    return {"status": "ok"}


@router.get("/me")
def me(current: Actor = Depends(actor), app: Runtime = Depends(runtime), session: Session = Depends(db_session)) -> dict:
    quota = app.catalog.quota(session, current)
    return {
        "id": str(current.user_id),
        "username": current.username,
        "role": current.role,
        "storage_key": current.storage_key,
        "quota": quota,
    }
