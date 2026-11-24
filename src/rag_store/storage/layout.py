"""Filesystem layout for GLOBAL and LOCAL source documents.

Paths stored in PostgreSQL are relative to the scope root. Callers confine every
user-supplied path before joining it to a root, and symbolic links are rejected.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from rag_store.common.checksum import sha256_bytes
from rag_store.common.errors import PayloadTooLarge, Unavailable, ValidationFailed
from rag_store.common.paths import confine, storage_key_ok
from rag_store.config.settings import Settings

AREAS = ("dropbox", "staging", "processing", "documents", "assets", "failed")
PENDING_MARKER = "PENDING_DB"


class StorageLayout:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.global_root = Path(settings.storage.global_root)
        self.local_root = Path(settings.storage.local_root)

    def scope_root(self, scope: str, storage_key: str = "") -> Path:
        if scope == "global":
            return self.global_root
        if scope != "local":
            raise ValidationFailed("Scope must be global or local.")
        if not storage_key_ok(storage_key):
            raise ValidationFailed("The storage key is not valid.")
        return self.local_root / storage_key

    def ensure_tree(self, scope: str, storage_key: str = "") -> None:
        root = self.scope_root(scope, storage_key)
        try:
            for area in AREAS:
                (root / area).mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise Unavailable(
                "Document storage is not writable.",
                details={"scope": scope, "reason": exc.strerror or "os error"},
            ) from exc

    def area(self, scope: str, storage_key: str, name: str) -> Path:
        if name not in AREAS:
            raise ValidationFailed("Unknown storage area.")
        return self.scope_root(scope, storage_key) / name

    def version_relative(self, document_id, version_id, filename: str) -> str:
        suffix = Path(filename).suffix.lower()
        if len(suffix) > 16 or any(char not in ".abcdefghijklmnopqrstuvwxyz0123456789" for char in suffix):
            suffix = ""
        return f"documents/{document_id}/{version_id}/original{suffix}"

    def absolute(self, scope: str, storage_key: str, relative: str) -> Path:
        return confine(self.scope_root(scope, storage_key), relative)

    def write_original(self, scope: str, storage_key: str, document_id, version_id, filename: str, source, manifest: dict) -> tuple[str, str, int]:
        self.ensure_tree(scope, storage_key)
        relative = self.version_relative(document_id, version_id, filename)
        target = self.absolute(scope, storage_key, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(target.name + ".partial")
        digest = hashlib.sha256()
        size = 0
        limit = self.settings.storage.max_file_bytes
        try:
            with partial.open("wb") as handle:
                while True:
                    block = source.read(1024 * 1024)
                    if not block:
                        break
                    size += len(block)
                    if size > limit:
                        raise PayloadTooLarge(
                            "The file exceeds the configured maximum size.",
                            details={"limit_bytes": limit},
                        )
                    digest.update(block)
                    handle.write(block)
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            partial.unlink(missing_ok=True)
            raise
        os.replace(partial, target)
        checksum = digest.hexdigest()
        manifest = {
            **manifest,
            "relative_path_stored": relative,
            "checksum": checksum,
            "size": size,
        }
        manifest_path = target.parent / "manifest.json"
        encoded = json.dumps(manifest, sort_keys=True).encode("utf-8")
        manifest_path.write_bytes(encoded)
        (target.parent / PENDING_MARKER).write_text("pending\n", encoding="utf-8")
        return relative, checksum, size

    def publish_staged(self, scope: str, storage_key: str, staging_relative: str, document_id, version_id, filename: str, manifest: dict) -> str:
        source = self.absolute(scope, storage_key, staging_relative)
        if not source.is_file() or source.is_symlink():
            raise Unavailable("The staged upload is missing.", details={"degradation": "source_storage_unavailable"})
        relative = self.version_relative(document_id, version_id, filename)
        target = self.absolute(scope, storage_key, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(source, target)
        manifest_path = target.parent / "manifest.json"
        manifest_path.write_text(json.dumps({**manifest, "relative_path_stored": relative}, sort_keys=True), encoding="utf-8")
        (target.parent / PENDING_MARKER).write_text("pending\n", encoding="utf-8")
        try:
            source.parent.rmdir()
        except OSError:
            pass
        return relative

    def clear_pending(self, scope: str, storage_key: str, relative: str) -> None:
        marker = self.absolute(scope, storage_key, relative).parent / PENDING_MARKER
        marker.unlink(missing_ok=True)

    def read_bytes(self, scope: str, storage_key: str, relative: str) -> bytes:
        path = self.absolute(scope, storage_key, relative)
        if not path.is_file() or path.is_symlink():
            raise Unavailable("The source file is not available.", details={"degradation": "source_storage_unavailable"})
        return path.read_bytes()

    def checksum(self, scope: str, storage_key: str, relative: str) -> str:
        return sha256_bytes(self.read_bytes(scope, storage_key, relative))

    def remove_tree(self, scope: str, storage_key: str, relative: str) -> None:
        path = self.absolute(scope, storage_key, relative)
        if path.is_symlink():
            raise ValidationFailed("Symbolic links are not accepted.")
        if not path.exists():
            return
        if path.is_file():
            path.unlink()
            return
        for child in sorted(path.rglob("*"), reverse=True):
            if child.is_symlink():
                raise ValidationFailed("Symbolic links are not accepted.")
            if child.is_file():
                child.unlink()
            else:
                child.rmdir()
        path.rmdir()

    def storage_status(self) -> dict:
        def describe(path: Path) -> dict:
            try:
                path.mkdir(parents=True, exist_ok=True)
                probe = path / ".health"
                probe.write_text("ok\n", encoding="utf-8")
                probe.unlink()
                usage = os.statvfs(path)
                return {
                    "available": True,
                    "path": str(path),
                    "free_bytes": usage.f_bavail * usage.f_frsize,
                    "total_bytes": usage.f_blocks * usage.f_frsize,
                }
            except OSError as exc:
                return {"available": False, "path": str(path), "error": exc.strerror or "os error"}

        return {"global": describe(self.global_root), "local": describe(self.local_root)}
