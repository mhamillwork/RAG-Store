# API

Interactive OpenAPI is served by FastAPI at `/docs` on the file and search processes.

| Method | Path | Process |
|---|---|---|
| POST | `/api/v1/auth/login` | files |
| POST | `/api/v1/auth/refresh` | files |
| GET | `/api/v1/users/me` | files |
| GET | `/api/v1/users/me/quota` | files |
| POST | `/api/v1/search` | search |
| GET/POST | `/api/v1/collections` | files |
| GET | `/api/v1/collections/{id}/listing` | files |
| POST | `/api/v1/documents/upload` | files |
| POST | `/api/v1/uploads` | files |
| PUT | `/api/v1/uploads/{id}?offset=` | files |
| POST | `/api/v1/uploads/{id}/complete` | files |
| GET | `/api/v1/documents/{id}` | files |
| GET | `/api/v1/documents/{id}/download` | files |
| GET | `/api/v1/documents/{id}/markdown` | files |
| GET | `/api/v1/documents/{id}/text` | files |
| GET | `/api/v1/documents/{id}/docling` | files |
| GET | `/api/v1/documents/{id}/tables` | files |
| GET | `/api/v1/documents/{id}/chunks` | files |
| PATCH/DELETE | `/api/v1/documents/{id}` | files |
| POST | `/api/v1/documents/{id}/reindex` | files |
| POST | `/api/v1/documents/{id}/reprocess` | files |
| GET/POST | `/api/v1/jobs` and `/api/v1/jobs/{id}/retry` | files |
| GET | `/api/v1/admin/system-status` | files |
| GET | `/healthz`, `/readyz`, `/metrics` | each process |

Errors use `{"error": {"code", "message", "details"}}`. Unimplemented behavior is not returned as success.
