"""Dropbox discovery.

Periodic reconciliation is authoritative. inotify is not used, because Longhorn
RWX mounts are network filesystems. Only the lease holder enumerates a dropbox.
"""

from __future__ import annotations

import json
import os
import socket
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from rag_store.common.logging import get_logger
from rag_store.common.paths import storage_key_ok
from rag_store.config.settings import Settings
from rag_store.database.models import Collection, DistributedLease, DropboxObservation, User
from rag_store.database.session import Actor, bind_actor, session_scope
from rag_store.ingestion.catalog import Catalog
from rag_store.ingestion.jobs import recover_expired_leases, utcnow
from rag_store.monitoring import metrics
from rag_store.parsers.router import route_for
from rag_store.storage.layout import PENDING_MARKER, StorageLayout

log = get_logger("scanner")


class Scanner:
    def __init__(self, settings: Settings, session_factory):
        self.settings = settings
        self.session_factory = session_factory
        self.catalog = Catalog(settings)
        self.layout = StorageLayout(settings)
        self.holder = settings.worker_id or f"scanner-{socket.gethostname()}-{os.getpid()}"
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def serve(self) -> None:
        while not self._stop.is_set():
            if self.settings.maintenance.enabled:
                metrics.SCANNER_LEADER.set(0)
                self._stop.wait(self.settings.scanner.interval_seconds)
                continue
            try:
                self.run_once()
            except Exception as exc:
                log.error("scanner_failed", error_type=exc.__class__.__name__)
            self._stop.wait(self.settings.scanner.interval_seconds)

    def run_once(self) -> bool:
        if self.settings.maintenance.enabled:
            return False
        with session_scope(self.session_factory) as session:
            recover_expired_leases(session)
            token = _acquire_lease(session, self.settings.scanner.lease_name, self.holder, self.settings.scanner.lease_seconds)
            if token is None:
                metrics.SCANNER_LEADER.set(0)
                return False
            metrics.SCANNER_LEADER.set(1)
            pending = self._reconcile_pending(session)
            ingested = []
            ingested.extend(self._scan_root(session, "global", "", None))
            users = session.scalars(select(User).where(User.role != "service", User.is_active.is_(True))).all()
            for user in users:
                ingested.extend(self._scan_root(session, "local", user.storage_key, user))
        for path in ingested:
            path.unlink(missing_ok=True)
        for marker in pending:
            marker.unlink(missing_ok=True)
        return True

    def _scan_root(self, session: Session, scope: str, storage_key: str, user: User | None) -> list[Path]:
        try:
            dropbox = self.layout.area(scope, storage_key, "dropbox")
        except Exception:
            return []
        if not dropbox.exists():
            return []
        actor = _actor_for(session, scope, user)
        if actor is None:
            return []
        bind_actor(session, actor)
        ingested: list[Path] = []
        for path in _files(dropbox, self.settings.excluded_directories()):
            relative = path.relative_to(dropbox).as_posix()
            if path.is_symlink():
                self._observe_error(session, scope, storage_key, relative, path, "symbolic links are not ingested")
                continue
            try:
                route_for(path)
            except Exception as exc:
                self._observe_error(session, scope, storage_key, relative, path, str(exc))
                continue
            stat = path.stat()
            if not self._stable(session, scope, storage_key, relative, stat.st_size, stat.st_mtime_ns):
                continue
            collection = _collection_for(session, scope, actor, relative)
            inside = relative.split("/", 1)[1] if relative.startswith(collection.name + "/") else relative
            parent = Path(inside).parent.as_posix()
            parent = "" if parent == "." else parent
            try:
                with path.open("rb") as handle:
                    self.catalog.upload(
                        session,
                        actor,
                        scope=scope,
                        collection_name=collection.name,
                        relative_path=parent,
                        filename=Path(inside).name,
                        source=handle,
                        priority="bulk",
                    )
                ingested.append(path)
                log.info("dropbox_ingested", scope=scope, relative=relative)
            except Exception as exc:
                self._observe_error(session, scope, storage_key, relative, path, exc.__class__.__name__)
        return ingested

    def _stable(self, session, scope, storage_key, relative, size, mtime_ns) -> bool:
        row = session.scalars(
            select(DropboxObservation).where(
                DropboxObservation.scope == scope,
                DropboxObservation.storage_key == storage_key,
                DropboxObservation.relative_path == relative,
            )
        ).first()
        now = utcnow()
        if row is None or row.size_bytes != size or row.mtime_ns != mtime_ns:
            if row is None:
                session.add(
                    DropboxObservation(
                        scope=scope,
                        storage_key=storage_key,
                        relative_path=relative,
                        size_bytes=size,
                        mtime_ns=mtime_ns,
                        stable=False,
                    )
                )
            else:
                row.size_bytes = size
                row.mtime_ns = mtime_ns
                row.first_seen = now
                row.last_seen = now
                row.stable = False
            return False
        row.last_seen = now
        if now - row.first_seen >= timedelta(seconds=self.settings.storage.stability_seconds):
            row.stable = True
            return True
        return False

    def _observe_error(self, session, scope, storage_key, relative, path: Path, message: str) -> None:
        stat = path.stat() if path.exists() and not path.is_symlink() else None
        row = session.scalars(
            select(DropboxObservation).where(
                DropboxObservation.scope == scope,
                DropboxObservation.storage_key == storage_key,
                DropboxObservation.relative_path == relative,
            )
        ).first()
        if row is None:
            session.add(
                DropboxObservation(
                    scope=scope,
                    storage_key=storage_key,
                    relative_path=relative,
                    size_bytes=stat.st_size if stat else 0,
                    mtime_ns=stat.st_mtime_ns if stat else 0,
                    stable=False,
                    last_error=message[:1000],
                )
            )
        else:
            row.last_error = message[:1000]
            row.last_seen = utcnow()

    def _reconcile_pending(self, session: Session) -> list[Path]:
        clear: list[Path] = []
        roots = [self.layout.global_root]
        if self.layout.local_root.exists():
            roots.extend(path for path in self.layout.local_root.iterdir() if path.is_dir() and storage_key_ok(path.name))
        for root in roots:
            if not root.exists():
                continue
            for marker in root.rglob(PENDING_MARKER):
                if marker.is_symlink():
                    continue
                located = self._marker_scope(marker)
                manifest_path = marker.parent / "manifest.json"
                if located is None or not manifest_path.is_file() or manifest_path.is_symlink():
                    continue
                scope, storage_key = located
                try:
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    ready = self.catalog.recover_published(
                        session, scope=scope, storage_key=storage_key, manifest=manifest
                    )
                except Exception as exc:
                    log.error("pending_recovery_kept", error_type=exc.__class__.__name__)
                    continue
                if ready:
                    clear.append(marker)
        return clear

    def _marker_scope(self, marker: Path) -> tuple[str, str] | None:
        try:
            marker.relative_to(self.layout.global_root)
            return "global", ""
        except ValueError:
            pass
        try:
            relative = marker.relative_to(self.layout.local_root)
        except ValueError:
            return None
        if not relative.parts or not storage_key_ok(relative.parts[0]):
            return None
        return "local", relative.parts[0]


def _acquire_lease(session: Session, name: str, holder: str, ttl: int) -> int | None:
    session.execute(text("SELECT pg_advisory_xact_lock(42, 7)"))
    row = session.get(DistributedLease, name)
    expires = datetime.now(timezone.utc) + timedelta(seconds=ttl)
    if row is None:
        session.add(DistributedLease(name=name, holder_id=holder, fencing_token=1, expires_at=expires, details={}))
        session.flush()
        return 1
    if row.holder_id != holder and row.expires_at > datetime.now(timezone.utc):
        return None
    row.holder_id = holder
    row.fencing_token += 1
    row.expires_at = expires
    session.flush()
    return row.fencing_token


def _actor_for(session: Session, scope: str, user: User | None) -> Actor | None:
    if scope == "local":
        if user is None:
            return None
        return Actor(user_id=user.id, role=user.role, username=user.username, storage_key=user.storage_key)
    admin = session.scalars(select(User).where(User.role == "admin", User.is_active.is_(True)).order_by(User.created_at.asc())).first()
    if admin is None:
        return None
    return Actor(user_id=admin.id, role=admin.role, username=admin.username, storage_key=admin.storage_key)


def _collection_for(session: Session, scope: str, actor: Actor, relative: str) -> Collection:
    head = relative.split("/", 1)[0] if "/" in relative else ""
    if head:
        stmt = select(Collection).where(Collection.scope == scope, Collection.name == head)
        if scope == "local":
            stmt = stmt.where(Collection.owner_id == actor.user_id)
        match = session.scalars(stmt).first()
        if match is not None:
            return match
    stmt = select(Collection).where(Collection.scope == scope, Collection.is_default.is_(True))
    if scope == "local":
        stmt = stmt.where(Collection.owner_id == actor.user_id)
    default = session.scalars(stmt).first()
    if default is None:
        raise RuntimeError("No default collection is available for this dropbox.")
    return default


def _files(root: Path, excluded: set[str]):
    for path in sorted(root.rglob("*")):
        if not path.is_file() and not path.is_symlink():
            continue
        if any(part in excluded or part.startswith(".") for part in path.relative_to(root).parts[:-1]):
            continue
        if path.name.startswith(".") or path.name.endswith(".partial"):
            continue
        yield path
