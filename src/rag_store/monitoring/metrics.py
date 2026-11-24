"""Prometheus metrics.

Labels stay low-cardinality. Queue depth is computed from PostgreSQL at scrape
time; dashboards should aggregate it with max(), because every replica reports
the same queue.
"""

from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

SEARCH_REQUESTS = Counter("rag_store_search_requests_total", "Search requests", ["mode", "outcome"])
SEARCH_DURATION = Histogram(
    "rag_store_search_duration_seconds",
    "End-to-end search duration",
    ["mode"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
)
SEARCH_RESULTS = Histogram(
    "rag_store_search_results",
    "Number of hits returned",
    buckets=(0, 1, 5, 10, 20, 50),
)
DEGRADED_SEARCHES = Counter("rag_store_search_degraded_total", "Searches that returned a degraded result", ["reason"])
EMBEDDING_REQUESTS = Counter("rag_store_embedding_requests_total", "Embedding requests", ["priority"])
EMBEDDING_FAILURES = Counter("rag_store_embedding_failures_total", "Embedding request failures")
EMBEDDING_DURATION = Histogram(
    "rag_store_embedding_duration_seconds",
    "Embedding request duration",
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 15, 30, 60),
)
RERANK_FAILURES = Counter("rag_store_rerank_failures_total", "Reranking failures")
RERANK_DURATION = Histogram(
    "rag_store_rerank_duration_seconds",
    "Reranking duration",
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 15),
)
JOBS = Counter("rag_store_jobs_total", "Job outcomes", ["job_type", "outcome"])
JOB_DURATION = Histogram(
    "rag_store_job_duration_seconds",
    "Job processing duration",
    ["job_type"],
    buckets=(0.1, 0.5, 1, 5, 15, 60, 300, 900, 3600),
)
CHUNKS_GENERATED = Counter("rag_store_chunks_generated_total", "Chunks generated")
CHUNKS_EMBEDDED = Counter("rag_store_chunks_embedded_total", "Chunks embedded")
OCR_PAGES = Counter("rag_store_ocr_pages_total", "Pages recorded as processed with OCR")
CONVERSIONS = Counter("rag_store_conversions_total", "Document conversions", ["route", "outcome"])
BACKPRESSURE = Counter("rag_store_backpressure_total", "Inference permit refusals", ["kind"])
SCANNER_LEADER = Gauge("rag_store_scanner_leader", "1 when this process holds the scanner lease")
MODEL_READY = Gauge("rag_store_docling_model_ready", "1 when required Docling artifacts were found")
DB_UP = Gauge("rag_store_database_up", "1 when the process can query PostgreSQL")
JOBS_PENDING = Gauge("rag_store_jobs_pending", "Claimable or active jobs", ["state"])
OLDEST_PENDING_SECONDS = Gauge("rag_store_oldest_pending_job_seconds", "Age of the oldest claimable job")
STORAGE_FREE_BYTES = Gauge("rag_store_storage_free_bytes", "Free bytes on a mounted document root", ["scope"])


def render() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST
