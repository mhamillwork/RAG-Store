"""Ingestion worker process."""

from __future__ import annotations

import signal

from rag_store.common.logging import configure_logging, install_offline_environment
from rag_store.config.settings import get_settings
from rag_store.database.session import build_engine, build_session_factory
from rag_store.entrypoints.probes import start_probe_server
from rag_store.workers.loop import Worker


def main() -> None:
    install_offline_environment()
    settings = get_settings()
    configure_logging(settings.log_level)
    sessions = build_session_factory(build_engine(settings))
    start_probe_server(settings, sessions, lambda: [])
    worker = Worker(settings, sessions, kind="ingestion")

    def _stop(*_args) -> None:
        worker.stop()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    worker.serve()


if __name__ == "__main__":
    main()
