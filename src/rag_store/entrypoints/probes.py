"""Small HTTP probe server for processes that are not FastAPI applications."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from sqlalchemy import text

from rag_store.database.session import session_scope
from rag_store.monitoring import metrics


def start_probe_server(settings, session_factory, ready) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path.startswith("/healthz"):
                self._json(200, {"status": "ok"})
                return
            if self.path.startswith("/readyz"):
                try:
                    with session_scope(session_factory) as session:
                        session.execute(text("SELECT 1"))
                    metrics.DB_UP.set(1)
                    problems = ready()
                except Exception as exc:
                    metrics.DB_UP.set(0)
                    self._json(503, {"status": "not_ready", "database": exc.__class__.__name__})
                    return
                if problems:
                    self._json(503, {"status": "not_ready", "problems": problems})
                    return
                self._json(200, {"status": "ready", "component": settings.component, "maintenance": settings.maintenance.enabled})
                return
            if self.path.startswith("/metrics"):
                body, content_type = metrics.render()
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self._json(404, {"error": {"code": "not_found", "message": "Not found."}})

        def _json(self, status: int, payload: dict) -> None:
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, fmt: str, *args) -> None:
            return

    server = ThreadingHTTPServer((settings.http.host, settings.http.port), Handler)
    threading.Thread(target=server.serve_forever, name="probes", daemon=True).start()
    return server
