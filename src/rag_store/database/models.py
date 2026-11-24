"""Relational model.

PostgreSQL is the authoritative store for identity, documents, Docling output,
chunks, embeddings, jobs, and coordination. Original binaries stay on the
filesystem. The ``metadata`` column is exposed as ``attributes`` because
SQLAlchemy reserves the attribute name ``metadata``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from rag_store.config.settings import SCHEMA_EMBEDDING_DIMENSIONS

SCHEMA = "ragstore"


class Base(DeclarativeBase):
    metadata = MetaData(schema=SCHEMA)


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('admin', 'user', 'service')", name="users_role_chk"),
        CheckConstraint("storage_key ~ '^user-[0-9a-f]{12}$'", name="users_storage_key_chk"),
        # The first account is inserted before an actor exists. RETURNING would
        # also apply the SELECT policy, which cannot see that row yet.
        {"implicit_returning": False},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    storage_key: Mapped[str] = mapped_column(String(32), unique=True)
    username: Mapped[str] = mapped_column(String(128), unique=True)
    display_name: Mapped[str] = mapped_column(String(256))
    email: Mapped[str | None] = mapped_column(String(320))
    password_hash: Mapped[str | None] = mapped_column(String(512))
    external_subject: Mapped[str | None] = mapped_column(String(512), unique=True)
    role: Mapped[str] = mapped_column(String(32))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ApiCredential(Base):
    __tablename__ = "api_credentials"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    key_prefix: Mapped[str] = mapped_column(String(32))
    key_hash: Mapped[str] = mapped_column(String(128), unique=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserQuota(Base):
    __tablename__ = "user_quotas"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"), primary_key=True)
    max_bytes: Mapped[int] = mapped_column(BigInteger)
    used_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    max_documents: Mapped[int] = mapped_column(Integer)
    max_collections: Mapped[int] = mapped_column(Integer)
    max_document_bytes: Mapped[int] = mapped_column(BigInteger)
    max_concurrent_uploads: Mapped[int] = mapped_column(Integer)
    max_concurrent_jobs: Mapped[int] = mapped_column(Integer)
    search_requests_per_minute: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Collection(Base):
    __tablename__ = "collections"
    __table_args__ = (
        CheckConstraint("scope IN ('global', 'local')", name="collections_scope_chk"),
        CheckConstraint(
            "(scope = 'global' AND owner_id IS NULL) OR (scope = 'local' AND owner_id IS NOT NULL)",
            name="collections_owner_chk",
        ),
        Index("collections_global_name_uq", "name", unique=True, postgresql_where=text("scope = 'global'")),
        Index("collections_local_name_uq", "owner_id", "name", unique=True, postgresql_where=text("scope = 'local'")),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(128))
    scope: Mapped[str] = mapped_column(String(16))
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey(f"{SCHEMA}.users.id"))
    description: Mapped[str] = mapped_column(Text, default="")
    attributes: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Folder(Base):
    __tablename__ = "folders"
    __table_args__ = (
        CheckConstraint("scope IN ('global', 'local')", name="folders_scope_chk"),
        Index(
            "folders_collection_path_uq",
            "collection_id",
            "relative_path",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("folders_parent_idx", "collection_id", "parent_path"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    collection_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.collections.id", ondelete="CASCADE"))
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey(f"{SCHEMA}.folders.id"))
    name: Mapped[str] = mapped_column(String(255))
    relative_path: Mapped[str] = mapped_column(String(1024))
    parent_path: Mapped[str] = mapped_column(String(1024), default="")
    scope: Mapped[str] = mapped_column(String(16))
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey(f"{SCHEMA}.users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint("scope IN ('global', 'local')", name="documents_scope_chk"),
        CheckConstraint(
            "lifecycle_state IN ('processing', 'active', 'deleted', 'failed')",
            name="documents_lifecycle_chk",
        ),
        Index(
            "documents_collection_path_uq",
            "collection_id",
            "relative_path",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("documents_parent_idx", "collection_id", "parent_path"),
        Index("documents_owner_idx", "owner_id", "scope"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    collection_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.collections.id"))
    folder_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey(f"{SCHEMA}.folders.id"))
    scope: Mapped[str] = mapped_column(String(16))
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey(f"{SCHEMA}.users.id"))
    filename: Mapped[str] = mapped_column(String(255))
    relative_path: Mapped[str] = mapped_column(String(1024))
    parent_path: Mapped[str] = mapped_column(String(1024), default="")
    file_type: Mapped[str] = mapped_column(String(32), default="")
    active_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(f"{SCHEMA}.document_versions.id", use_alter=True, name="fk_documents_active_version", ondelete="SET NULL")
    )
    lifecycle_state: Mapped[str] = mapped_column(String(32), default="processing")
    attributes: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)
    tags: Mapped[list[str]] = mapped_column(ARRAY(String(64)), default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "version_number", name="document_versions_number_uq"),
        Index("document_versions_checksum_idx", "source_checksum"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.documents.id", ondelete="CASCADE"), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    source_path: Mapped[str] = mapped_column(String(1024))
    source_checksum: Mapped[str] = mapped_column(String(64))
    source_size: Mapped[int] = mapped_column(BigInteger)
    parser_name: Mapped[str] = mapped_column(String(64), default="")
    parser_config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    conversion_config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    chunking_config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    processing_state: Mapped[str] = mapped_column(String(32), default="queued")
    searchable: Mapped[bool] = mapped_column(Boolean, default=False)
    failure_reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DoclingDocument(Base):
    __tablename__ = "docling_documents"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    document_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.document_versions.id", ondelete="CASCADE"), unique=True
    )
    content: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    content_storage: Mapped[str] = mapped_column(String(32))
    schema_version: Mapped[str] = mapped_column(String(64), default="")
    representation: Mapped[str] = mapped_column(String(32))
    markdown: Mapped[str | None] = mapped_column(Text)
    plain_text: Mapped[str | None] = mapped_column(Text)
    ocr_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    warnings: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    docling_version: Mapped[str] = mapped_column(String(64), default="")
    ocr_engine: Mapped[str] = mapped_column(String(64), default="")
    ocr_engine_version: Mapped[str] = mapped_column(String(64), default="")
    conversion_config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    config_checksum: Mapped[str] = mapped_column(String(64), default="")
    source_checksum: Mapped[str] = mapped_column(String(64))
    content_checksum: Mapped[str] = mapped_column(String(64))
    page_count: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32))
    fallback_path: Mapped[str] = mapped_column(String(1024), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DoclingDocumentSegment(Base):
    __tablename__ = "docling_document_segments"
    __table_args__ = (UniqueConstraint("docling_document_id", "segment_index", name="docling_segments_uq"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    docling_document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.docling_documents.id", ondelete="CASCADE"), index=True
    )
    segment_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[dict[str, Any]] = mapped_column(JSONB)
    checksum: Mapped[str] = mapped_column(String(64))


class DocumentTable(Base):
    __tablename__ = "document_tables"
    __table_args__ = (UniqueConstraint("document_version_id", "table_index", name="document_tables_uq"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    document_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.document_versions.id", ondelete="CASCADE"), index=True
    )
    table_index: Mapped[int] = mapped_column(Integer)
    page_number: Mapped[int | None] = mapped_column(Integer)
    caption: Mapped[str] = mapped_column(Text, default="")
    section_path: Mapped[str] = mapped_column(Text, default="")
    content: Mapped[dict[str, Any]] = mapped_column(JSONB)
    checksum: Mapped[str] = mapped_column(String(64))


class DocumentAsset(Base):
    __tablename__ = "document_assets"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    document_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.document_versions.id", ondelete="CASCADE"), index=True
    )
    scope: Mapped[str] = mapped_column(String(16))
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey(f"{SCHEMA}.users.id"))
    relative_path: Mapped[str] = mapped_column(String(1024))
    asset_type: Mapped[str] = mapped_column(String(64))
    mime_type: Mapped[str] = mapped_column(String(128), default="application/octet-stream")
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    checksum: Mapped[str] = mapped_column(String(64))
    page_number: Mapped[int | None] = mapped_column(Integer)
    docling_object_id: Mapped[str] = mapped_column(String(128), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("document_version_id", "sequence", name="document_chunks_sequence_uq"),
        CheckConstraint("scope IN ('global', 'local')", name="chunks_scope_chk"),
        Index("document_chunks_search_idx", "search_vector", postgresql_using="gin"),
        Index("document_chunks_document_idx", "document_id"),
        Index("document_chunks_collection_idx", "collection_id", "scope"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    document_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.document_versions.id", ondelete="CASCADE"))
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.documents.id", ondelete="CASCADE"))
    collection_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.collections.id"))
    scope: Mapped[str] = mapped_column(String(16))
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey(f"{SCHEMA}.users.id"))
    sequence: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    lexical_text: Mapped[str] = mapped_column(Text)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    page_number: Mapped[int | None] = mapped_column(Integer)
    section_path: Mapped[str] = mapped_column(Text, default="")
    table_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey(f"{SCHEMA}.document_tables.id", ondelete="SET NULL"))
    line_start: Mapped[int | None] = mapped_column(Integer)
    line_end: Mapped[int | None] = mapped_column(Integer)
    content_checksum: Mapped[str] = mapped_column(String(64))
    search_vector: Mapped[Any] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('simple', coalesce(lexical_text, ''))", persisted=True),
    )
    chunking_config_version: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EmbeddingModel(Base):
    __tablename__ = "embedding_models"
    __table_args__ = (UniqueConstraint("name", "version", "dimensions", name="embedding_models_identity_uq"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(256))
    version: Mapped[str] = mapped_column(String(128), default="")
    dimensions: Mapped[int] = mapped_column(Integer)
    metric: Mapped[str] = mapped_column(String(32), default="cosine")
    tokenizer: Mapped[str] = mapped_column(String(256), default="")
    preprocessing: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChunkEmbedding(Base):
    __tablename__ = "chunk_embeddings"
    __table_args__ = (
        UniqueConstraint("chunk_id", "embedding_model_id", name="chunk_embeddings_model_uq"),
        Index(
            "chunk_embeddings_hnsw_idx",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    chunk_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.document_chunks.id", ondelete="CASCADE"), index=True)
    embedding_model_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.embedding_models.id"))
    dimensions: Mapped[int] = mapped_column(Integer, default=SCHEMA_EMBEDDING_DIMENSIONS)
    metric: Mapped[str] = mapped_column(String(32), default="cosine")
    embedding: Mapped[list[float]] = mapped_column(Vector(SCHEMA_EMBEDDING_DIMENSIONS))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="ingestion_jobs_idempotency_uq"),
        CheckConstraint("scope IN ('global', 'local')", name="jobs_scope_chk"),
        Index("ingestion_jobs_document_idx", "document_id"),
        Index(
            "ingestion_jobs_claim_idx",
            "priority",
            "next_run_at",
            "created_at",
            postgresql_where=text("state IN ('queued', 'retry_pending')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey(f"{SCHEMA}.documents.id", ondelete="CASCADE"))
    document_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey(f"{SCHEMA}.document_versions.id", ondelete="CASCADE"))
    scope: Mapped[str] = mapped_column(String(16))
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey(f"{SCHEMA}.users.id"))
    job_type: Mapped[str] = mapped_column(String(32))
    state: Mapped[str] = mapped_column(String(32), default="queued")
    priority: Mapped[int] = mapped_column(Integer, default=50)
    idempotency_key: Mapped[str] = mapped_column(String(200))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    progress: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    worker_id: Mapped[str | None] = mapped_column(String(128))
    fencing_token: Mapped[int] = mapped_column(Integer, default=0)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IngestionAttempt(Base):
    __tablename__ = "ingestion_attempts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.ingestion_jobs.id", ondelete="CASCADE"), index=True)
    attempt_number: Mapped[int] = mapped_column(Integer)
    worker_id: Mapped[str] = mapped_column(String(128))
    fencing_token: Mapped[int] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str] = mapped_column(String(32), default="running")
    error: Mapped[str] = mapped_column(Text, default="")


class DistributedLease(Base):
    __tablename__ = "distributed_leases"

    name: Mapped[str] = mapped_column(String(128), primary_key=True)
    holder_id: Mapped[str] = mapped_column(String(128))
    fencing_token: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class InferencePermit(Base):
    __tablename__ = "inference_permits"
    __table_args__ = (Index("inference_permits_kind_idx", "kind", "expires_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    kind: Mapped[str] = mapped_column(String(32))
    holder_id: Mapped[str] = mapped_column(String(128))
    priority: Mapped[int] = mapped_column(Integer, default=50)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"

    worker_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    component: Mapped[str] = mapped_column(String(64))
    hostname: Mapped[str] = mapped_column(String(255), default="")
    pid: Mapped[int] = mapped_column(Integer, default=0)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("audit_events_created_idx", "created_at"),
        # Failed logins insert an event before an actor exists. RETURNING would
        # apply the administrator-only SELECT policy and reject the insert.
        {"implicit_returning": False},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey(f"{SCHEMA}.users.id"))
    action: Mapped[str] = mapped_column(String(64))
    scope: Mapped[str] = mapped_column(String(16), default="")
    target_type: Mapped[str] = mapped_column(String(64), default="")
    target_id: Mapped[str] = mapped_column(String(64), default="")
    attributes: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UploadSession(Base):
    __tablename__ = "upload_sessions"
    __table_args__ = (UniqueConstraint("idempotency_key", name="upload_sessions_idempotency_uq"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.users.id"))
    scope: Mapped[str] = mapped_column(String(16))
    collection_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.collections.id"))
    relative_path: Mapped[str] = mapped_column(String(1024))
    filename: Mapped[str] = mapped_column(String(255))
    expected_size: Mapped[int | None] = mapped_column(BigInteger)
    expected_checksum: Mapped[str] = mapped_column(String(64), default="")
    bytes_received: Mapped[int] = mapped_column(BigInteger, default=0)
    staging_path: Mapped[str] = mapped_column(String(1024))
    state: Mapped[str] = mapped_column(String(32), default="open")
    idempotency_key: Mapped[str] = mapped_column(String(200))
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey(f"{SCHEMA}.documents.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DropboxObservation(Base):
    __tablename__ = "dropbox_observations"
    __table_args__ = (UniqueConstraint("scope", "storage_key", "relative_path", name="dropbox_observations_uq"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    scope: Mapped[str] = mapped_column(String(16))
    storage_key: Mapped[str] = mapped_column(String(64), default="")
    relative_path: Mapped[str] = mapped_column(String(1024))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    mtime_ns: Mapped[int] = mapped_column(BigInteger)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    stable: Mapped[bool] = mapped_column(Boolean, default=False)
    last_error: Mapped[str] = mapped_column(Text, default="")


class RateBucket(Base):
    __tablename__ = "rate_buckets"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"), primary_key=True)
    action: Mapped[str] = mapped_column(String(64), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)
