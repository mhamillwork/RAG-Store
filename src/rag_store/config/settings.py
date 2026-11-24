"""Process configuration.

Every environment-specific value is read from the environment. Internal hostnames,
credentials, and model identifiers are not hardcoded. Nested fields use the
``RAG_STORE_<SECTION>__<FIELD>`` form, for example ``RAG_STORE_EMBEDDING__BASE_URL``.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from rag_store.common.errors import ConfigurationError

SCHEMA_EMBEDDING_DIMENSIONS = 768
_INSECURE_SECRETS = {"", "change-me", "secret", "password", "rag-store"}


class DatabaseSettings(BaseModel):
    url: str = ""
    pool_size: int = 5
    max_overflow: int = 5
    pool_timeout_seconds: int = 30
    schema_name: str = "ragstore"


class HttpSettings(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8080
    root_path: str = ""


class AuthSettings(BaseModel):
    jwt_secret: str = ""
    jwt_ttl_seconds: int = 900
    refresh_ttl_seconds: int = 60 * 60 * 12
    bootstrap_admin_username: str = ""
    bootstrap_admin_password: str = ""
    oidc_issuer: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_redirect_url: str = ""
    oidc_scopes: str = "openid profile email"


class StorageSettings(BaseModel):
    global_root: str = "/data/global"
    local_root: str = "/data/local"
    stability_seconds: int = 10
    exclude_directories: str = ".git,node_modules,__pycache__,.venv,build,dist,.idea,.vscode"
    max_file_bytes: int = 1024 * 1024 * 1024


class EmbeddingSettings(BaseModel):
    provider: str = ""
    base_url: str = ""
    api_path: str = "/v1/embeddings"
    model: str = ""
    api_key: str = ""
    dimensions: int = SCHEMA_EMBEDDING_DIMENSIONS
    batch_size: int = 32
    timeout_seconds: int = 120
    max_retries: int = 5
    query_prefix: str = ""
    document_prefix: str = ""
    tls_verify: bool = True
    ca_bundle: str = ""


class RerankingSettings(BaseModel):
    enabled: bool = False
    provider: str = ""
    base_url: str = ""
    model: str = ""
    api_path: str = "/rerank"
    api_key: str = ""
    candidate_count: int = 40
    top_k: int = 10
    timeout_seconds: int = 60
    max_retries: int = 3
    tls_verify: bool = True
    ca_bundle: str = ""
    allow_fallback: bool = True


class ConcurrencySettings(BaseModel):
    embedding_global_limit: int = 12
    embedding_reserved_interactive: int = 4
    rerank_global_limit: int = 8
    permit_ttl_seconds: int = 180


class ChunkingSettings(BaseModel):
    strategy: Literal["auto", "paragraph", "heading", "page", "table", "code"] = "auto"
    max_tokens: int = 512
    overlap_tokens: int = 64
    tokenizer_mode: Literal["basic", "huggingface"] = "huggingface"
    tokenizer_path: str = ""
    tokenizer_required: bool = True


class DoclingSettings(BaseModel):
    enabled: bool = True
    artifacts_path: str = "/models/docling"
    offline_mode: bool = True
    allow_remote_services: bool = False
    allow_model_downloads: bool = False
    device: Literal["cpu"] = "cpu"
    num_threads: int = 8
    max_concurrent_documents: int = 1
    max_pages: int = 2000
    max_document_mib: int = 1024
    timeout_seconds: int = 3600
    ocr_enabled: bool = True
    ocr_engine: Literal["rapidocr", "tesseract", "tesseract_cli"] = "rapidocr"
    ocr_mode: Literal["auto", "force", "native"] = "auto"
    ocr_languages: str = "en"
    force_full_page_ocr: bool = False
    table_structure_enabled: bool = True
    table_mode: Literal["accurate", "fast"] = "accurate"
    structured_max_bytes: int = 8 * 1024 * 1024
    partial_policy: Literal["reject", "allow"] = "reject"
    layout_enabled: bool = True

    def language_list(self) -> list[str]:
        return [part.strip() for part in self.ocr_languages.split(",") if part.strip()]


class SearchSettings(BaseModel):
    default_mode: Literal["semantic", "keyword", "hybrid"] = "hybrid"
    default_top_k: int = 10
    max_top_k: int = 50
    candidate_count: int = 40
    rrf_k: int = 60
    similarity_threshold: float = 0.0
    allow_keyword_fallback: bool = True
    exact_fallback: bool = True


class JobSettings(BaseModel):
    lease_seconds: int = 300
    max_attempts: int = 5
    heartbeat_seconds: int = 15
    retry_base_seconds: int = 10
    poll_seconds: float = 1.0
    shutdown_grace_seconds: int = 120


class MaintenanceSettings(BaseModel):
    enabled: bool = False


class QuotaSettings(BaseModel):
    max_bytes: int = 10 * 1024 * 1024 * 1024
    max_documents: int = 10000
    max_collections: int = 50
    max_document_bytes: int = 1024 * 1024 * 1024
    max_concurrent_uploads: int = 4
    max_concurrent_jobs: int = 4
    search_requests_per_minute: int = 60


class ScannerSettings(BaseModel):
    interval_seconds: float = 5.0
    lease_seconds: int = 30
    lease_name: str = "dropbox-scanner"


class McpSettings(BaseModel):
    path: str = "/mcp"
    allowed_hosts: str = "localhost,127.0.0.1"
    allowed_origins: str = ""
    protect_dns_rebinding: bool = True

    def host_list(self) -> list[str]:
        return [part.strip() for part in self.allowed_hosts.split(",") if part.strip()]

    def origin_list(self) -> list[str]:
        return [part.strip() for part in self.allowed_origins.split(",") if part.strip()]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RAG_STORE_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    environment: Literal["production", "development", "test"] = "production"
    component: Literal["search", "files", "worker", "scanner", "mcp", "docling", "all"] = "search"
    instance_name: str = "rag-store"
    log_level: str = "INFO"
    worker_id: str = ""
    public_base_url: str = ""

    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    http: HttpSettings = Field(default_factory=HttpSettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    embedding: EmbeddingSettings = Field(default_factory=EmbeddingSettings)
    reranking: RerankingSettings = Field(default_factory=RerankingSettings)
    concurrency: ConcurrencySettings = Field(default_factory=ConcurrencySettings)
    chunking: ChunkingSettings = Field(default_factory=ChunkingSettings)
    docling: DoclingSettings = Field(default_factory=DoclingSettings)
    search: SearchSettings = Field(default_factory=SearchSettings)
    jobs: JobSettings = Field(default_factory=JobSettings)
    maintenance: MaintenanceSettings = Field(default_factory=MaintenanceSettings)
    quota: QuotaSettings = Field(default_factory=QuotaSettings)
    scanner: ScannerSettings = Field(default_factory=ScannerSettings)
    mcp: McpSettings = Field(default_factory=McpSettings)

    @model_validator(mode="after")
    def _apply_maintenance_mode_variable(self) -> Settings:
        raw = os.environ.get("MAINTENANCE_MODE")
        if raw is not None and raw.strip().lower() in {"1", "true", "yes", "on"}:
            self.maintenance.enabled = True
        return self

    def validate_runtime(self) -> None:
        problems: list[str] = []
        if not self.database.url:
            problems.append("RAG_STORE_DATABASE__URL is required.")
        if len(self.auth.jwt_secret) < 32 or self.auth.jwt_secret.lower() in _INSECURE_SECRETS:
            problems.append("RAG_STORE_AUTH__JWT_SECRET must be at least 32 characters and not a placeholder.")
        if self.embedding.dimensions != SCHEMA_EMBEDDING_DIMENSIONS:
            problems.append(
                f"RAG_STORE_EMBEDDING__DIMENSIONS is {self.embedding.dimensions}, but the schema "
                f"vector column is vector({SCHEMA_EMBEDDING_DIMENSIONS}). Apply a dimension migration "
                "before changing this value."
            )
        if self.concurrency.embedding_reserved_interactive >= self.concurrency.embedding_global_limit:
            problems.append("Reserved interactive embedding capacity must be lower than the global limit.")
        if self.concurrency.embedding_reserved_interactive < 0:
            problems.append("Reserved interactive embedding capacity cannot be negative.")
        if self.chunking.overlap_tokens >= self.chunking.max_tokens:
            problems.append("Chunk overlap must be smaller than the chunk size.")
        if self.chunking.max_tokens < 32:
            problems.append("Chunk size must be at least 32 tokens.")
        if self.docling.max_concurrent_documents < 1:
            problems.append("Docling document concurrency must be at least 1.")
        if self.search.candidate_count < self.search.default_top_k:
            problems.append("Search candidate count must be at least the default result count.")

        production = self.environment == "production"
        if production:
            if self.component == "all":
                problems.append("The combined 'all' component is only available for development and tests.")
            if self.embedding.provider in {"deterministic-test", "fake", "mock"}:
                problems.append("Test embedding providers are rejected in production.")
            if self.reranking.provider in {"lexical-test", "fake", "mock"}:
                problems.append("Test reranking providers are rejected in production.")
            if not self.docling.enabled:
                problems.append("Docling cannot be disabled in production.")
            if not self.docling.ocr_enabled:
                problems.append("OCR cannot be disabled in production.")
            if not self.docling.offline_mode:
                problems.append("Docling offline mode is required in production.")
            if self.docling.allow_model_downloads:
                problems.append("Docling model downloads are not permitted in production.")
            if self.docling.allow_remote_services:
                problems.append("Docling remote services are not permitted in production.")
            if self.docling.device != "cpu":
                problems.append("Docling must run on CPU.")
            if self.chunking.tokenizer_required and self.chunking.tokenizer_mode == "huggingface" and not self.chunking.tokenizer_path:
                problems.append(
                    "A local tokenizer file is required. Set RAG_STORE_CHUNKING__TOKENIZER_PATH to a tokenizer "
                    "prepared inside the isolated network. The application will not download one."
                )
            if self.chunking.tokenizer_mode == "basic" and self.chunking.tokenizer_required:
                problems.append(
                    "The basic tokenizer is an approximation. Production workers that require a tokenizer "
                    "must use tokenizer_mode=huggingface with a local tokenizer file, or set "
                    "RAG_STORE_CHUNKING__TOKENIZER_REQUIRED=false only for a documented temporary exception."
                )
        if problems:
            raise ConfigurationError("Configuration is not valid.", details={"problems": problems})

    def excluded_directories(self) -> set[str]:
        return {part.strip() for part in self.storage.exclude_directories.split(",") if part.strip()}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.validate_runtime()
    return settings


def load_settings() -> Settings:
    """Reload settings from the environment. Tests use this after changing variables."""

    get_settings.cache_clear()
    return get_settings()
