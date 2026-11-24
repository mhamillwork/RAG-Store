"""Semantic, keyword, and hybrid retrieval.

Authorization is the caller's database identity plus explicit scope filters.
Ordinary searches read chunks, embeddings, and document metadata. They do not
load Docling documents.
"""

from __future__ import annotations

import time
from datetime import datetime

from sqlalchemy import Select, func, or_, select, text
from sqlalchemy.orm import Session

from rag_store.common.errors import Forbidden, NotFound, Unavailable, ValidationFailed
from rag_store.config.settings import Settings
from rag_store.database.models import (
    ChunkEmbedding,
    Collection,
    Document,
    DocumentChunk,
    DocumentVersion,
    EmbeddingModel,
)
from rag_store.embedding.client import EmbeddingClient
from rag_store.monitoring import metrics
from rag_store.reranking.client import RerankClient
from rag_store.search.ranking import ordered, reciprocal_rank_fusion


class SearchService:
    def __init__(self, settings: Settings, embeddings: EmbeddingClient, reranker: RerankClient):
        self.settings = settings
        self.embeddings = embeddings
        self.reranker = reranker

    def search(self, session: Session, actor, body: dict) -> dict:
        started = time.monotonic()
        mode = body.get("mode") or self.settings.search.default_mode
        if mode not in {"semantic", "keyword", "hybrid"}:
            raise ValidationFailed("Search mode must be semantic, keyword, or hybrid.")
        query = (body.get("query") or "").strip()
        if not query:
            raise ValidationFailed("A query is required.")
        if len(query) > 4000:
            raise ValidationFailed("The query is too long.")
        top_k = int(body.get("top_k") or self.settings.search.default_top_k)
        top_k = max(1, min(top_k, self.settings.search.max_top_k))
        requested_scope = body.get("scope") or "all"
        scope, notes = _effective_scope(actor, requested_scope)
        filters = body.get("filters") or {}
        want_rerank = bool(body.get("rerank", False))
        reasons: list[str] = list(notes)
        degraded = bool(notes)
        semantic_rows: dict[str, dict] = {}
        lexical_rows: dict[str, dict] = {}
        semantic_order: list[str] = []
        lexical_order: list[str] = []
        model = _active_model(session, self.settings) if mode in {"semantic", "hybrid"} else None

        if mode in {"semantic", "hybrid"}:
            try:
                if model is None:
                    raise Unavailable("No embeddings are indexed for the configured model.")
                vector = self.embeddings.embed_query(query)
                semantic_order, semantic_rows = self._semantic(session, vector, model.id, scope, filters, top_k)
            except Unavailable as exc:
                if mode == "semantic" or not self.settings.search.allow_keyword_fallback:
                    metrics.SEARCH_REQUESTS.labels(mode=mode, outcome="error").inc()
                    raise
                degraded = True
                reason = exc.details.get("degradation", "embedding_unavailable")
                reasons.append(reason)
                metrics.DEGRADED_SEARCHES.labels(reason=reason).inc()
                mode = "keyword"

        if mode in {"keyword", "hybrid"}:
            lexical_order, lexical_rows = self._keyword(session, query, scope, filters, top_k)

        if mode == "hybrid" and semantic_order:
            fused = reciprocal_rank_fusion([semantic_order, lexical_order], k=self.settings.search.rrf_k)
            ranking = ordered(fused)
            pool = {**lexical_rows, **semantic_rows}
            for item_id, score in fused.items():
                if item_id in pool:
                    pool[item_id]["score"] = score
        elif mode == "keyword" or not semantic_order:
            ranking = lexical_order
            pool = lexical_rows
            for position, item_id in enumerate(ranking, start=1):
                pool[item_id]["score"] = pool[item_id].get("lexical_score") or 0
        else:
            ranking = semantic_order
            pool = semantic_rows
            for item_id in ranking:
                distance = pool[item_id].get("distance")
                pool[item_id]["score"] = None if distance is None else 1 - distance

        candidates = [pool[item_id] for item_id in ranking if item_id in pool]
        rerank_applied = False
        rerank_provider = ""
        if want_rerank:
            limit = self.settings.reranking.candidate_count
            chosen = candidates[:limit]
            try:
                ranked, rerank_provider = self.reranker.rerank(query, [item["content"] for item in chosen])
            except Unavailable as exc:
                if not self.settings.reranking.allow_fallback:
                    raise
                degraded = True
                reason = exc.details.get("degradation", "reranking_unavailable")
                reasons.append(reason)
                metrics.DEGRADED_SEARCHES.labels(reason=reason).inc()
                ranked = None
            if ranked is None:
                if self.settings.reranking.enabled and self.settings.reranking.provider:
                    degraded = True
                    reasons.append("reranking_unavailable")
                else:
                    reasons.append("reranking_not_configured")
            else:
                rerank_applied = True
                reordered = []
                for index, score in ranked:
                    item = dict(chosen[index])
                    item["rerank_score"] = score
                    item["score"] = score
                    reordered.append(item)
                candidates = reordered + candidates[limit:]
        hits = candidates[:top_k]
        for hit in hits:
            hit["source_reference"] = f"/api/v1/documents/{hit['document_id']}"
            hit.pop("distance", None)
        outcome = "degraded" if degraded else "ok"
        metrics.SEARCH_REQUESTS.labels(mode=body.get("mode") or self.settings.search.default_mode, outcome=outcome).inc()
        metrics.SEARCH_DURATION.labels(mode=mode).observe(time.monotonic() - started)
        metrics.SEARCH_RESULTS.observe(len(hits))
        return {
            "query": query,
            "mode": mode,
            "scope": scope,
            "degraded": degraded,
            "degradation_reasons": reasons,
            "rerank_applied": rerank_applied,
            "rerank_provider": rerank_provider,
            "hits": hits,
        }

    def _semantic(self, session, vector, model_id, scope, filters, top_k) -> tuple[list[str], dict[str, dict]]:
        candidates = max(top_k, self.settings.search.candidate_count)
        _try_iterative_scan(session)
        stmt = _base_query(scope, filters).join(ChunkEmbedding, ChunkEmbedding.chunk_id == DocumentChunk.id)
        distance = ChunkEmbedding.embedding.cosine_distance(vector)
        stmt = (
            stmt.where(ChunkEmbedding.embedding_model_id == model_id)
            .add_columns(distance.label("distance"))
            .order_by(distance)
            .limit(candidates)
        )
        rows = session.execute(stmt).all()
        if self.settings.search.exact_fallback and len(rows) < top_k:
            with session.begin_nested():
                session.execute(text("SET LOCAL enable_indexscan = off"))
                session.execute(text("SET LOCAL enable_bitmapscan = off"))
                rows = session.execute(stmt).all()
        order = []
        found = {}
        for chunk, document, collection, version, distance_value in rows:
            similarity = 1 - float(distance_value)
            if similarity < self.settings.search.similarity_threshold:
                continue
            item = _hit(chunk, document, collection, semantic_score=similarity, distance=float(distance_value))
            found[str(chunk.id)] = item
            order.append(str(chunk.id))
        return order, found

    def _keyword(self, session, query, scope, filters, top_k) -> tuple[list[str], dict[str, dict]]:
        candidates = max(top_k, self.settings.search.candidate_count)
        tsq = func.websearch_to_tsquery("simple", query)
        rank = func.ts_rank_cd(DocumentChunk.search_vector, tsq)
        stmt = _base_query(scope, filters)
        identifier = _identifier_query(query)
        if identifier:
            like = _like(query)
            stmt = stmt.where(
                or_(
                    DocumentChunk.search_vector.op("@@")(tsq),
                    DocumentChunk.content.ilike(like, escape="\\"),
                    Document.filename.ilike(like, escape="\\"),
                )
            )
        else:
            stmt = stmt.where(DocumentChunk.search_vector.op("@@")(tsq))
        stmt = stmt.add_columns(rank.label("lexical_rank")).order_by(rank.desc()).limit(candidates)
        rows = session.execute(stmt).all()
        order = []
        found = {}
        for chunk, document, collection, version, lexical_rank in rows:
            item = _hit(chunk, document, collection, lexical_score=float(lexical_rank or 0))
            found[str(chunk.id)] = item
            order.append(str(chunk.id))
        return order, found


def _base_query(scope: str, filters: dict) -> Select:
    stmt = (
        select(DocumentChunk, Document, Collection, DocumentVersion)
        .join(Document, Document.id == DocumentChunk.document_id)
        .join(Collection, Collection.id == Document.collection_id)
        .join(DocumentVersion, DocumentVersion.id == DocumentChunk.document_version_id)
        .where(Document.lifecycle_state == "active")
        .where(Document.deleted_at.is_(None))
        .where(Document.active_version_id == DocumentChunk.document_version_id)
        .where(DocumentVersion.searchable.is_(True))
    )
    if scope == "global":
        stmt = stmt.where(Document.scope == "global")
    elif scope == "local":
        stmt = stmt.where(Document.scope == "local")
    collection_ids = filters.get("collection_ids") or []
    if collection_ids:
        stmt = stmt.where(Document.collection_id.in_(collection_ids))
    names = filters.get("collection_names") or []
    if names:
        stmt = stmt.where(Collection.name.in_(names))
    document_ids = filters.get("document_ids") or []
    if document_ids:
        stmt = stmt.where(Document.id.in_(document_ids))
    if filters.get("filename"):
        stmt = stmt.where(Document.filename.ilike(_like(filters["filename"]), escape="\\"))
    if filters.get("path_prefix"):
        prefix = filters["path_prefix"].replace("%", "").replace("_", "")
        stmt = stmt.where(Document.relative_path.like(prefix + "%", escape="\\"))
    file_types = filters.get("file_types") or []
    if file_types:
        stmt = stmt.where(Document.file_type.in_([item.lower().lstrip(".") for item in file_types]))
    tags = filters.get("tags") or []
    if tags:
        stmt = stmt.where(Document.tags.overlap(tags))
    if filters.get("metadata"):
        stmt = stmt.where(Document.attributes.contains(filters["metadata"]))
    for field, column, op_name in (
        ("created_after", Document.created_at, "ge"),
        ("created_before", Document.created_at, "le"),
        ("modified_after", Document.updated_at, "ge"),
        ("modified_before", Document.updated_at, "le"),
    ):
        if filters.get(field):
            moment = _parse_time(filters[field])
            stmt = stmt.where(column >= moment) if op_name == "ge" else stmt.where(column <= moment)
    return stmt


def _hit(chunk, document, collection, *, semantic_score=None, lexical_score=None, distance=None) -> dict:
    return {
        "chunk_id": str(chunk.id),
        "document_id": str(document.id),
        "document_version_id": str(chunk.document_version_id),
        "collection_id": str(collection.id),
        "collection": collection.name,
        "filename": document.filename,
        "relative_path": document.relative_path,
        "scope": document.scope,
        "page_number": chunk.page_number,
        "section": chunk.section_path,
        "line_start": chunk.line_start,
        "line_end": chunk.line_end,
        "table_id": str(chunk.table_id) if chunk.table_id else None,
        "content": chunk.content[:4000],
        "semantic_score": semantic_score,
        "lexical_score": lexical_score,
        "rerank_score": None,
        "score": semantic_score if semantic_score is not None else lexical_score,
        "distance": distance,
    }


def _active_model(session: Session, settings: Settings) -> EmbeddingModel | None:
    if not settings.embedding.model and settings.embedding.provider != "deterministic-test":
        return None
    name = settings.embedding.model or "deterministic-test"
    return session.scalars(
        select(EmbeddingModel).where(
            EmbeddingModel.name == name,
            EmbeddingModel.dimensions == settings.embedding.dimensions,
            EmbeddingModel.active.is_(True),
        )
    ).first()


def _effective_scope(actor, requested: str) -> tuple[str, list[str]]:
    if requested not in {"all", "global", "local"}:
        raise ValidationFailed("Scope must be all, global, or local.")
    if actor.is_service:
        if requested == "local":
            raise Forbidden("Service accounts cannot search local knowledge.")
        if requested == "all":
            return "global", ["service accounts search global knowledge only"]
        return "global", []
    return requested, []


def _identifier_query(query: str) -> bool:
    return " " not in query and any(char in query for char in "_./:-")


def _like(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _parse_time(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationFailed("A filter timestamp is not valid.") from exc


def _try_iterative_scan(session: Session) -> None:
    try:
        with session.begin_nested():
            session.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
    except Exception:
        return


def require_visible_document(session: Session, document_id) -> Document:
    document = session.get(Document, document_id)
    if document is None or document.deleted_at is not None:
        raise NotFound("Document not found.")
    return document
