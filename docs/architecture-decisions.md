# Architecture decisions

## PostgreSQL instead of another vector database

The cluster already runs PostgreSQL. pgvector HNSW and full-text search cover the retrieval modes without a new database service. A search backend can be replaced later behind `SearchService`; the current implementation is SQL.

## One database, row-level security

Users and collections are rows, not databases. Policies use transaction-local `app.user_id` and `app.role`. The worker role is recognized with `current_user`, so an API role cannot become a worker by setting a variable. The migration role owns the tables and is the only role that bypasses row-level security.

## Jobs in PostgreSQL

`FOR UPDATE SKIP LOCKED` claims work. A fencing token stops an expired worker from publishing over a newer attempt. Execution is at-least-once. Chunk inserts are replaced per version, so a retry does not leave two searchable copies. The previous searchable version stays active until the new version's publish transaction commits.

## Docling on CPU, models offline

Docling workers request no GPU. `HF_HUB_OFFLINE` and related variables are set at process start. Missing artifacts fail readiness. The application does not download models.

## OCR honesty

Automatic mode does not claim that full-page OCR ran. The OCR-applied flag is true for forced OCR and for image inputs. Layout and table recognition happen inside one Docling call; they are not separate job states.

## Test embeddings

`deterministic-test` builds a token-overlap vector. Settings validation rejects it when `RAG_STORE_ENVIRONMENT=production`.

## OIDC

Issuer, client id, and client secret are configuration fields. The browser redirect flow is not implemented. Local passwords and `rag_` API keys are the working authenticators.

## Fixed vector width

`chunk_embeddings.embedding` is `vector(768)`. Startup refuses any other dimension.
