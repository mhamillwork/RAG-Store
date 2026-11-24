"""Collections, documents, folders, jobs, and resumable uploads."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from rag_store.api.deps import actor, db_session, runtime
from rag_store.api.runtime import Runtime
from rag_store.common.errors import ValidationFailed
from rag_store.database.session import Actor

router = APIRouter(prefix="/api/v1")


class CollectionBody(BaseModel):
    name: str
    scope: str
    description: str = ""


class CollectionPatch(BaseModel):
    description: str | None = None


class FolderBody(BaseModel):
    path: str


class DocumentPatch(BaseModel):
    filename: str | None = None
    relative_path: str | None = None
    collection_id: str | None = None
    tags: list[str] | None = None
    metadata: dict | None = None


class ReprocessBody(BaseModel):
    ocr_mode: str | None = None
    parser: str | None = None


class UploadStart(BaseModel):
    scope: str
    collection: str
    relative_path: str = ""
    filename: str
    expected_size: int | None = None
    expected_checksum: str = ""
    idempotency_key: str = ""


@router.get("/collections")
def list_collections(scope: str | None = None, current: Actor = Depends(actor), session: Session = Depends(db_session), app: Runtime = Depends(runtime)) -> dict:
    rows = app.catalog.list_collections(session, current, scope)
    from rag_store.ingestion.catalog import _collection_dict

    return {"collections": [_collection_dict(row) for row in rows]}


@router.post("/collections", status_code=201)
def create_collection(body: CollectionBody, current: Actor = Depends(actor), session: Session = Depends(db_session), app: Runtime = Depends(runtime)) -> dict:
    from rag_store.ingestion.catalog import _collection_dict

    row = app.catalog.create_collection(session, current, scope=body.scope, name=body.name, description=body.description)
    return _collection_dict(row)


@router.patch("/collections/{collection_id}")
def patch_collection(collection_id: UUID, body: CollectionPatch, current: Actor = Depends(actor), session: Session = Depends(db_session), app: Runtime = Depends(runtime)) -> dict:
    from rag_store.ingestion.catalog import _collection_dict, _require_write

    collection = app.catalog._collection(session, collection_id)
    _require_write(current, collection.scope)
    if body.description is not None:
        collection.description = body.description[:2000]
    return _collection_dict(collection)


@router.delete("/collections/{collection_id}")
def delete_collection(collection_id: UUID, current: Actor = Depends(actor), session: Session = Depends(db_session), app: Runtime = Depends(runtime)) -> dict:
    app.catalog.delete_collection(session, current, collection_id)
    return {"status": "deleted"}


@router.get("/collections/{collection_id}/listing")
def listing(collection_id: UUID, path: str = "", current: Actor = Depends(actor), session: Session = Depends(db_session), app: Runtime = Depends(runtime)) -> dict:
    return app.catalog.list_directory(session, current, collection_id, path)


@router.post("/collections/{collection_id}/folders", status_code=201)
def create_folder(collection_id: UUID, body: FolderBody, current: Actor = Depends(actor), session: Session = Depends(db_session), app: Runtime = Depends(runtime)) -> dict:
    from rag_store.ingestion.catalog import _folder_dict

    folder = app.catalog.create_folder(session, current, collection_id, body.path)
    return _folder_dict(folder) if folder else {"path": ""}


@router.get("/documents")
def list_documents(
    scope: str | None = None,
    collection_id: UUID | None = None,
    filename: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current: Actor = Depends(actor),
    session: Session = Depends(db_session),
    app: Runtime = Depends(runtime),
) -> dict:
    return app.catalog.list_documents(session, scope=scope, collection_id=collection_id, filename=filename, limit=limit, offset=offset)


@router.post("/documents/upload", status_code=201)
async def upload_document(
    scope: str = Form(...),
    collection: str = Form(...),
    file: UploadFile = File(...),
    relative_path: str = Form(""),
    idempotency_key: str = Form(""),
    ocr_mode: str = Form(""),
    priority: str = Form("ordinary"),
    current: Actor = Depends(actor),
    session: Session = Depends(db_session),
    app: Runtime = Depends(runtime),
) -> dict:
    if not file.filename:
        raise ValidationFailed("A filename is required.")
    result = app.catalog.upload(
        session,
        current,
        scope=scope,
        collection_name=collection,
        relative_path=relative_path,
        filename=file.filename,
        source=file.file,
        idempotency_key=idempotency_key or None,
        priority=priority,
        ocr_mode=ocr_mode or None,
    )
    pending = result.pop("pending", None)
    session.commit()
    app.catalog.clear_pending_after_commit(pending)
    return result


@router.post("/uploads", status_code=201)
def start_upload(body: UploadStart, current: Actor = Depends(actor), session: Session = Depends(db_session), app: Runtime = Depends(runtime)) -> dict:
    return app.catalog.begin_upload(
        session,
        current,
        scope=body.scope,
        collection_name=body.collection,
        relative_path=body.relative_path,
        filename=body.filename,
        expected_size=body.expected_size,
        expected_checksum=body.expected_checksum,
        idempotency_key=body.idempotency_key,
    )


@router.put("/uploads/{upload_id}")
async def append_upload(
    upload_id: UUID,
    request: Request,
    offset: int = Query(ge=0),
    current: Actor = Depends(actor),
    session: Session = Depends(db_session),
    app: Runtime = Depends(runtime),
) -> dict:
    data = await request.body()
    if len(data) > app.settings.storage.max_file_bytes:
        raise ValidationFailed("The upload chunk is larger than the configured maximum file size.")
    return app.catalog.append_upload(session, current, upload_id, offset, data)


@router.post("/uploads/{upload_id}/complete")
def complete_upload(upload_id: UUID, current: Actor = Depends(actor), session: Session = Depends(db_session), app: Runtime = Depends(runtime)) -> dict:
    result = app.catalog.complete_upload(session, current, upload_id)
    pending = result.pop("pending", None) if isinstance(result, dict) else None
    session.commit()
    app.catalog.clear_pending_after_commit(pending)
    return result


@router.get("/documents/{document_id}")
def get_document(document_id: UUID, current: Actor = Depends(actor), session: Session = Depends(db_session), app: Runtime = Depends(runtime)) -> dict:
    return app.catalog.get_document(session, document_id)


@router.get("/documents/{document_id}/download")
def download_document(document_id: UUID, current: Actor = Depends(actor), session: Session = Depends(db_session), app: Runtime = Depends(runtime)):
    path, filename = app.catalog.original_file(session, document_id)
    return FileResponse(path, filename=filename)


@router.get("/documents/{document_id}/versions")
def document_versions(document_id: UUID, current: Actor = Depends(actor), session: Session = Depends(db_session), app: Runtime = Depends(runtime)) -> dict:
    return {"versions": app.catalog.document_versions(session, document_id)}


@router.get("/documents/{document_id}/markdown")
def document_markdown(document_id: UUID, current: Actor = Depends(actor), session: Session = Depends(db_session), app: Runtime = Depends(runtime)):
    return PlainTextResponse(app.catalog.document_markdown(session, document_id))


@router.get("/documents/{document_id}/text")
def document_text(document_id: UUID, current: Actor = Depends(actor), session: Session = Depends(db_session), app: Runtime = Depends(runtime)):
    return PlainTextResponse(app.catalog.document_text(session, document_id))


@router.get("/documents/{document_id}/docling")
def document_docling(
    document_id: UUID,
    include_content: bool = False,
    segment: int | None = None,
    current: Actor = Depends(actor),
    session: Session = Depends(db_session),
    app: Runtime = Depends(runtime),
) -> dict:
    return app.catalog.document_docling(session, document_id, include_content=include_content, segment=segment)


@router.get("/documents/{document_id}/tables")
def document_tables(document_id: UUID, limit: int = 50, offset: int = 0, current: Actor = Depends(actor), session: Session = Depends(db_session), app: Runtime = Depends(runtime)) -> dict:
    return app.catalog.document_tables(session, document_id, limit=limit, offset=offset)


@router.get("/documents/{document_id}/chunks")
def document_chunks(document_id: UUID, limit: int = 50, offset: int = 0, current: Actor = Depends(actor), session: Session = Depends(db_session), app: Runtime = Depends(runtime)) -> dict:
    return app.catalog.document_chunks(session, document_id, limit=limit, offset=offset)


@router.get("/documents/{document_id}/assets")
def document_assets(document_id: UUID, current: Actor = Depends(actor), session: Session = Depends(db_session), app: Runtime = Depends(runtime)) -> dict:
    return {"assets": app.catalog.list_assets(session, document_id)}


@router.get("/documents/{document_id}/assets/{asset_id}")
def download_asset(document_id: UUID, asset_id: UUID, current: Actor = Depends(actor), session: Session = Depends(db_session), app: Runtime = Depends(runtime)):
    path, mime, filename = app.catalog.asset_file(session, document_id, asset_id)
    return FileResponse(path, media_type=mime, filename=filename)


@router.patch("/documents/{document_id}")
def patch_document(document_id: UUID, body: DocumentPatch, current: Actor = Depends(actor), session: Session = Depends(db_session), app: Runtime = Depends(runtime)) -> dict:
    return app.catalog.update_document(session, current, document_id, body.model_dump(exclude_none=True))


@router.delete("/documents/{document_id}")
def delete_document(document_id: UUID, physical: bool = False, current: Actor = Depends(actor), session: Session = Depends(db_session), app: Runtime = Depends(runtime)) -> dict:
    app.catalog.delete_document(session, current, document_id, physical=physical)
    return {"status": "deleted"}


@router.post("/documents/{document_id}/reindex")
def reindex(document_id: UUID, current: Actor = Depends(actor), session: Session = Depends(db_session), app: Runtime = Depends(runtime)) -> dict:
    return app.catalog.reindex(session, current, document_id)


@router.post("/documents/{document_id}/reprocess")
def reprocess(document_id: UUID, body: ReprocessBody | None = None, current: Actor = Depends(actor), session: Session = Depends(db_session), app: Runtime = Depends(runtime)) -> dict:
    payload = body or ReprocessBody()
    return app.catalog.reprocess(session, current, document_id, ocr_mode=payload.ocr_mode, parser=payload.parser)


@router.get("/jobs")
def list_jobs(document_id: UUID | None = None, state: str | None = None, limit: int = 50, current: Actor = Depends(actor), session: Session = Depends(db_session), app: Runtime = Depends(runtime)) -> dict:
    return {"jobs": app.catalog.list_jobs(session, document_id=document_id, state=state, limit=limit)}


@router.get("/jobs/{job_id}")
def get_job(job_id: UUID, current: Actor = Depends(actor), session: Session = Depends(db_session), app: Runtime = Depends(runtime)) -> dict:
    return app.catalog.get_job(session, job_id)


@router.post("/jobs/{job_id}/retry")
def retry_job(job_id: UUID, current: Actor = Depends(actor), session: Session = Depends(db_session), app: Runtime = Depends(runtime)) -> dict:
    return app.catalog.retry(session, current, job_id)


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: UUID, current: Actor = Depends(actor), session: Session = Depends(db_session), app: Runtime = Depends(runtime)) -> dict:
    return app.catalog.cancel(session, current, job_id)


@router.get("/users/me")
def current_user(current: Actor = Depends(actor), session: Session = Depends(db_session), app: Runtime = Depends(runtime)) -> dict:
    return {"id": str(current.user_id), "username": current.username, "role": current.role, "storage_key": current.storage_key, "quota": app.catalog.quota(session, current)}


@router.get("/users/me/quota")
def current_quota(current: Actor = Depends(actor), session: Session = Depends(db_session), app: Runtime = Depends(runtime)) -> dict:
    return app.catalog.quota(session, current)
