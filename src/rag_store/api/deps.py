"""Request dependencies."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from rag_store.api.runtime import Runtime
from rag_store.auth.service import authenticate_bearer
from rag_store.common.errors import Forbidden, RateLimited
from rag_store.database.models import UserQuota
from rag_store.database.session import Actor


def runtime(request: Request) -> Runtime:
    return request.app.state.runtime


def db_session(request: Request) -> Iterator[Session]:
    factory = request.app.state.runtime.sessions
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def actor(request: Request, session: Session = Depends(db_session)) -> Actor:
    header = request.headers.get("authorization")
    return authenticate_bearer(session, request.app.state.runtime.settings, header)


def require_admin(current: Actor = Depends(actor)) -> Actor:
    if not current.is_admin:
        raise Forbidden("Administrator access is required.")
    return current


def limit_search(session: Session, current: Actor, settings) -> None:
    quota = session.get(UserQuota, current.user_id)
    limit = quota.search_requests_per_minute if quota is not None else settings.quota.search_requests_per_minute
    count = session.execute(
        text(
            """
            INSERT INTO ragstore.rate_buckets (user_id, action, window_start, count)
            VALUES (:user_id, 'search', date_trunc('minute', now()), 1)
            ON CONFLICT (user_id, action, window_start)
            DO UPDATE SET count = ragstore.rate_buckets.count + 1
            RETURNING count
            """
        ),
        {"user_id": current.user_id},
    ).scalar()
    if count is not None and int(count) > limit:
        raise RateLimited("The search rate limit has been reached.", details={"limit_per_minute": limit})
