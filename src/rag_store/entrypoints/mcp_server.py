"""MCP process. Streamable HTTP, stateless, no in-memory session store."""

from __future__ import annotations

import uvicorn
from mcp.server.transport_security import TransportSecuritySettings

from rag_store.api.runtime import Runtime
from rag_store.common.logging import configure_logging, install_offline_environment
from rag_store.config.settings import get_settings
from rag_store.mcp.server import build_server


def _hosts(values: list[str]) -> list[str]:
    hosts = []
    for value in values:
        hosts.append(value if value.endswith(":*") or ":" in value else f"{value}:*")
    return hosts


def main() -> None:
    install_offline_environment()
    settings = get_settings()
    configure_logging(settings.log_level)
    runtime = Runtime.create(settings)
    server = build_server(runtime)
    from starlette.responses import JSONResponse, Response

    from rag_store.monitoring import metrics

    def metrics_route(_request):
        body, content_type = metrics.render()
        return Response(content=body, media_type=content_type)

    def health_route(_request):
        return JSONResponse({"status": "ok"})

    app = server.streamable_http_app(
        streamable_http_path=settings.mcp.path,
        json_response=True,
        stateless_http=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=settings.mcp.protect_dns_rebinding,
            allowed_hosts=_hosts(settings.mcp.host_list()),
            allowed_origins=settings.mcp.origin_list(),
        ),
    )
    app.router.add_route("/healthz", health_route, methods=["GET"])
    app.router.add_route("/readyz", health_route, methods=["GET"])
    app.router.add_route("/metrics", metrics_route, methods=["GET"])
    uvicorn.run(app, host=settings.http.host, port=settings.http.port, log_level=settings.log_level.lower())


if __name__ == "__main__":
    main()
