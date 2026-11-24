"""Conversion and indexing stages.

Database transactions are not held open during parsing, OCR, or embedding calls.
A chunking retry rebuilds the unpublished version. The currently searchable
version is replaced only in the transaction that commits the new chunks.
"""

from __future__ import annotations

import time
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from rag_store.chunking.chunker import chunk_document, normalize_table
from rag_store.chunking.tokenizer import build_tokenizer
from rag_store.common.checksum import sha256_bytes
from rag_store.common.errors import LeaseLost, Unavailable
from rag_store.config.settings import Settings
from rag_store.database.models import (
    ChunkEmbedding,
    DoclingDocument,
    DoclingDocumentSegment,
    Document,
    DocumentChunk,
    DocumentTable,
    DocumentVersion,
    EmbeddingModel,
)
from rag_store.database.session import session_scope
from rag_store.docling.structured import json_bytes, prepare_structure, reassemble
from rag_store.embedding.client import EmbeddingClient
from rag_store.ingestion.jobs import PRIORITY, enqueue, fail_or_retry, heartbeat, set_state, succeed
from rag_store.monitoring import metrics
from rag_store.parsers.text import parse_text
from rag_store.storage.layout import StorageLayout


class Pipeline:
    def __init__(self, settings: Settings, session_factory, embeddings: EmbeddingClient, docling=None):
        self.settings = settings
        self.session_factory = session_factory
        self.embeddings = embeddings
        self.layout = StorageLayout(settings)
        self.docling = docling
        self.tokenizer = build_tokenizer(settings.chunking)

    def convert(self, job_id: UUID, token: int, worker_id: str) -> None:
        started = time.monotonic()
        with session_scope(self.session_factory) as session:
            set_state(session, job_id, token, worker_id, "validating")
            context = self._context(session, job_id)
        path = self.layout.absolute(context["scope"], context["storage_key"], context["source_path"])
        if not path.is_file():
            self._fail(job_id, token, worker_id, "source file is missing")
            return
        try:
            if context["route"] == "lightweight":
                parsed = parse_text(context["filename"], path.read_bytes(), max_bytes=self.settings.storage.max_file_bytes)
                parsed["content"] = {
                    "representation": parsed["representation"],
                    "schema_version": parsed["schema_version"],
                    "name": parsed["name"],
                    "texts": parsed["texts"],
                    "tables": parsed["tables"],
                }
            else:
                if self.docling is None:
                    raise Unavailable("This worker is not configured to run Docling.")
                with session_scope(self.session_factory) as session:
                    state = "ocr_processing" if context["ocr_mode"] in {"force"} or path.suffix.lower() in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"} else "converting"
                    set_state(session, job_id, token, worker_id, state, {"stage": state})
                parsed = self.docling.convert(path, ocr_mode=context["ocr_mode"])
                parsed["content"] = parsed["content"]
        except LeaseLost:
            raise
        except Exception as exc:
            self._fail(job_id, token, worker_id, str(exc))
            metrics.CONVERSIONS.labels(route=context["route"], outcome="failed").inc()
            return
        texts = (parsed.get("content") or {}).get("texts") or []
        tables = (parsed.get("content") or {}).get("tables") or []
        plain = (parsed.get("plain_text") or "").strip()
        has_text = bool(plain) or any((item.get("text") or "").strip() for item in texts) or bool(tables)
        if not has_text or (parsed.get("status") == "partial" and self.settings.docling.partial_policy == "reject"):
            self._fail(job_id, token, worker_id, "extraction was empty or incomplete and was not published")
            metrics.CONVERSIONS.labels(route=context["route"], outcome="rejected").inc()
            return
        prepared = prepare_structure(parsed["content"], self.settings.docling.structured_max_bytes)
        fallback_relative = ""
        if prepared.fallback_bytes is not None:
            fallback_relative = f"assets/{context['document_id']}/{context['version_id']}/structured.json"
            target = self.layout.absolute(context["scope"], context["storage_key"], fallback_relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(prepared.fallback_bytes)
        with session_scope(self.session_factory) as session:
            heartbeat(session, job_id, token, worker_id, self.settings.jobs.lease_seconds)
            self._store_conversion(session, context, parsed, prepared, fallback_relative)
            enqueue(
                session,
                document_id=context["document_id"],
                document_version_id=context["version_id"],
                scope=context["scope"],
                owner_id=context["owner_id"],
                job_type="chunk_embed",
                state="queued",
                priority=PRIORITY.get(context["priority"], PRIORITY["ordinary"]),
                idempotency_key=f"chunk:{context['version_id']}",
                payload={"priority": context["priority"], "storage_key": context["storage_key"], "route": context["route"]},
                progress={"stage": "queued"},
                max_attempts=self.settings.jobs.max_attempts,
            )
            succeed(session, job_id, token, worker_id, state="conversion_completed")
        metrics.CONVERSIONS.labels(route=context["route"], outcome="completed").inc()
        metrics.JOB_DURATION.labels(job_type="convert").observe(time.monotonic() - started)

    def chunk_and_embed(self, job_id: UUID, token: int, worker_id: str) -> None:
        started = time.monotonic()
        with session_scope(self.session_factory) as session:
            set_state(session, job_id, token, worker_id, "chunking", {"stage": "chunking"})
            context = self._context(session, job_id)
            structured = session.scalars(
                select(DoclingDocument).where(DoclingDocument.document_version_id == context["version_id"])
            ).first()
            if structured is None:
                raise Unavailable("Structured content is not available for chunking.")
            segments = session.scalars(
                select(DoclingDocumentSegment).where(DoclingDocumentSegment.docling_document_id == structured.id)
            ).all()
            fallback = None
            if structured.content_storage == "longhorn_fallback" and structured.fallback_path:
                fallback = self.layout.read_bytes(context["scope"], context["storage_key"], structured.fallback_path)
            document_dict = reassemble(
                structured.content,
                [{"segment_index": item.segment_index, "content": item.content} for item in segments],
                fallback,
            )
            filename = context["filename"]
            relative_path = context["relative_path"]
            file_type = context["file_type"]
            plain = structured.plain_text or ""
        if plain and "plain_text" not in document_dict:
            document_dict = {**document_dict, "plain_text": plain}
        drafts = chunk_document(
            document_dict,
            filename=filename,
            relative_path=relative_path,
            file_type=file_type,
            max_tokens=self.settings.chunking.max_tokens,
            overlap_tokens=self.settings.chunking.overlap_tokens,
            strategy=self.settings.chunking.strategy,
            tokenizer=self.tokenizer,
        )
        metrics.CHUNKS_GENERATED.inc(len(drafts))
        if not drafts:
            self._fail(job_id, token, worker_id, "chunking produced no searchable content")
            return
        priority = context["priority"] if context["priority"] in {"interactive", "ordinary", "bulk", "reindex"} else "bulk"
        embed_priority = "ordinary" if priority == "reindex" else priority
        try:
            with session_scope(self.session_factory) as session:
                set_state(session, job_id, token, worker_id, "embedding", {"stage": "embedding", "chunks_generated": len(drafts)})
            vectors = self.embeddings.embed_documents([draft.content for draft in drafts], priority=embed_priority if embed_priority != "reindex" else "bulk")
        except LeaseLost:
            raise
        except Exception as exc:
            self._fail(job_id, token, worker_id, str(exc))
            return
        if len(vectors) != len(drafts):
            self._fail(job_id, token, worker_id, "the embedding service returned a different number of vectors")
            return
        with session_scope(self.session_factory) as session:
            set_state(session, job_id, token, worker_id, "indexing", {"stage": "indexing", "chunks_embedded": len(vectors)})
            self._publish(session, context, drafts, vectors, job_id, token, worker_id)
        metrics.CHUNKS_EMBEDDED.inc(len(vectors))
        metrics.JOBS.labels(job_type="chunk_embed", outcome="completed").inc()
        metrics.JOB_DURATION.labels(job_type="chunk_embed").observe(time.monotonic() - started)

    def _publish(self, session: Session, context: dict, drafts, vectors, job_id, token, worker_id) -> None:
        heartbeat(session, job_id, token, worker_id, self.settings.jobs.lease_seconds)
        version = session.get(DocumentVersion, context["version_id"])
        document = session.get(Document, context["document_id"])
        if version is None or document is None:
            raise Unavailable("The document version disappeared before publication.")
        session.execute(delete(DocumentChunk).where(DocumentChunk.document_version_id == version.id))
        tables = {
            row.table_index: row.id
            for row in session.scalars(select(DocumentTable).where(DocumentTable.document_version_id == version.id))
        }
        model = self._model(session)
        chunk_rows = []
        for draft in drafts:
            chunk = DocumentChunk(
                document_version_id=version.id,
                document_id=document.id,
                collection_id=document.collection_id,
                scope=document.scope,
                owner_id=document.owner_id,
                sequence=draft.sequence,
                content=draft.content,
                lexical_text=draft.lexical_text,
                provenance=draft.provenance,
                page_number=draft.page_number,
                section_path=draft.section_path,
                table_id=tables.get(draft.table_index) if draft.table_index is not None else None,
                line_start=draft.line_start,
                line_end=draft.line_end,
                content_checksum=draft.content_checksum,
                chunking_config_version=self.tokenizer.name,
            )
            session.add(chunk)
            chunk_rows.append((chunk, vectors[draft.sequence]))
        session.flush()
        for chunk, vector in chunk_rows:
            session.add(
                ChunkEmbedding(
                    chunk_id=chunk.id,
                    embedding_model_id=model.id,
                    dimensions=self.settings.embedding.dimensions,
                    metric="cosine",
                    embedding=vector,
                )
            )
        set_state(session, job_id, token, worker_id, "publishing", {"stage": "publishing"})
        document.active_version_id = version.id
        document.lifecycle_state = "active"
        document.updated_at = version.created_at
        version.searchable = True
        version.processing_state = "completed"
        session.execute(
            update(DocumentVersion)
            .where(DocumentVersion.document_id == document.id, DocumentVersion.id != version.id)
            .values(searchable=False)
        )
        session.execute(
            delete(DocumentChunk).where(DocumentChunk.document_id == document.id, DocumentChunk.document_version_id != version.id)
        )
        session.flush()
        succeed(session, job_id, token, worker_id, state="completed")

    def _store_conversion(self, session, context, parsed, prepared, fallback_relative: str) -> None:
        status = parsed.get("status") or "success"
        if prepared.warnings:
            status = "warning" if status == "success" else status
        record = DoclingDocument(
            document_version_id=context["version_id"],
            content=prepared.content,
            content_storage=prepared.content_storage,
            schema_version=parsed.get("schema_version") or "",
            representation=parsed.get("representation") or "docling",
            markdown=parsed.get("markdown"),
            plain_text=parsed.get("plain_text"),
            ocr_metadata=parsed.get("ocr") or {},
            warnings=list(parsed.get("warnings") or []) + prepared.warnings,
            docling_version=parsed.get("docling_version") or "",
            ocr_engine=(parsed.get("ocr") or {}).get("engine") or "",
            ocr_engine_version=(parsed.get("ocr") or {}).get("engine_version") or "",
            conversion_config={"ocr_mode": context["ocr_mode"], "route": context["route"]},
            config_checksum=sha256_bytes(json_bytes({"ocr_mode": context["ocr_mode"], "route": context["route"]})),
            source_checksum=context["checksum"],
            content_checksum=prepared.content_checksum,
            page_count=parsed.get("page_count"),
            status=status,
            fallback_path=fallback_relative,
        )
        session.add(record)
        session.flush()
        for segment in prepared.segments:
            body = segment["content"]
            session.add(
                DoclingDocumentSegment(
                    docling_document_id=record.id,
                    segment_index=segment["segment_index"],
                    content=body,
                    checksum=sha256_bytes(json_bytes(body)),
                )
            )
        tables = (parsed.get("content") or {}).get("tables") or []
        for index, table in enumerate(tables):
            headers, rows, caption, page = normalize_table(table)
            content = {"headers": headers, "rows": rows, "caption": caption}
            session.add(
                DocumentTable(
                    document_version_id=context["version_id"],
                    table_index=index,
                    page_number=page,
                    caption=caption,
                    section_path=table.get("section_path") or "",
                    content=content,
                    checksum=sha256_bytes(json_bytes(content)),
                )
            )
        if parsed.get("ocr", {}).get("applied") and parsed.get("page_count"):
            metrics.OCR_PAGES.inc(parsed["page_count"])

    def _model(self, session: Session) -> EmbeddingModel:
        name = self.settings.embedding.model or ("deterministic-test" if self.settings.embedding.provider == "deterministic-test" else "")
        if not name:
            raise Unavailable("No embedding model is configured.")
        model = session.scalars(
            select(EmbeddingModel).where(
                EmbeddingModel.name == name,
                EmbeddingModel.dimensions == self.settings.embedding.dimensions,
            )
        ).first()
        if model is None:
            model = EmbeddingModel(
                name=name,
                version="configured",
                dimensions=self.settings.embedding.dimensions,
                metric="cosine",
                tokenizer=self.tokenizer.name,
                preprocessing={
                    "query_prefix": self.settings.embedding.query_prefix,
                    "document_prefix": self.settings.embedding.document_prefix,
                },
                active=True,
            )
            session.add(model)
            session.flush()
        session.execute(update(EmbeddingModel).where(EmbeddingModel.id != model.id).values(active=False))
        model.active = True
        return model

    def _context(self, session: Session, job_id: UUID) -> dict:
        from rag_store.database.models import IngestionJob

        job = session.get(IngestionJob, job_id)
        if job is None:
            raise Unavailable("The job no longer exists.")
        version = session.get(DocumentVersion, job.document_version_id) if job.document_version_id else None
        document = session.get(Document, job.document_id) if job.document_id else None
        if version is None or document is None:
            raise Unavailable("The job no longer points at a document.")
        payload = job.payload or {}
        return {
            "job_id": job.id,
            "document_id": document.id,
            "version_id": version.id,
            "scope": document.scope,
            "owner_id": document.owner_id,
            "storage_key": payload.get("storage_key") or "",
            "source_path": version.source_path,
            "filename": document.filename,
            "relative_path": document.relative_path,
            "file_type": document.file_type,
            "checksum": version.source_checksum,
            "route": payload.get("route") or version.parser_name,
            "ocr_mode": payload.get("ocr_mode") or "auto",
            "priority": payload.get("priority") or "ordinary",
        }

    def _fail(self, job_id, token, worker_id, error: str) -> None:
        with session_scope(self.session_factory) as session:
            try:
                outcome = fail_or_retry(
                    session,
                    job_id,
                    token,
                    worker_id,
                    error,
                    base_seconds=self.settings.jobs.retry_base_seconds,
                )
            except LeaseLost:
                return
        metrics.JOBS.labels(job_type="failed", outcome=outcome).inc()
