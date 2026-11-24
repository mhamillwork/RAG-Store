"""Authentication.

Local passwords, signed access tokens, refresh sessions, and scoped API keys.
OIDC is used only when an issuer is configured. User identity always comes from
the authenticated request, never from a tool argument.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy import text
from sqlalchemy.orm import Session

from rag_store.common.errors import Forbidden, Unauthorized, ValidationFailed
from rag_store.config.settings import Settings
from rag_store.database.models import ApiCredential, AuditEvent, Collection, User, UserQuota, UserSession
from rag_store.database.session import Actor, bind_actor

_HASHER = PasswordHasher()
_LOGIN_COLUMNS = ["id", "username", "display_name", "role", "is_active", "storage_key", "password_hash"]


def hash_password(password: str) -> str:
    if len(password) < 12:
        raise ValidationFailed("Passwords must be at least 12 characters.")
    return _HASHER.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    try:
        return _HASHER.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def audit(session: Session, actor: Actor | None, action: str, *, scope: str = "", target_type: str = "", target_id: str = "", attributes: dict | None = None) -> None:
    session.add(
        AuditEvent(
            actor_id=actor.user_id if actor else None,
            action=action,
            scope=scope,
            target_type=target_type,
            target_id=target_id,
            attributes=attributes or {},
        )
    )


def _row_to_actor(row) -> Actor:
    return Actor(user_id=row.id, role=row.role, username=row.username, storage_key=row.storage_key)


def lookup_login(session: Session, username: str):
    result = session.execute(
        text(
            "SELECT id, username, display_name, role, is_active, storage_key, password_hash "
            "FROM ragstore.lookup_login(:username)"
        ),
        {"username": username.strip().lower()},
    ).mappings().first()
    return result


def lookup_user(session: Session, user_id: UUID):
    result = session.execute(
        text(
            "SELECT id, username, display_name, role, is_active, storage_key, password_hash "
            "FROM ragstore.lookup_user(:user_id)"
        ),
        {"user_id": user_id},
    ).mappings().first()
    return result


def issue_tokens(session: Session, settings: Settings, user_row) -> dict:
    if not user_row["is_active"]:
        raise Unauthorized("The account is disabled.")
    now = _utcnow()
    access = jwt.encode(
        {
            "sub": str(user_row["id"]),
            "role": user_row["role"],
            "username": user_row["username"],
            "typ": "access",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=settings.auth.jwt_ttl_seconds)).timestamp()),
        },
        settings.auth.jwt_secret,
        algorithm="HS256",
    )
    refresh = secrets.token_urlsafe(48)
    session.add(
        UserSession(
            user_id=user_row["id"],
            token_hash=hash_secret(refresh),
            expires_at=now + timedelta(seconds=settings.auth.refresh_ttl_seconds),
        )
    )
    return {
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "bearer",
        "expires_in": settings.auth.jwt_ttl_seconds,
    }


def login(session: Session, settings: Settings, username: str, password: str) -> dict:
    row = lookup_login(session, username)
    if row is None or not verify_password(password, row["password_hash"]) or not row["is_active"]:
        audit(session, None, "login_failed", attributes={"username": username.strip().lower()[:128]})
        raise Unauthorized("The username or password is incorrect.")
    actor = Actor(user_id=row["id"], role=row["role"], username=row["username"], storage_key=row["storage_key"])
    bind_actor(session, actor)
    audit(session, actor, "login_succeeded")
    return issue_tokens(session, settings, row)


def refresh_session(session: Session, settings: Settings, refresh_token: str) -> dict:
    stored = session.execute(
        text(
            "SELECT session_id, id, username, display_name, role, is_active, storage_key "
            "FROM ragstore.lookup_refresh(:token_hash)"
        ),
        {"token_hash": hash_secret(refresh_token)},
    ).mappings().first()
    if stored is None or not stored["is_active"]:
        raise Unauthorized("The refresh token is not valid.")
    actor = Actor(user_id=stored["id"], role=stored["role"], username=stored["username"], storage_key=stored["storage_key"])
    bind_actor(session, actor)
    session.execute(
        text("UPDATE ragstore.user_sessions SET revoked_at = now() WHERE id = :session_id"),
        {"session_id": stored["session_id"]},
    )
    return issue_tokens(session, settings, stored)


def logout(session: Session, refresh_token: str) -> None:
    session.execute(
        text("UPDATE ragstore.user_sessions SET revoked_at = now() WHERE token_hash = :token_hash AND revoked_at IS NULL"),
        {"token_hash": hash_secret(refresh_token)},
    )


def authenticate_bearer(session: Session, settings: Settings, header: str | None) -> Actor:
    if not header:
        raise Unauthorized("Authentication is required.")
    scheme, _, value = header.partition(" ")
    if scheme.lower() not in {"bearer", "apikey"} or not value:
        raise Unauthorized("Authentication is required.")
    if value.startswith("rag_"):
        return _authenticate_api_key(session, value.strip())
    try:
        payload = jwt.decode(value.strip(), settings.auth.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise Unauthorized("The access token is not valid.") from exc
    if payload.get("typ") != "access":
        raise Unauthorized("The access token is not valid.")
    user_id = UUID(payload["sub"])
    row = lookup_user(session, user_id)
    if row is None or not row["is_active"]:
        raise Unauthorized("The access token is not valid.")
    actor = _row_to_actor(row)
    bind_actor(session, actor)
    return actor


def _authenticate_api_key(session: Session, token: str) -> Actor:
    row = session.execute(
        text(
            "SELECT credential_id, user_id, username, display_name, role, is_active, storage_key, expires_at, revoked_at "
            "FROM ragstore.lookup_api_key(:key_hash)"
        ),
        {"key_hash": hash_secret(token)},
    ).mappings().first()
    if row is None or not row["is_active"] or row["revoked_at"] is not None:
        raise Unauthorized("The API key is not valid.")
    expires_at = row["expires_at"]
    if expires_at is not None and expires_at < _utcnow():
        raise Unauthorized("The API key is not valid.")
    actor = Actor(user_id=row["user_id"], role=row["role"], username=row["username"], storage_key=row["storage_key"])
    bind_actor(session, actor)
    session.execute(
        text("UPDATE ragstore.api_credentials SET last_used_at = now() WHERE id = :credential_id"),
        {"credential_id": row["credential_id"]},
    )
    return actor


def create_api_key(session: Session, actor: Actor, name: str, *, target_user: User | None = None) -> dict:
    owner = target_user or session.get(User, actor.user_id)
    if owner is None:
        raise Unauthorized("The account is not available.")
    if target_user is not None and not actor.is_admin:
        raise Forbidden("Only an administrator can create a key for another account.")
    secret = "rag_" + secrets.token_urlsafe(32)
    session.add(
        ApiCredential(
            user_id=owner.id,
            name=name[:128] or "default",
            key_prefix=secret[:12],
            key_hash=hash_secret(secret),
        )
    )
    audit(session, actor, "api_key_created", target_type="user", target_id=str(owner.id), attributes={"name": name[:128]})
    return {"api_key": secret, "prefix": secret[:12]}


def storage_key_for(user_id: UUID) -> str:
    return "user-" + user_id.hex[:12]


def create_user(session: Session, settings: Settings, *, username: str, password: str | None, role: str, display_name: str = "", email: str | None = None, actor: Actor | None = None) -> User:
    if role not in {"admin", "user", "service"}:
        raise ValidationFailed("Role must be admin, user, or service.")
    if actor is not None and not actor.is_admin:
        raise Forbidden("Only an administrator can create accounts.")
    normalized = username.strip().lower()
    if not normalized or "/" in normalized or len(normalized) > 128:
        raise ValidationFailed("The username is not valid.")
    user_id = uuid4()
    user = User(
        id=user_id,
        storage_key=storage_key_for(user_id),
        username=normalized,
        display_name=display_name or normalized,
        email=email,
        password_hash=hash_password(password) if password else None,
        role=role,
        is_active=True,
    )
    if role != "service" and not password:
        raise ValidationFailed("A password is required for user and administrator accounts.")
    session.add(user)
    session.flush()
    created = Actor(user_id=user.id, role=user.role, username=user.username, storage_key=user.storage_key)
    previous = session.info.get("actor")
    bind_actor(session, created)
    session.add(
        UserQuota(
            user_id=user.id,
            max_bytes=settings.quota.max_bytes,
            used_bytes=0,
            max_documents=settings.quota.max_documents,
            max_collections=settings.quota.max_collections,
            max_document_bytes=settings.quota.max_document_bytes,
            max_concurrent_uploads=settings.quota.max_concurrent_uploads,
            max_concurrent_jobs=settings.quota.max_concurrent_jobs,
            search_requests_per_minute=settings.quota.search_requests_per_minute,
        )
    )
    if role != "service":
        session.add(
            Collection(
                name="documents",
                scope="local",
                owner_id=user.id,
                description="Default local collection",
                is_default=True,
                attributes={},
            )
        )
    if previous is not None:
        bind_actor(session, previous)
    audit(session, previous or created, "user_created", target_type="user", target_id=str(user.id), attributes={"role": role})
    return user


def ensure_global_collection(session: Session) -> Collection:
    existing = session.execute(
        text("SELECT id FROM ragstore.collections WHERE scope = 'global' AND is_default = true LIMIT 1")
    ).first()
    if existing:
        found = session.get(Collection, existing[0])
        if found is not None:
            return found
    collection = Collection(
        name="general",
        scope="global",
        owner_id=None,
        description="Default global collection",
        is_default=True,
        attributes={},
    )
    session.add(collection)
    session.flush()
    return collection


def bootstrap_admin(session: Session, settings: Settings) -> None:
    if not settings.auth.bootstrap_admin_username or not settings.auth.bootstrap_admin_password:
        return
    session.execute(text("SELECT pg_advisory_xact_lock(42, 99)"))
    count = session.execute(text("SELECT ragstore.user_count()")).scalar()
    if count:
        return
    admin = create_user(
        session,
        settings,
        username=settings.auth.bootstrap_admin_username,
        password=settings.auth.bootstrap_admin_password,
        role="admin",
        display_name="Administrator",
    )
    bind_actor(session, Actor(user_id=admin.id, role=admin.role, username=admin.username, storage_key=admin.storage_key))
    ensure_global_collection(session)
    audit(session, session.info.get("actor"), "bootstrap_admin", target_type="user", target_id=str(admin.id))
