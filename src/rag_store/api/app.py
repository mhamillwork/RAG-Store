"""FastAPI application factory."""

from __future__ import annotations

import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from rag_store.api.routes_admin import router as admin_router
from rag_store.api.routes_auth import router as auth_router
from rag_store.api.routes_files import router as files_router
from rag_store.api.routes_health import router as health_router
from rag_store.api.routes_search import router as search_router
from rag_store.api.runtime import Runtime
from rag_store.common.errors import RagStoreError
from rag_store.common.logging import get_logger
from rag_store.config.settings import Settings

log = get_logger("api")


def create_app(settings: Settings, *, files: bool, search: bool) -> FastAPI:
    runtime = Runtime.create(settings)
    app = FastAPI(title=settings.instance_name, version="1.0.0", root_path=settings.http.root_path)
    app.state.runtime = runtime

    @app.middleware("http")
    async def correlation(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        return response

    @app.exception_handler(RagStoreError)
    async def rag_error(_request: Request, exc: RagStoreError):
        return JSONResponse(status_code=exc.status_code, content=exc.to_dict())

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "validation_error", "message": "The request is not valid.", "details": {"errors": exc.errors()}}},
        )

    app.include_router(health_router)
    if files:
        app.include_router(auth_router)
        app.include_router(files_router)
        app.include_router(admin_router)
    if search:
        app.include_router(search_router)
    return app
