"""Uvicorn launcher shared by the HTTP components."""

from __future__ import annotations

import uvicorn

from rag_store.common.logging import configure_logging, install_offline_environment
from rag_store.config.settings import get_settings


def serve(app_path: str) -> None:
    install_offline_environment()
    settings = get_settings()
    configure_logging(settings.log_level)
    uvicorn.run(
        app_path,
        host=settings.http.host,
        port=settings.http.port,
        factory=True,
        log_level=settings.log_level.lower(),
        timeout_graceful_shutdown=settings.jobs.shutdown_grace_seconds,
    )
