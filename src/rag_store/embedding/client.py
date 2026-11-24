"""Embedding providers.

The OpenAI-compatible client talks to the existing Nomic service. The
deterministic provider exists only for development and tests and is rejected
when the environment is production. Embeddings are never invented in production
when the inference service is unavailable.
"""

from __future__ import annotations

import hashlib
import math
import re
import time

import httpx

from rag_store.common.errors import ConfigurationError, Unavailable
from rag_store.config.settings import Settings
from rag_store.database.session import session_scope
from rag_store.monitoring import metrics
from rag_store.workers.permits import acquire_permit, release_permit


def deterministic_embedding(text: str, dimensions: int) -> list[float]:
    """Token-overlap vector for tests. This is not a semantic embedding model."""

    vector = [0.0] * dimensions
    tokens = re.findall(r"[a-z0-9_]+", text.lower()) or ["empty"]
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


class EmbeddingClient:
    def __init__(self, settings: Settings, session_factory):
        self.settings = settings
        self.session_factory = session_factory

    def embed_query(self, text: str) -> list[float]:
        return self.embed([text], kind="query", priority="interactive")[0]

    def embed_documents(self, texts: list[str], *, priority: str = "bulk") -> list[list[float]]:
        return self.embed(texts, kind="document", priority=priority)

    def embed(self, texts: list[str], *, kind: str, priority: str) -> list[list[float]]:
        if not texts:
            return []
        provider = self.settings.embedding.provider
        prefix = self.settings.embedding.query_prefix if kind == "query" else self.settings.embedding.document_prefix
        prepared = [f"{prefix}{text}" for text in texts]
        if provider == "deterministic-test":
            if self.settings.environment == "production":
                raise ConfigurationError("The deterministic test embedding provider cannot be used in production.")
            return [deterministic_embedding(text, self.settings.embedding.dimensions) for text in prepared]
        if provider != "openai-compatible":
            raise Unavailable("No embedding service is configured.", details={"degradation": "embedding_unconfigured"})
        if not self.settings.embedding.base_url or not self.settings.embedding.model:
            raise Unavailable(
                "The embedding base URL and model identifier must be configured.",
                details={"degradation": "embedding_unconfigured"},
            )
        vectors: list[list[float]] = []
        batch_size = max(1, self.settings.embedding.batch_size)
        for start in range(0, len(prepared), batch_size):
            batch = prepared[start : start + batch_size]
            vectors.extend(self._request(batch, priority=priority))
        return vectors

    def _request(self, batch: list[str], *, priority: str) -> list[list[float]]:
        holder = self.settings.worker_id or self.settings.component
        permit_id = None
        started = time.monotonic()
        try:
            with session_scope(self.session_factory, actor=None) as session:
                permit_id = acquire_permit(session, self.settings, kind="embedding", holder=holder, priority=priority)
            url = self.settings.embedding.base_url.rstrip("/") + "/" + self.settings.embedding.api_path.lstrip("/")
            headers = {"Content-Type": "application/json"}
            if self.settings.embedding.api_key:
                headers["Authorization"] = f"Bearer {self.settings.embedding.api_key}"
            verify: bool | str = self.settings.embedding.ca_bundle or self.settings.embedding.tls_verify
            last_error = "embedding request failed"
            for attempt in range(self.settings.embedding.max_retries + 1):
                try:
                    response = httpx.post(
                        url,
                        json={"model": self.settings.embedding.model, "input": batch},
                        headers=headers,
                        timeout=self.settings.embedding.timeout_seconds,
                        verify=verify,
                    )
                except httpx.HTTPError as exc:
                    last_error = str(exc.__class__.__name__)
                    time.sleep(min(2 ** attempt, 10))
                    continue
                if response.status_code in {429, 500, 502, 503, 504}:
                    last_error = f"HTTP {response.status_code}"
                    metrics.EMBEDDING_FAILURES.inc()
                    time.sleep(min(2 ** attempt, 10))
                    continue
                if response.status_code >= 400:
                    metrics.EMBEDDING_FAILURES.inc()
                    raise Unavailable(
                        "The embedding service rejected the request.",
                        details={"status": response.status_code, "degradation": "embedding_unavailable"},
                    )
                payload = response.json()
                rows = sorted(payload.get("data") or [], key=lambda item: item.get("index", 0))
                if len(rows) != len(batch):
                    raise Unavailable("The embedding service returned an unexpected number of vectors.")
                vectors = []
                for row in rows:
                    vector = row.get("embedding")
                    if not isinstance(vector, list) or len(vector) != self.settings.embedding.dimensions:
                        raise Unavailable(
                            "The embedding service returned a vector with an unexpected dimension.",
                            details={"expected": self.settings.embedding.dimensions, "actual": len(vector or [])},
                        )
                    vectors.append([float(value) for value in vector])
                metrics.EMBEDDING_REQUESTS.labels(priority=priority).inc()
                metrics.EMBEDDING_DURATION.observe(time.monotonic() - started)
                return vectors
            metrics.EMBEDDING_FAILURES.inc()
            raise Unavailable(
                "The embedding service is unavailable.",
                details={"degradation": "embedding_unavailable", "reason": last_error},
            )
        finally:
            if permit_id is not None:
                with session_scope(self.session_factory, actor=None) as session:
                    release_permit(session, permit_id)
