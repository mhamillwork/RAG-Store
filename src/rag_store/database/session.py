"""Database sessions.

Actor identity is applied at the start of every transaction and cleared when a
connection returns to the pool. Search, file, and worker processes are expected
to be configured with different database roles.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.orm import Session as OrmSession

from rag_store.config.settings import Settings


@dataclass(frozen=True)
class Actor:
    user_id: UUID
    role: str
    username: str
    storage_key: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def is_service(self) -> bool:
        return self.role == "service"


def build_engine(settings: Settings) -> Engine:
    engine = create_engine(
        settings.database.url,
        pool_size=settings.database.pool_size,
        max_overflow=settings.database.max_overflow,
        pool_timeout=settings.database.pool_timeout_seconds,
        pool_pre_ping=True,
        future=True,
        connect_args={
            "application_name": f"{settings.instance_name}-{settings.component}",
            "options": f"-csearch_path={settings.database.schema_name},public",
        },
    )

    @event.listens_for(engine, "checkout")
    def _clear_actor(dbapi_connection, _record, _proxy) -> None:
        dbapi_connection.rollback()
        cursor = dbapi_connection.cursor()
        cursor.execute("SELECT set_config('app.user_id', '', false)")
        cursor.execute("SELECT set_config('app.role', '', false)")
        cursor.close()
        dbapi_connection.commit()

    return engine


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)

    @event.listens_for(factory, "after_begin")
    def _apply_actor(session, _transaction, connection) -> None:
        actor: Actor | None = session.info.get("actor")
        user_id = str(actor.user_id) if actor is not None else ""
        role = actor.role if actor is not None else ""
        connection.execute(text("SELECT set_config('app.user_id', :user_id, true)"), {"user_id": user_id})
        connection.execute(text("SELECT set_config('app.role', :role, true)"), {"role": role})

    return factory


def bind_actor(session: OrmSession, actor: Actor | None) -> None:
    """Apply the actor immediately and on every later transaction of this session."""

    session.info["actor"] = actor
    user_id = str(actor.user_id) if actor is not None else ""
    role = actor.role if actor is not None else ""
    session.execute(text("SELECT set_config('app.user_id', :user_id, true)"), {"user_id": user_id})
    session.execute(text("SELECT set_config('app.role', :role, true)"), {"role": role})


@contextmanager
def session_scope(factory: sessionmaker[Session], actor: Actor | None = None) -> Iterator[Session]:
    session = factory()
    session.info["actor"] = actor
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
