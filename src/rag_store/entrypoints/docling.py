"""Docling and OCR worker process."""

from __future__ import annotations

import signal

from rag_store.common.logging import configure_logging, install_offline_environment
from rag_store.config.settings import get_settings
from rag_store.database.session import build_engine, build_session_factory
from rag_store.docling.adapter import DoclingAdapter
from rag_store.entrypoints.probes import start_probe_server
from rag_store.monitoring import metrics
from rag_store.workers.loop import Worker


def main() -> None:
    install_offline_environment()
    settings = get_settings()
    configure_logging(settings.log_level)
    adapter = DoclingAdapter(settings)
    try:
        adapter.validate()
        metrics.MODEL_READY.set(1)
    except Exception:
        metrics.MODEL_READY.set(0)
        raise
    sessions = build_session_factory(build_engine(settings))

    def ready() -> list[str]:
        try:
            adapter.validate()
            metrics.MODEL_READY.set(1)
            return []
        except Exception as exc:
            metrics.MODEL_READY.set(0)
            return [str(exc)]

    start_probe_server(settings, sessions, ready)
    worker = Worker(settings, sessions, kind="docling", docling=adapter)

    def _stop(*_args) -> None:
        worker.stop()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    worker.serve()


if __name__ == "__main__":
    main()
