"""Shared process objects for the HTTP services."""

from __future__ import annotations

from dataclasses import dataclass

from rag_store.config.settings import Settings
from rag_store.database.session import build_engine, build_session_factory
from rag_store.embedding.client import EmbeddingClient
from rag_store.ingestion.catalog import Catalog
from rag_store.reranking.client import RerankClient
from rag_store.search.service import SearchService
from rag_store.storage.layout import StorageLayout


@dataclass
class Runtime:
    settings: Settings
    engine: object
    sessions: object
    catalog: Catalog
    search: SearchService
    layout: StorageLayout

    @classmethod
    def create(cls, settings: Settings) -> Runtime:
        engine = build_engine(settings)
        sessions = build_session_factory(engine)
        embeddings = EmbeddingClient(settings, sessions)
        return cls(
            settings=settings,
            engine=engine,
            sessions=sessions,
            catalog=Catalog(settings),
            search=SearchService(settings, embeddings, RerankClient(settings, sessions)),
            layout=StorageLayout(settings),
        )
