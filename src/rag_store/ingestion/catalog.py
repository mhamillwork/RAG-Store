"""Document and collection operations shared by the API, CLI, and scanner."""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from rag_store.auth.service import audit
from rag_store.common.checksum import sha256_file
from rag_store.common.errors import (
    Conflict,
    Forbidden,
    NotFound,
    PayloadTooLarge,
    QuotaExceeded,
    ValidationFailed,
)
from rag_store.common.paths import (
    join_relative,
    name_of,
    normalize_relative_path,
    parent_path,
    validate_filename,
)
from rag_store.config.settings import Settings
from rag_store.database.models import (
    Collection,
    DoclingDocument,
    DoclingDocumentSegment,
    Document,
    DocumentAsset,
    DocumentChunk,
    DocumentTable,
    DocumentVersion,
    Folder,
    IngestionJob,
    UploadSession,
    UserQuota,
)
from rag_store.database.session import Actor
from rag_store.ingestion.jobs import PRIORITY, cancel_job, enqueue, retry_job, utcnow
from rag_store.parsers.router import route_for
from rag_store.storage.layout import StorageLayout


class Catalog:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.layout = StorageLayout(settings)

    def list_collections(self, session: Session, actor: Actor, scope: str | None = None) -> list[Collection]:
        stmt = select(Collection).order_by(Collection.scope, Collection.name)
        if scope:
            _check_scope(scope)
            if scope == "local" and actor.is_service:
                raise Forbidden("Service accounts cannot use local knowledge.")
            stmt = stmt.where(Collection.scope == scope)
        return list(session.scalars(stmt))

    def create_collection(self, session: Session, actor: Actor, *, scope: str, name: str, description: str = "") -> Collection:
        _require_write(actor, scope)
        clean = _collection_name(name)
        self._quota_collections(session, actor, scope)
        row = Collection(
            name=clean,
            scope=scope,
            owner_id=None if scope == "global" else actor.user_id,
            description=description[:2000],
            attributes={},
            is_default=False,
        )
        session.add(row)
        session.flush()
        audit(session, actor, "collection_created", scope=scope, target_type="collection", target_id=str(row.id))
        return row

    def delete_collection(self, session: Session, actor: Actor, collection_id: UUID) -> None:
        collection = self._collection(session, collection_id)
        _require_write(actor, collection.scope)
        if collection.is_default:
            raise Conflict("The default collection cannot be deleted.")
        remaining = session.scalar(
            select(func.count()).select_from(Document).where(Document.collection_id == collection.id, Document.deleted_at.is_(None))
        )
        if remaining:
            raise Conflict("The collection still contains documents.")
        session.delete(collection)
        audit(session, actor, "collection_deleted", scope=collection.scope, target_type="collection", target_id=str(collection.id))

    def list_documents(self, session: Session, *, scope: str | None = None, collection_id: UUID | None = None, filename: str | None = None, limit: int = 50, offset: int = 0) -> dict:
        stmt = select(Document).where(Document.deleted_at.is_(None))
        if scope:
            _check_scope(scope)
            stmt = stmt.where(Document.scope == scope)
        if collection_id is not None:
            stmt = stmt.where(Document.collection_id == collection_id)
        if filename:
            stmt = stmt.where(Document.filename.ilike(f"%{filename[:128]}%"))
        total = session.scalar(select(func.count()).select_from(stmt.subquery()))
        rows = session.scalars(
            stmt.order_by(Document.updated_at.desc()).offset(max(offset, 0)).limit(min(max(limit, 1), 200))
        ).all()
        return {"total": int(total or 0), "documents": [_document_summary(session, row) for row in rows]}

    def list_directory(self, session: Session, actor: Actor, collection_id: UUID, path: str = "") -> dict:
        collection = self._collection(session, collection_id)
        relative = normalize_relative_path(path) if path else ""
        folders = session.scalars(
            select(Folder)
            .where(Folder.collection_id == collection.id, Folder.parent_path == relative, Folder.deleted_at.is_(None))
            .order_by(Folder.name)
        ).all()
        documents = session.scalars(
            select(Document)
            .where(Document.collection_id == collection.id, Document.parent_path == relative, Document.deleted_at.is_(None))
            .order_by(Document.filename)
        ).all()
        return {
            "collection": _collection_dict(collection),
            "path": relative,
            "folders": [_folder_dict(folder) for folder in folders],
            "documents": [_document_summary(session, document) for document in documents],
        }

    def create_folder(self, session: Session, actor: Actor, collection_id: UUID, path: str) -> Folder:
        collection = self._collection(session, collection_id)
        _require_write(actor, collection.scope)
        relative = normalize_relative_path(path)
        return self.ensure_folder(session, collection, relative)

    def upload(self, session: Session, actor: Actor, *, scope: str, collection_name: str, relative_path: str, filename: str, source, idempotency_key: str | None = None, priority: str = "ordinary", ocr_mode: str | None = None) -> dict:
        if self.settings.maintenance.enabled:
            from rag_store.common.errors import Unavailable

            raise Unavailable("Ingestion is paused for maintenance.")
        _require_write(actor, scope)
        collection = self._by_name(session, actor, scope, collection_name)
        filename = validate_filename(filename)
        relative = join_relative(relative_path, filename) if relative_path else filename
        route = route_for(Path(filename))
        if ocr_mode and ocr_mode not in {"auto", "force", "native"}:
            raise ValidationFailed("OCR mode must be auto, force, or native.")
        if scope == "local":
            self._quota_jobs(session, actor)
        upload_id = uuid4()
        storage_key = "" if scope == "global" else actor.storage_key
        staged, checksum, size = self._stage(scope, storage_key, upload_id, source)
        if scope == "local" and size > self._quota(session, actor).max_document_bytes:
            self._discard_staged(scope, actor, staged)
            raise PayloadTooLarge("The file exceeds the account document size limit.")
        if scope == "local":
            self._quota_bytes(session, actor, size)
        existing = session.scalars(
            select(Document).where(
                Document.collection_id == collection.id,
                Document.relative_path == relative,
                Document.deleted_at.is_(None),
            )
        ).first()
        if existing is not None and existing.active_version_id is not None:
            current = session.get(DocumentVersion, existing.active_version_id)
            if current is not None and current.source_checksum == checksum:
                self._discard_staged(scope, actor, staged)
                return {"document": _document_summary(session, existing), "deduplicated": True, "job_id": None}
        document_id = existing.id if existing is not None else uuid4()
        version_id = uuid4()
        key = idempotency_key or f"upload:{actor.user_id}:{collection.id}:{relative}:{checksum}"
        prior = session.scalars(select(IngestionJob).where(IngestionJob.idempotency_key == f"convert:{version_id}")).first()
        if prior is not None:
            self._discard_staged(scope, actor, staged)
            document = session.get(Document, prior.document_id)
            return {"document": _document_summary(session, document), "deduplicated": True, "job_id": str(prior.id)}
        stored = self.layout.publish_staged(
            scope,
            storage_key,
            staged,
            document_id,
            version_id,
            filename,
            {
                "document_id": str(document_id),
                "version_id": str(version_id),
                "scope": scope,
                "owner_id": None if scope == "global" else str(actor.user_id),
                "storage_key": storage_key,
                "collection_id": str(collection.id),
                "relative_path": relative,
                "filename": filename,
                "checksum": checksum,
                "size": size,
                "idempotency_key": key,
                "route": route,
                "ocr_mode": ocr_mode or self.settings.docling.ocr_mode,
                "priority": priority,
            },
        )
        if existing is None:
            parent = parent_path(relative)
            folder = self.ensure_folder(session, collection, parent) if parent else None
            document = Document(
                id=document_id,
                collection_id=collection.id,
                folder_id=folder.id if folder else None,
                scope=scope,
                owner_id=None if scope == "global" else actor.user_id,
                filename=filename,
                relative_path=relative,
                parent_path=parent,
                file_type=Path(filename).suffix.lower().lstrip(".")[:32],
                lifecycle_state="processing",
                attributes={},
                tags=[],
            )
            session.add(document)
            session.flush()
        else:
            document = existing
            document.lifecycle_state = "processing"
            document.updated_at = utcnow()
        version_number = (session.scalar(select(func.max(DocumentVersion.version_number)).where(DocumentVersion.document_id == document.id)) or 0) + 1
        version = DocumentVersion(
            id=version_id,
            document_id=document.id,
            version_number=version_number,
            source_path=stored,
            source_checksum=checksum,
            source_size=size,
            parser_name=route,
            processing_state="queued",
            searchable=False,
        )
        session.add(version)
        session.flush()
        job = enqueue(
            session,
            document_id=document.id,
            document_version_id=version.id,
            scope=scope,
            owner_id=document.owner_id,
            job_type="convert",
            state="queued",
            priority=PRIORITY.get(priority, PRIORITY["ordinary"]),
            idempotency_key=f"convert:{version.id}",
            payload={
                "route": route,
                "ocr_mode": ocr_mode or self.settings.docling.ocr_mode,
                "priority": priority,
                "storage_key": storage_key,
            },
            progress={"stage": "queued"},
            max_attempts=self.settings.jobs.max_attempts,
        )
        if scope == "local":
            quota = self._quota(session, actor)
            quota.used_bytes += size
        audit(session, actor, "document_uploaded", scope=scope, target_type="document", target_id=str(document.id))
        self._pending_clear = (scope, storage_key, stored)
        return {"document": _document_summary(session, document), "deduplicated": False, "job_id": str(job.id), "pending": self._pending_clear}

    def clear_pending_after_commit(self, pending) -> None:
        if not pending:
            return
        scope, storage_key, relative = pending
        self.layout.clear_pending(scope, storage_key, relative)

    def recover_published(self, session: Session, *, scope: str, storage_key: str, manifest: dict) -> bool:
        """Recreate database rows for a file published before its transaction committed.

        The pending marker is removed by the caller only after that caller's transaction commits.
        A checksum mismatch or an identity conflict leaves the marker in place.
        """
        required = (
            "document_id",
            "version_id",
            "collection_id",
            "relative_path",
            "filename",
            "checksum",
            "size",
            "relative_path_stored",
        )
        if any(key not in manifest for key in required):
            raise ValidationFailed("Published manifest is incomplete.")
        if manifest.get("scope") != scope or str(manifest.get("storage_key") or "") != storage_key:
            raise ValidationFailed("Published manifest does not match its directory.")
        document_id = UUID(str(manifest["document_id"]))
        version_id = UUID(str(manifest["version_id"]))
        collection_id = UUID(str(manifest["collection_id"]))
        relative = normalize_relative_path(str(manifest["relative_path"]))
        filename = validate_filename(str(manifest["filename"]))
        stored = str(manifest["relative_path_stored"])
        if stored != self.layout.version_relative(document_id, version_id, filename):
            raise ValidationFailed("Stored path does not match the document version.")
        path = self.layout.absolute(scope, storage_key, stored)
        if not path.is_file() or path.is_symlink():
            raise ValidationFailed("Published original is missing.")
        checksum = str(manifest["checksum"])
        size = int(manifest["size"])
        if path.stat().st_size != size or sha256_file(path) != checksum:
            raise ValidationFailed("Published original does not match the manifest checksum.")

        existing_version = session.get(DocumentVersion, version_id)
        if existing_version is not None:
            return True

        collection = session.get(Collection, collection_id)
        if collection is None or collection.scope != scope:
            raise ValidationFailed("Published collection is missing.")
        if scope == "local" and str(collection.owner_id) != str(manifest.get("owner_id")):
            raise ValidationFailed("Published owner does not match the collection.")
        owner_id = None if scope == "global" else collection.owner_id
        document = session.get(Document, document_id)
        if document is None:
            occupied = session.scalars(
                select(Document).where(
                    Document.collection_id == collection.id,
                    Document.relative_path == relative,
                    Document.deleted_at.is_(None),
                )
            ).first()
            if occupied is not None:
                raise ValidationFailed("Another document already uses this path.")
            parent = parent_path(relative)
            folder = self.ensure_folder(session, collection, parent) if parent else None
            document = Document(
                id=document_id,
                collection_id=collection.id,
                folder_id=folder.id if folder else None,
                scope=scope,
                owner_id=owner_id,
                filename=filename,
                relative_path=relative,
                parent_path=parent,
                file_type=Path(filename).suffix.lower().lstrip(".")[:32],
                lifecycle_state="processing",
                attributes={},
                tags=[],
            )
            session.add(document)
            session.flush()
        elif document.collection_id != collection.id or document.relative_path != relative or document.scope != scope:
            raise ValidationFailed("Published document identity does not match the stored row.")
        else:
            document.lifecycle_state = "processing"
            document.updated_at = utcnow()

        version_number = (
            session.scalar(select(func.max(DocumentVersion.version_number)).where(DocumentVersion.document_id == document.id))
            or 0
        ) + 1
        route = str(manifest.get("route") or "")
        if not route:
            route = route_for(Path(filename))
        ocr_mode = manifest.get("ocr_mode") or self.settings.docling.ocr_mode
        if ocr_mode not in {"auto", "force", "native"}:
            ocr_mode = self.settings.docling.ocr_mode
        priority = manifest.get("priority") if manifest.get("priority") in PRIORITY else "ordinary"
        session.add(
            DocumentVersion(
                id=version_id,
                document_id=document.id,
                version_number=version_number,
                source_path=stored,
                source_checksum=checksum,
                source_size=size,
                parser_name=route,
                processing_state="queued",
                searchable=False,
            )
        )
        session.flush()
        enqueue(
            session,
            document_id=document.id,
            document_version_id=version_id,
            scope=scope,
            owner_id=owner_id,
            job_type="convert",
            state="queued",
            priority=PRIORITY[priority],
            idempotency_key=f"convert:{version_id}",
            payload={"route": route, "ocr_mode": ocr_mode, "priority": priority, "storage_key": storage_key, "recovered": True},
            progress={"stage": "queued"},
            max_attempts=self.settings.jobs.max_attempts,
        )
        if owner_id is not None:
            quota = session.get(UserQuota, owner_id)
            if quota is not None:
                quota.used_bytes += size
        audit(session, None, "document_recovered", scope=scope, target_type="document", target_id=str(document.id))
        return True

    def get_document(self, session: Session, document_id: UUID) -> dict:
        document = self._document(session, document_id)
        version = session.get(DocumentVersion, document.active_version_id) if document.active_version_id else None
        structured = None
        if version is not None:
            structured = session.scalars(select(DoclingDocument).where(DoclingDocument.document_version_id == version.id)).first()
        chunk_count = session.scalar(
            select(func.count()).select_from(DocumentChunk).where(DocumentChunk.document_version_id == document.active_version_id)
        ) if document.active_version_id else 0
        return {
            **_document_summary(session, document),
            "version": _version_dict(version),
            "conversion": _conversion_dict(structured) if structured else None,
            "chunk_count": int(chunk_count or 0),
        }

    def document_markdown(self, session: Session, document_id: UUID) -> str:
        structured = self._structured(session, document_id)
        if structured.markdown is None:
            raise NotFound("Extracted Markdown is not available for this document.")
        return structured.markdown

    def document_text(self, session: Session, document_id: UUID) -> str:
        structured = self._structured(session, document_id)
        if structured.plain_text is None:
            raise NotFound("Extracted text is not available for this document.")
        return structured.plain_text

    def document_docling(self, session: Session, document_id: UUID, *, include_content: bool, segment: int | None) -> dict:
        structured = self._structured(session, document_id)
        body = _conversion_dict(structured)
        if not include_content:
            return body
        if structured.content_storage == "segmented":
            segments = session.scalars(
                select(DoclingDocumentSegment)
                .where(DoclingDocumentSegment.docling_document_id == structured.id)
                .order_by(DoclingDocumentSegment.segment_index)
            ).all()
            if segment is None:
                body["segment_count"] = len(segments)
                body["note"] = "Request a segment index to retrieve structured content."
                return body
            chosen = next((item for item in segments if item.segment_index == segment), None)
            if chosen is None:
                raise NotFound("Structured segment not found.")
            body["segment"] = {"index": chosen.segment_index, "content": chosen.content}
            return body
        if structured.content_storage == "longhorn_fallback":
            body["note"] = "The structured document is stored as a fallback artifact. Download it through the asset endpoint."
            return body
        body["content"] = structured.content
        return body

    def document_tables(self, session: Session, document_id: UUID, limit: int = 50, offset: int = 0) -> dict:
        document = self._document(session, document_id)
        if document.active_version_id is None:
            return {"tables": [], "total": 0}
        total = session.scalar(
            select(func.count()).select_from(DocumentTable).where(DocumentTable.document_version_id == document.active_version_id)
        )
        rows = session.scalars(
            select(DocumentTable)
            .where(DocumentTable.document_version_id == document.active_version_id)
            .order_by(DocumentTable.table_index)
            .offset(max(offset, 0))
            .limit(min(max(limit, 1), 100))
        ).all()
        return {
            "total": int(total or 0),
            "tables": [
                {
                    "id": str(row.id),
                    "table_index": row.table_index,
                    "page_number": row.page_number,
                    "caption": row.caption,
                    "section": row.section_path,
                    "content": row.content,
                }
                for row in rows
            ],
        }

    def document_chunks(self, session: Session, document_id: UUID, limit: int = 50, offset: int = 0) -> dict:
        document = self._document(session, document_id)
        if document.active_version_id is None:
            return {"chunks": [], "total": 0}
        total = session.scalar(
            select(func.count()).select_from(DocumentChunk).where(DocumentChunk.document_version_id == document.active_version_id)
        )
        rows = session.scalars(
            select(DocumentChunk)
            .where(DocumentChunk.document_version_id == document.active_version_id)
            .order_by(DocumentChunk.sequence)
            .offset(max(offset, 0))
            .limit(min(max(limit, 1), 200))
        ).all()
        return {
            "total": int(total or 0),
            "chunks": [
                {
                    "id": str(row.id),
                    "sequence": row.sequence,
                    "content": row.content,
                    "page_number": row.page_number,
                    "section": row.section_path,
                    "line_start": row.line_start,
                    "line_end": row.line_end,
                    "table_id": str(row.table_id) if row.table_id else None,
                }
                for row in rows
            ],
        }

    def original_file(self, session: Session, document_id: UUID) -> tuple[str, str]:
        document = self._document(session, document_id)
        version = self._active_version(session, document)
        storage_key = "" if document.scope == "global" else self._owner_storage_key(session, document.owner_id)
        path = self.layout.absolute(document.scope, storage_key, version.source_path)
        if not path.is_file():
            from rag_store.common.errors import Unavailable

            raise Unavailable(
                "The original file is temporarily unavailable. Indexed text remains searchable when the database is up.",
                details={"degradation": "source_storage_unavailable"},
            )
        return str(path), document.filename

    def update_document(self, session: Session, actor: Actor, document_id: UUID, changes: dict) -> dict:
        document = self._document(session, document_id)
        _require_write(actor, document.scope)
        if "filename" in changes and changes["filename"]:
            filename = validate_filename(changes["filename"])
            document.filename = filename
            document.relative_path = join_relative(document.parent_path, filename)
            document.file_type = Path(filename).suffix.lower().lstrip(".")[:32]
        if "relative_path" in changes and changes["relative_path"]:
            relative = normalize_relative_path(changes["relative_path"])
            self._ensure_unique_path(session, document.collection_id, relative, ignore=document.id)
            parent = parent_path(relative)
            folder = self.ensure_folder(session, self._collection(session, document.collection_id), parent) if parent else None
            document.relative_path = relative
            document.parent_path = parent
            document.filename = name_of(relative)
            document.folder_id = folder.id if folder else None
        if "collection_id" in changes and changes["collection_id"]:
            target = self._collection(session, UUID(str(changes["collection_id"])))
            if target.scope != document.scope:
                raise Forbidden("Documents cannot move between global and local knowledge.")
            _require_write(actor, target.scope)
            self._ensure_unique_path(session, target.id, document.relative_path, ignore=document.id)
            document.collection_id = target.id
            session.flush()
            session.execute(
                text("UPDATE ragstore.document_chunks SET collection_id = :collection_id WHERE document_id = :document_id"),
                {"collection_id": target.id, "document_id": document.id},
            )
        if "tags" in changes and changes["tags"] is not None:
            document.tags = [str(tag)[:64] for tag in changes["tags"][:32]]
        if "metadata" in changes and changes["metadata"] is not None:
            if not isinstance(changes["metadata"], dict):
                raise ValidationFailed("Metadata must be an object.")
            document.attributes = changes["metadata"]
        document.updated_at = utcnow()
        audit(session, actor, "document_updated", scope=document.scope, target_type="document", target_id=str(document.id))
        return _document_summary(session, document)

    def delete_document(self, session: Session, actor: Actor, document_id: UUID, *, physical: bool = False) -> None:
        document = self._document(session, document_id)
        _require_write(actor, document.scope)
        document.lifecycle_state = "deleted"
        document.deleted_at = utcnow()
        document.updated_at = utcnow()
        session.execute(
            text("UPDATE ragstore.document_versions SET searchable = false WHERE document_id = :document_id"),
            {"document_id": document.id},
        )
        session.execute(text("DELETE FROM ragstore.document_chunks WHERE document_id = :document_id"), {"document_id": document.id})
        versions = session.scalars(select(DocumentVersion).where(DocumentVersion.document_id == document.id)).all()
        released = sum(version.source_size for version in versions)
        if document.owner_id is not None:
            quota = session.get(UserQuota, document.owner_id)
            if quota is not None:
                quota.used_bytes = max(0, quota.used_bytes - released)
        if physical:
            storage_key = "" if document.scope == "global" else self._owner_storage_key(session, document.owner_id)
            for version in versions:
                parent = str(Path(version.source_path).parent)
                self.layout.remove_tree(document.scope, storage_key, parent)
            session.execute(text("DELETE FROM ragstore.documents WHERE id = :document_id"), {"document_id": document.id})
        audit(session, actor, "document_deleted", scope=document.scope, target_type="document", target_id=str(document.id), attributes={"physical": physical})

    def reindex(self, session: Session, actor: Actor, document_id: UUID) -> dict:
        if self.settings.maintenance.enabled:
            from rag_store.common.errors import Unavailable

            raise Unavailable("Ingestion is paused for maintenance.")
        document = self._document(session, document_id)
        _require_write(actor, document.scope)
        version = self._active_version(session, document)
        structured = session.scalars(select(DoclingDocument).where(DoclingDocument.document_version_id == version.id)).first()
        if structured is None or structured.status == "failed":
            raise Conflict("There is no reusable structured document to reindex. Reprocess the original instead.")
        new_version = self._clone_version(session, document, version)
        self._copy_structure(session, structured, new_version.id)
        job = enqueue(
            session,
            document_id=document.id,
            document_version_id=new_version.id,
            scope=document.scope,
            owner_id=document.owner_id,
            job_type="chunk_embed",
            state="queued",
            priority=PRIORITY["reindex"],
            idempotency_key=f"chunk:{new_version.id}",
            payload={
                "reuse_structured": True,
                "priority": "reindex",
                "storage_key": "" if document.scope == "global" else self._owner_storage_key(session, document.owner_id),
            },
            progress={"stage": "queued"},
            max_attempts=self.settings.jobs.max_attempts,
        )
        audit(session, actor, "document_reindexed", scope=document.scope, target_type="document", target_id=str(document.id))
        return {"job_id": str(job.id), "document_version_id": str(new_version.id)}

    def reprocess(self, session: Session, actor: Actor, document_id: UUID, *, ocr_mode: str | None = None, parser: str | None = None) -> dict:
        if self.settings.maintenance.enabled:
            from rag_store.common.errors import Unavailable

            raise Unavailable("Ingestion is paused for maintenance.")
        document = self._document(session, document_id)
        _require_write(actor, document.scope)
        if ocr_mode and ocr_mode not in {"auto", "force", "native"}:
            raise ValidationFailed("OCR mode must be auto, force, or native.")
        current = self._active_version(session, document)
        route = route_for(Path(document.filename), forced=parser)
        new_version = self._clone_version(session, document, current)
        new_version.parser_name = route
        job = enqueue(
            session,
            document_id=document.id,
            document_version_id=new_version.id,
            scope=document.scope,
            owner_id=document.owner_id,
            job_type="convert",
            state="queued",
            priority=PRIORITY["ordinary"],
            idempotency_key=f"convert:{new_version.id}",
            payload={
                "route": route,
                "ocr_mode": ocr_mode or "auto",
                "priority": "ordinary",
                "storage_key": "" if document.scope == "global" else self._owner_storage_key(session, document.owner_id),
            },
            progress={"stage": "queued"},
            max_attempts=self.settings.jobs.max_attempts,
        )
        audit(session, actor, "document_reprocessed", scope=document.scope, target_type="document", target_id=str(document.id), attributes={"ocr_mode": ocr_mode or "auto"})
        return {"job_id": str(job.id), "document_version_id": str(new_version.id)}

    def list_jobs(self, session: Session, *, document_id: UUID | None = None, state: str | None = None, limit: int = 50) -> list[dict]:
        stmt = select(IngestionJob).order_by(IngestionJob.created_at.desc()).limit(min(max(limit, 1), 200))
        if document_id:
            stmt = stmt.where(IngestionJob.document_id == document_id)
        if state:
            stmt = stmt.where(IngestionJob.state == state)
        return [_job_dict(job) for job in session.scalars(stmt)]

    def get_job(self, session: Session, job_id: UUID) -> dict:
        job = session.get(IngestionJob, job_id)
        if job is None:
            raise NotFound("Job not found.")
        return _job_dict(job)

    def retry(self, session: Session, actor: Actor, job_id: UUID) -> dict:
        job = session.get(IngestionJob, job_id)
        if job is None:
            raise NotFound("Job not found.")
        _require_write(actor, job.scope)
        retry_job(session, job_id)
        audit(session, actor, "job_retried", scope=job.scope, target_type="job", target_id=str(job.id))
        return _job_dict(job)

    def cancel(self, session: Session, actor: Actor, job_id: UUID) -> dict:
        job = session.get(IngestionJob, job_id)
        if job is None:
            raise NotFound("Job not found.")
        _require_write(actor, job.scope)
        cancel_job(session, job_id)
        return _job_dict(job)

    def quota(self, session: Session, actor: Actor) -> dict:
        quota = self._quota(session, actor)
        documents = session.scalar(
            select(func.count()).select_from(Document).where(Document.owner_id == actor.user_id, Document.deleted_at.is_(None))
        )
        collections = session.scalar(
            select(func.count()).select_from(Collection).where(Collection.owner_id == actor.user_id)
        )
        return {
            "used_bytes": quota.used_bytes,
            "max_bytes": quota.max_bytes,
            "document_count": int(documents or 0),
            "max_documents": quota.max_documents,
            "collection_count": int(collections or 0),
            "max_collections": quota.max_collections,
            "max_document_bytes": quota.max_document_bytes,
            "max_concurrent_jobs": quota.max_concurrent_jobs,
            "search_requests_per_minute": quota.search_requests_per_minute,
        }

    def document_versions(self, session: Session, document_id: UUID) -> list[dict]:
        document = self._document(session, document_id)
        rows = session.scalars(
            select(DocumentVersion).where(DocumentVersion.document_id == document.id).order_by(DocumentVersion.version_number.desc())
        ).all()
        return [item for item in (_version_dict(row) for row in rows) if item is not None]

    def list_assets(self, session: Session, document_id: UUID) -> list[dict]:
        document = self._document(session, document_id)
        if document.active_version_id is None:
            return []
        rows = session.scalars(
            select(DocumentAsset).where(DocumentAsset.document_version_id == document.active_version_id).order_by(DocumentAsset.created_at.asc())
        ).all()
        return [
            {
                "id": str(row.id),
                "asset_type": row.asset_type,
                "mime_type": row.mime_type,
                "size_bytes": row.size_bytes,
                "checksum": row.checksum,
                "page_number": row.page_number,
                "relative_path": row.relative_path,
            }
            for row in rows
        ]

    def asset_file(self, session: Session, document_id: UUID, asset_id: UUID) -> tuple[str, str, str]:
        document = self._document(session, document_id)
        asset = session.get(DocumentAsset, asset_id)
        if asset is None or document.active_version_id != asset.document_version_id:
            raise NotFound("Asset not found.")
        storage_key = "" if document.scope == "global" else self._owner_storage_key(session, document.owner_id)
        path = self.layout.absolute(document.scope, storage_key, asset.relative_path)
        if not path.is_file():
            from rag_store.common.errors import Unavailable

            raise Unavailable("The asset file is temporarily unavailable.", details={"degradation": "source_storage_unavailable"})
        return str(path), asset.mime_type, Path(asset.relative_path).name

    def begin_upload(self, session: Session, actor: Actor, *, scope: str, collection_name: str, relative_path: str, filename: str, expected_size: int | None, expected_checksum: str, idempotency_key: str) -> dict:
        if self.settings.maintenance.enabled:
            from rag_store.common.errors import Unavailable

            raise Unavailable("Ingestion is paused for maintenance.")
        _require_write(actor, scope)
        collection = self._by_name(session, actor, scope, collection_name)
        filename = validate_filename(filename)
        relative = join_relative(relative_path, filename) if relative_path else filename
        key = idempotency_key or f"resume:{actor.user_id}:{collection.id}:{relative}:{expected_checksum}"
        existing = session.scalars(select(UploadSession).where(UploadSession.idempotency_key == key)).first()
        if existing is not None:
            return _upload_dict(existing)
        upload_id = uuid4()
        storage_key = "" if scope == "global" else actor.storage_key
        staging = f"staging/{upload_id}/payload"
        self.layout.ensure_tree(scope, storage_key)
        path = self.layout.absolute(scope, storage_key, staging)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")
        row = UploadSession(
            id=upload_id,
            user_id=actor.user_id,
            scope=scope,
            collection_id=collection.id,
            relative_path=relative,
            filename=filename,
            expected_size=expected_size,
            expected_checksum=expected_checksum.lower(),
            bytes_received=0,
            staging_path=staging,
            state="open",
            idempotency_key=key,
            expires_at=utcnow() + timedelta(hours=24),
        )
        session.add(row)
        session.flush()
        return _upload_dict(row)

    def append_upload(self, session: Session, actor: Actor, upload_id: UUID, offset: int, data: bytes) -> dict:
        row = self._upload_session(session, actor, upload_id)
        if row.state != "open":
            raise Conflict("The upload is not open.")
        if offset not in {0, row.bytes_received}:
            raise Conflict("The upload offset does not match the bytes already stored.", details={"bytes_received": row.bytes_received})
        storage_key = "" if row.scope == "global" else actor.storage_key
        path = self.layout.absolute(row.scope, storage_key, row.staging_path)
        if offset == 0:
            row.bytes_received = 0
        with path.open("wb" if offset == 0 else "ab") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        row.bytes_received += len(data)
        if row.bytes_received > self.settings.storage.max_file_bytes:
            path.unlink(missing_ok=True)
            row.state = "failed"
            raise PayloadTooLarge("The file exceeds the configured maximum size.", details={"limit_bytes": self.settings.storage.max_file_bytes})
        row.updated_at = utcnow()
        return _upload_dict(row)

    def complete_upload(self, session: Session, actor: Actor, upload_id: UUID) -> dict:
        row = self._upload_session(session, actor, upload_id)
        if row.state == "completed" and row.document_id is not None:
            return {"document": self.get_document(session, row.document_id), "deduplicated": True, "job_id": None}
        if row.state != "open":
            raise Conflict("The upload cannot be completed.")
        if row.expected_size is not None and row.bytes_received != row.expected_size:
            raise Conflict("The uploaded size does not match the expected size.", details={"bytes_received": row.bytes_received, "expected_size": row.expected_size})
        storage_key = "" if row.scope == "global" else actor.storage_key
        path = self.layout.absolute(row.scope, storage_key, row.staging_path)
        if row.expected_checksum:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest != row.expected_checksum:
                raise ValidationFailed("The uploaded checksum does not match.")
        parent = parent_path(row.relative_path)
        with path.open("rb") as handle:
            result = self.upload(
                session,
                actor,
                scope=row.scope,
                collection_name=session.get(Collection, row.collection_id).name,
                relative_path=parent,
                filename=row.filename,
                source=handle,
                idempotency_key=row.idempotency_key,
            )
        path.unlink(missing_ok=True)
        row.state = "completed"
        row.document_id = UUID(result["document"]["id"])
        row.updated_at = utcnow()
        return result

    def _upload_session(self, session: Session, actor: Actor, upload_id: UUID) -> UploadSession:
        row = session.get(UploadSession, upload_id)
        if row is None:
            raise NotFound("Upload not found.")
        if row.user_id != actor.user_id and not (row.scope == "global" and actor.is_admin):
            raise NotFound("Upload not found.")
        return row

    def ensure_folder(self, session: Session, collection: Collection, relative: str) -> Folder | None:
        if not relative:
            return None
        existing = session.scalars(
            select(Folder).where(
                Folder.collection_id == collection.id,
                Folder.relative_path == relative,
                Folder.deleted_at.is_(None),
            )
        ).first()
        if existing is not None:
            return existing
        parent_relative = parent_path(relative)
        parent = self.ensure_folder(session, collection, parent_relative) if parent_relative else None
        folder = Folder(
            collection_id=collection.id,
            parent_id=parent.id if parent else None,
            name=name_of(relative),
            relative_path=relative,
            parent_path=parent_relative,
            scope=collection.scope,
            owner_id=collection.owner_id,
        )
        session.add(folder)
        session.flush()
        return folder

    def _clone_version(self, session: Session, document: Document, current: DocumentVersion) -> DocumentVersion:
        number = (session.scalar(select(func.max(DocumentVersion.version_number)).where(DocumentVersion.document_id == document.id)) or 0) + 1
        version = DocumentVersion(
            document_id=document.id,
            version_number=number,
            source_path=current.source_path,
            source_checksum=current.source_checksum,
            source_size=current.source_size,
            parser_name=current.parser_name,
            processing_state="queued",
            searchable=False,
        )
        session.add(version)
        session.flush()
        return version

    def _copy_structure(self, session: Session, structured: DoclingDocument, version_id: UUID) -> None:
        clone = DoclingDocument(
            document_version_id=version_id,
            content=structured.content,
            content_storage=structured.content_storage,
            schema_version=structured.schema_version,
            representation=structured.representation,
            markdown=structured.markdown,
            plain_text=structured.plain_text,
            ocr_metadata=structured.ocr_metadata,
            warnings=structured.warnings,
            docling_version=structured.docling_version,
            ocr_engine=structured.ocr_engine,
            ocr_engine_version=structured.ocr_engine_version,
            conversion_config=structured.conversion_config,
            config_checksum=structured.config_checksum,
            source_checksum=structured.source_checksum,
            content_checksum=structured.content_checksum,
            page_count=structured.page_count,
            status=structured.status,
            fallback_path=structured.fallback_path,
        )
        session.add(clone)
        session.flush()
        segments = session.scalars(select(DoclingDocumentSegment).where(DoclingDocumentSegment.docling_document_id == structured.id)).all()
        for segment in segments:
            session.add(
                DoclingDocumentSegment(
                    docling_document_id=clone.id,
                    segment_index=segment.segment_index,
                    content=segment.content,
                    checksum=segment.checksum,
                )
            )

    def _stage(self, scope: str, storage_key: str, upload_id: UUID, source) -> tuple[str, str, int]:
        self.layout.ensure_tree(scope, storage_key)
        relative = f"staging/{upload_id}/payload"
        path = self.layout.absolute(scope, storage_key, relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_suffix(".partial")
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
                        raise PayloadTooLarge("The file exceeds the configured maximum size.", details={"limit_bytes": limit})
                    digest.update(block)
                    handle.write(block)
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            partial.unlink(missing_ok=True)
            raise
        os.replace(partial, path)
        return relative, digest.hexdigest(), size

    def _discard_staged(self, scope: str, actor: Actor, relative: str) -> None:
        storage_key = "" if scope == "global" else actor.storage_key
        path = self.layout.absolute(scope, storage_key, relative)
        path.unlink(missing_ok=True)

    def _collection(self, session: Session, collection_id: UUID) -> Collection:
        row = session.get(Collection, collection_id)
        if row is None:
            raise NotFound("Collection not found.")
        return row

    def _by_name(self, session: Session, actor: Actor, scope: str, name: str) -> Collection:
        stmt = select(Collection).where(Collection.scope == scope, Collection.name == name)
        if scope == "local":
            stmt = stmt.where(Collection.owner_id == actor.user_id)
        row = session.scalars(stmt).first()
        if row is None:
            raise NotFound("Collection not found.")
        return row

    def _document(self, session: Session, document_id: UUID) -> Document:
        document = session.get(Document, document_id)
        if document is None or document.deleted_at is not None:
            raise NotFound("Document not found.")
        return document

    def _active_version(self, session: Session, document: Document) -> DocumentVersion:
        if document.active_version_id is None:
            version = session.scalars(
                select(DocumentVersion).where(DocumentVersion.document_id == document.id).order_by(DocumentVersion.version_number.desc())
            ).first()
        else:
            version = session.get(DocumentVersion, document.active_version_id)
        if version is None:
            raise NotFound("The document has no stored version.")
        return version

    def _structured(self, session: Session, document_id: UUID) -> DoclingDocument:
        document = self._document(session, document_id)
        version = self._active_version(session, document)
        structured = session.scalars(select(DoclingDocument).where(DoclingDocument.document_version_id == version.id)).first()
        if structured is None:
            raise NotFound("Structured content is not available.")
        return structured

    def _quota(self, session: Session, actor: Actor) -> UserQuota:
        quota = session.get(UserQuota, actor.user_id)
        if quota is None:
            raise NotFound("A quota has not been assigned to this account.")
        return quota

    def _quota_bytes(self, session: Session, actor: Actor, size: int) -> None:
        if actor.is_admin and False:
            return
        quota = self._quota(session, actor)
        if quota.used_bytes + size > quota.max_bytes:
            raise QuotaExceeded("The upload would exceed the storage quota.")

    def _quota_jobs(self, session: Session, actor: Actor) -> None:
        quota = self._quota(session, actor)
        active = session.scalar(
            select(func.count()).select_from(IngestionJob).where(
                IngestionJob.owner_id == actor.user_id,
                IngestionJob.state.notin_(["completed", "failed", "cancelled", "conversion_completed"]),
            )
        )
        if active is not None and active >= quota.max_concurrent_jobs:
            raise QuotaExceeded("The account has too many active ingestion jobs.")
        documents = session.scalar(
            select(func.count()).select_from(Document).where(Document.owner_id == actor.user_id, Document.deleted_at.is_(None))
        )
        if documents is not None and documents >= quota.max_documents:
            raise QuotaExceeded("The account has reached its document limit.")

    def _quota_collections(self, session: Session, actor: Actor, scope: str) -> None:
        if scope != "local":
            return
        quota = self._quota(session, actor)
        count = session.scalar(select(func.count()).select_from(Collection).where(Collection.owner_id == actor.user_id))
        if count is not None and count >= quota.max_collections:
            raise QuotaExceeded("The account has reached its collection limit.")

    def _ensure_unique_path(self, session: Session, collection_id: UUID, relative: str, *, ignore: UUID | None) -> None:
        stmt = select(Document).where(Document.collection_id == collection_id, Document.relative_path == relative, Document.deleted_at.is_(None))
        if ignore is not None:
            stmt = stmt.where(Document.id != ignore)
        if session.scalars(stmt).first() is not None:
            raise Conflict("A document already exists at that path.")

    def _owner_storage_key(self, session: Session, owner_id: UUID | None) -> str:
        if owner_id is None:
            return ""
        row = session.execute(text("SELECT storage_key FROM ragstore.lookup_user(:user_id)"), {"user_id": owner_id}).first()
        if row is None:
            raise NotFound("The document owner is not available.")
        return row[0]


def _check_scope(scope: str) -> None:
    if scope not in {"global", "local"}:
        raise ValidationFailed("Scope must be global or local.")


def _require_write(actor: Actor, scope: str) -> None:
    _check_scope(scope)
    if scope == "global" and not actor.is_admin:
        raise Forbidden("Only administrators can modify global knowledge.")
    if scope == "local" and actor.is_service:
        raise Forbidden("Service accounts cannot use local knowledge.")


def _collection_name(name: str) -> str:
    clean = name.strip().lower()
    if not clean or len(clean) > 128 or any(char in clean for char in "/\\ "):
        raise ValidationFailed("Collection names are lowercase words without spaces.")
    return clean


def _collection_dict(collection: Collection) -> dict:
    return {
        "id": str(collection.id),
        "name": collection.name,
        "scope": collection.scope,
        "description": collection.description,
        "is_default": collection.is_default,
        "created_at": _iso(collection.created_at),
        "updated_at": _iso(collection.updated_at),
    }


def _folder_dict(folder: Folder) -> dict:
    return {"id": str(folder.id), "name": folder.name, "path": folder.relative_path}


def _document_summary(session: Session, document: Document) -> dict:
    job = session.scalars(
        select(IngestionJob).where(IngestionJob.document_id == document.id).order_by(IngestionJob.created_at.desc())
    ).first()
    return {
        "id": str(document.id),
        "collection_id": str(document.collection_id),
        "scope": document.scope,
        "filename": document.filename,
        "relative_path": document.relative_path,
        "parent_path": document.parent_path,
        "file_type": document.file_type,
        "lifecycle_state": document.lifecycle_state,
        "tags": list(document.tags or []),
        "metadata": document.attributes or {},
        "active_version_id": str(document.active_version_id) if document.active_version_id else None,
        "ingestion_state": job.state if job else None,
        "job_id": str(job.id) if job else None,
        "progress": job.progress if job else {},
        "created_at": _iso(document.created_at),
        "updated_at": _iso(document.updated_at),
    }


def _version_dict(version: DocumentVersion | None) -> dict | None:
    if version is None:
        return None
    return {
        "id": str(version.id),
        "version_number": version.version_number,
        "checksum": version.source_checksum,
        "size": version.source_size,
        "parser": version.parser_name,
        "processing_state": version.processing_state,
        "searchable": version.searchable,
        "failure_reason": version.failure_reason,
        "created_at": _iso(version.created_at),
    }


def _conversion_dict(structured: DoclingDocument) -> dict:
    return {
        "id": str(structured.id),
        "status": structured.status,
        "representation": structured.representation,
        "schema_version": structured.schema_version,
        "storage": structured.content_storage,
        "docling_version": structured.docling_version,
        "ocr_engine": structured.ocr_engine,
        "ocr_engine_version": structured.ocr_engine_version,
        "ocr": structured.ocr_metadata,
        "warnings": structured.warnings,
        "page_count": structured.page_count,
        "content_checksum": structured.content_checksum,
        "source_checksum": structured.source_checksum,
        "config_checksum": structured.config_checksum,
        "fallback_path": structured.fallback_path,
        "created_at": _iso(structured.created_at),
    }


def _job_dict(job: IngestionJob) -> dict:
    return {
        "id": str(job.id),
        "document_id": str(job.document_id) if job.document_id else None,
        "document_version_id": str(job.document_version_id) if job.document_version_id else None,
        "scope": job.scope,
        "job_type": job.job_type,
        "state": job.state,
        "priority": job.priority,
        "attempt_count": job.attempt_count,
        "max_attempts": job.max_attempts,
        "progress": job.progress or {},
        "last_error": job.last_error,
        "created_at": _iso(job.created_at),
        "updated_at": _iso(job.updated_at),
        "started_at": _iso(job.started_at),
        "finished_at": _iso(job.finished_at),
    }


def _upload_dict(row: UploadSession) -> dict:
    return {
        "id": str(row.id),
        "scope": row.scope,
        "collection_id": str(row.collection_id),
        "relative_path": row.relative_path,
        "filename": row.filename,
        "expected_size": row.expected_size,
        "bytes_received": row.bytes_received,
        "state": row.state,
        "document_id": str(row.document_id) if row.document_id else None,
        "expires_at": _iso(row.expires_at),
    }


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat()
