"""Reranking adapters.

Granite deployments do not share one HTTP contract. ``tei`` and ``cohere`` are
explicit adapters. A failed call does not invent scores. Fallback, when enabled,
returns the original order and records that reranking did not run.
"""

from __future__ import annotations

import re
import time

import httpx

from rag_store.common.errors import ConfigurationError, Unavailable
from rag_store.config.settings import Settings
from rag_store.database.session import session_scope
from rag_store.monitoring import metrics
from rag_store.workers.permits import acquire_permit, release_permit


class RerankClient:
    def __init__(self, settings: Settings, session_factory):
        self.settings = settings
        self.session_factory = session_factory

    def rerank(self, query: str, texts: list[str]) -> tuple[list[tuple[int, float]] | None, str]:
        """Return (ranked index/score pairs, provider name). None means reranking did not run."""

        if not texts:
            return [], ""
        provider = self.settings.reranking.provider
        if not self.settings.reranking.enabled or not provider:
            return None, ""
        if provider == "lexical-test":
            if self.settings.environment == "production":
                raise ConfigurationError("The lexical test reranker cannot be used in production.")
            return _lexical(query, texts), "lexical-test"
        if provider not in {"tei", "cohere"}:
            raise Unavailable(
                f"Reranking provider '{provider}' is not implemented.",
                details={"degradation": "reranking_unconfigured"},
            )
        if not self.settings.reranking.base_url:
            raise Unavailable("The reranking base URL is not configured.", details={"degradation": "reranking_unconfigured"})
        holder = self.settings.worker_id or self.settings.component
        permit_id = None
        started = time.monotonic()
        try:
            with session_scope(self.session_factory, actor=None) as session:
                permit_id = acquire_permit(session, self.settings, kind="reranking", holder=holder, priority="interactive")
            return self._request(query, texts), provider
        except Unavailable:
            metrics.RERANK_FAILURES.inc()
            if self.settings.reranking.allow_fallback:
                return None, provider
            raise
        finally:
            metrics.RERANK_DURATION.observe(time.monotonic() - started)
            if permit_id is not None:
                with session_scope(self.session_factory, actor=None) as session:
                    release_permit(session, permit_id)

    def _request(self, query: str, texts: list[str]) -> list[tuple[int, float]]:
        settings = self.settings.reranking
        url = settings.base_url.rstrip("/") + "/" + settings.api_path.lstrip("/")
        headers = {"Content-Type": "application/json"}
        if settings.api_key:
            headers["Authorization"] = f"Bearer {settings.api_key}"
        if settings.provider == "tei":
            body = {"query": query, "texts": texts}
        else:
            body = {"model": settings.model, "query": query, "documents": texts}
        verify: bool | str = settings.ca_bundle or settings.tls_verify
        last_error = "rerank request failed"
        for attempt in range(settings.max_retries + 1):
            try:
                response = httpx.post(url, json=body, headers=headers, timeout=settings.timeout_seconds, verify=verify)
            except httpx.HTTPError as exc:
                last_error = exc.__class__.__name__
                time.sleep(min(2 ** attempt, 8))
                continue
            if response.status_code in {429, 500, 502, 503, 504}:
                last_error = f"HTTP {response.status_code}"
                time.sleep(min(2 ** attempt, 8))
                continue
            if response.status_code >= 400:
                raise Unavailable("The reranking service rejected the request.", details={"status": response.status_code})
            return _parse(settings.provider, response.json(), len(texts))
        raise Unavailable("The reranking service is unavailable.", details={"reason": last_error, "degradation": "reranking_unavailable"})


def _parse(provider: str, payload, expected: int) -> list[tuple[int, float]]:
    if provider == "tei":
        rows = payload if isinstance(payload, list) else payload.get("results", [])
        parsed = [(int(row["index"]), float(row["score"])) for row in rows]
    else:
        rows = payload.get("results") or []
        parsed = [(int(row["index"]), float(row.get("relevance_score", row.get("score")))) for row in rows]
    if len(parsed) != expected:
        raise Unavailable("The reranking service returned an unexpected number of scores.")
    parsed.sort(key=lambda item: item[1], reverse=True)
    return parsed


def _lexical(query: str, texts: list[str]) -> list[tuple[int, float]]:
    needles = set(re.findall(r"[a-z0-9_]+", query.lower()))
    scored = []
    for index, text in enumerate(texts):
        tokens = set(re.findall(r"[a-z0-9_]+", text.lower()))
        score = (len(needles & tokens) / len(needles)) if needles else 0.0
        scored.append((index, score))
    scored.sort(key=lambda item: item[1], reverse=True)
    return scored
