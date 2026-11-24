"""Upload, index, search, and cross-user isolation against local PostgreSQL."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from rag_store.api.app import create_app
from rag_store.config.settings import (
    AuthSettings,
    ChunkingSettings,
    DatabaseSettings,
    EmbeddingSettings,
    Settings,
    StorageSettings,
)
from rag_store.database.migrate import upgrade
from rag_store.database.session import build_engine, build_session_factory, session_scope
from rag_store.workers.loop import Worker

MIGRATOR = "postgresql+psycopg://ragstore_migrator:migrator@127.0.0.1:5432/ragstore"
FILES = "postgresql+psycopg://ragstore_files:files@127.0.0.1:5432/ragstore"
SEARCH = "postgresql+psycopg://ragstore_search:search@127.0.0.1:5432/ragstore"
WORKER = "postgresql+psycopg://ragstore_worker:worker@127.0.0.1:5432/ragstore"
SECRET = "integration-test-jwt-secret-value-32"


def _settings(url: str, component: str, root: Path) -> Settings:
    settings = Settings(
        environment="test",
        component=component,
        database=DatabaseSettings(url=url),
        auth=AuthSettings(jwt_secret=SECRET, bootstrap_admin_username="admin", bootstrap_admin_password="administrator-pass"),
        storage=StorageSettings(global_root=str(root / "global"), local_root=str(root / "local"), stability_seconds=0),
        embedding=EmbeddingSettings(provider="deterministic-test", model="deterministic-test", dimensions=768),
        chunking=ChunkingSettings(tokenizer_mode="basic", tokenizer_required=False, max_tokens=128, overlap_tokens=16),
    )
    settings.validate_runtime()
    return settings


@pytest.fixture(scope="module")
def migrated():
    settings = Settings(environment="test", database=DatabaseSettings(url=MIGRATOR), auth=AuthSettings(jwt_secret=SECRET), embedding=EmbeddingSettings(provider="deterministic-test", model="deterministic-test", dimensions=768), chunking=ChunkingSettings(tokenizer_mode="basic", tokenizer_required=False))
    try:
        engine = build_engine(settings)
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.skip(f"PostgreSQL test roles are not available: {exc.__class__.__name__}")
    with engine.connect() as connection:
        connection.execute(text("DROP SCHEMA IF EXISTS ragstore CASCADE"))
        connection.commit()
    upgrade(MIGRATOR)
    yield


def test_local_isolation_and_global_search(migrated, tmp_path: Path):
    files_settings = _settings(FILES, "files", tmp_path)
    search_settings = _settings(SEARCH, "search", tmp_path)
    worker_settings = _settings(WORKER, "worker", tmp_path)
    files = TestClient(create_app(files_settings, files=True, search=False))
    search = TestClient(create_app(search_settings, files=False, search=True))

    sessions = build_session_factory(build_engine(files_settings))
    with session_scope(sessions) as db:
        from rag_store.auth.service import bootstrap_admin

        bootstrap_admin(db, files_settings)

    login = files.post("/api/v1/auth/login", json={"username": "admin", "password": "administrator-pass"})
    assert login.status_code == 200, login.text
    admin_token = login.json()["access_token"]
    admin = {"Authorization": f"Bearer {admin_token}"}

    created = files.post("/api/v1/admin/users", headers=admin, json={"username": "ada", "password": "local-user-password", "role": "user"})
    assert created.status_code == 201, created.text
    other = files.post("/api/v1/admin/users", headers=admin, json={"username": "bea", "password": "other-user-password", "role": "user"})
    assert other.status_code == 201, other.text

    ada = files.post("/api/v1/auth/login", json={"username": "ada", "password": "local-user-password"})
    bea = files.post("/api/v1/auth/login", json={"username": "bea", "password": "other-user-password"})
    ada_headers = {"Authorization": f"Bearer {ada.json()['access_token']}"}
    bea_headers = {"Authorization": f"Bearer {bea.json()['access_token']}"}

    upload = files.post(
        "/api/v1/documents/upload",
        headers=ada_headers,
        data={"scope": "local", "collection": "documents", "relative_path": ""},
        files={"file": ("notes.txt", io.BytesIO(b"Cilium multicast uses BPF maps for group membership.\n"), "text/plain")},
    )
    assert upload.status_code == 201, upload.text
    document_id = upload.json()["document"]["id"]

    global_upload = files.post(
        "/api/v1/documents/upload",
        headers=admin,
        data={"scope": "global", "collection": "general"},
        files={"file": ("standard.txt", io.BytesIO(b"The interface control document defines field MSG_ID.\n"), "text/plain")},
    )
    assert global_upload.status_code == 201, global_upload.text

    denied = files.post(
        "/api/v1/documents/upload",
        headers=ada_headers,
        data={"scope": "global", "collection": "general"},
        files={"file": ("nope.txt", io.BytesIO(b"should not land\n"), "text/plain")},
    )
    assert denied.status_code == 403

    worker = Worker(worker_settings, build_session_factory(build_engine(worker_settings)), kind="ingestion")
    assert worker.run_once()
    assert worker.run_once()
    assert worker.run_once()
    assert worker.run_once()

    hidden = files.get(f"/api/v1/documents/{document_id}", headers=bea_headers)
    assert hidden.status_code == 404

    ada_search = search.post("/api/v1/search", headers=ada_headers, json={"query": "Cilium multicast", "mode": "keyword", "scope": "local"})
    assert ada_search.status_code == 200, ada_search.text
    assert any(hit["document_id"] == document_id for hit in ada_search.json()["hits"])

    bea_search = search.post("/api/v1/search", headers=bea_headers, json={"query": "Cilium multicast", "mode": "keyword", "scope": "all"})
    assert bea_search.status_code == 200, bea_search.text
    assert all(hit["document_id"] != document_id for hit in bea_search.json()["hits"])

    global_hit = search.post("/api/v1/search", headers=bea_headers, json={"query": "MSG_ID", "mode": "hybrid", "scope": "global"})
    assert global_hit.status_code == 200, global_hit.text
    assert global_hit.json()["hits"]
    assert global_hit.json()["hits"][0]["source_reference"].startswith("/api/v1/documents/")

    ready = search.get("/readyz")
    assert ready.status_code == 200


def test_pending_publication_is_recovered(migrated, tmp_path: Path):
    from uuid import uuid4

    from rag_store.scanner.service import Scanner
    from rag_store.storage.layout import PENDING_MARKER, StorageLayout

    files_settings = _settings(FILES, "files", tmp_path)
    worker_settings = _settings(WORKER, "worker", tmp_path)
    files = TestClient(create_app(files_settings, files=True, search=False))
    login = files.post("/api/v1/auth/login", json={"username": "admin", "password": "administrator-pass"})
    assert login.status_code == 200, login.text
    admin = {"Authorization": f"Bearer {login.json()['access_token']}"}
    listed = files.get("/api/v1/collections", headers=admin)
    assert listed.status_code == 200, listed.text
    general = next(row for row in listed.json()["collections"] if row["scope"] == "global" and row["name"] == "general")
    document_id = uuid4()
    version_id = uuid4()
    layout = StorageLayout(worker_settings)
    relative, _checksum, _size = layout.write_original(
        "global",
        "",
        document_id,
        version_id,
        "recovered.txt",
        io.BytesIO(b"recovered publication\n"),
        {
            "document_id": str(document_id),
            "version_id": str(version_id),
            "scope": "global",
            "owner_id": None,
            "storage_key": "",
            "collection_id": general["id"],
            "relative_path": "recovered.txt",
            "filename": "recovered.txt",
        },
    )
    marker = layout.absolute("global", "", relative).parent / PENDING_MARKER
    assert marker.is_file()

    scanner = Scanner(worker_settings, build_session_factory(build_engine(worker_settings)))
    assert scanner.run_once() is True
    assert not marker.exists()
    fetched = files.get(f"/api/v1/documents/{document_id}", headers=admin)
    assert fetched.status_code == 200, fetched.text
    jobs = files.get(f"/api/v1/jobs?document_id={document_id}", headers=admin)
    assert jobs.status_code == 200, jobs.text
    assert jobs.json()["jobs"]
    assert jobs.json()["jobs"][0]["state"] == "queued"
