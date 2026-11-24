# RAG Store

RAG Store is a self-hosted knowledge system for an isolated Kubernetes cluster. PostgreSQL holds identity, Docling output, chunks, and pgvector embeddings. Longhorn holds original files. Docling and OCR run on CPU workers. A React file manager is part of the deployment.

Application, deployment, and service names come from configuration. Nothing in the source code contains a production hostname, password, or model identifier.

## Architecture

```text
GUI / ragctl / REST / MCP
        |
        v
File API and Search API  -- PostgreSQL row-level security
        |
        v
GLOBAL and LOCAL dropboxes on separate RWX volumes
        |
        v
Scanner -> durable jobs -> Docling/OCR or lightweight parser
        |
        v
Chunks and embeddings -> hybrid search -> optional reranker
```

Search reads chunks and embeddings. It does not load Docling documents for an ordinary query. Original-file download needs the document volume; indexed text does not.

## Repository

| Path | Contents |
|---|---|
| `src/rag_store` | API, workers, scanner, MCP, CLI |
| `src/frontend` | React GUI |
| `dockerfile` | One Dockerfile per image |
| `helm-chart` | Single chart |
| `helm-deploy` | Helmfile and production values |
| `scripts` | Operational scripts |
| `docs` | Operations and design notes |
| `tests` | Automated tests |
| `monitoring` | Grafana dashboard and Prometheus rules |

## Local development

PostgreSQL 16 with pgvector is required. The integration test uses these local roles, which are development passwords only:

- `ragstore_migrator` / `migrator`
- `ragstore_files` / `files`
- `ragstore_search` / `search`
- `ragstore_worker` / `worker`

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
export RAG_STORE_DATABASE__URL=postgresql+psycopg://ragstore_migrator:migrator@127.0.0.1:5432/ragstore
PYTHONPATH=src python -c 'from rag_store.database.migrate import upgrade; upgrade("postgresql+psycopg://ragstore_migrator:migrator@127.0.0.1:5432/ragstore")'
```

Create the first administrator with `RAG_STORE_AUTH__BOOTSTRAP_ADMIN_USERNAME` and `RAG_STORE_AUTH__BOOTSTRAP_ADMIN_PASSWORD` on the file API. The password must be at least 12 characters and the JWT secret at least 32.

Development and tests may set `RAG_STORE_EMBEDDING__PROVIDER=deterministic-test`. Production rejects that provider and will not invent embeddings.

The GUI development server proxies `/api/v1/search` to port 8080 and other `/api` calls to port 8081:

```bash
cd src/frontend && npm ci && npm run dev
```

## Kubernetes

```bash
kubectl label node <worker-node> rag-worker=enabled
# Create Secret rag-store-credentials with migrator-url, search-url, files-url, worker-url, jwt-secret.
cd helm-deploy
helmfile diff
helmfile apply
```

The chart does not install PostgreSQL, Longhorn, or the embedding service. See `docs/installation.md` and `docs/air-gapped-installation.md`.

## Upload and search

Administrators upload GLOBAL documents. Ordinary users upload LOCAL documents. Both can use the GUI, `ragctl`, or `POST /api/v1/documents/upload`.

```bash
ragctl upload ./technical-docs --scope global --collection technical --recursive
ragctl upload ./my-project --scope local --collection projects --recursive
ragctl search "How does Cilium multicast work?"
```

A direct copy into the dropbox is administrative. Stage the file, then move it into `/data/global/dropbox/` or `/data/local/<storage-key>/dropbox/` with `mv` on the same volume. The scanner waits until the size is stable, then ingests it. See `docs/dropbox-ingestion.md`.

Reindex reuses the stored conversion. Reprocess with `--ocr-mode force` runs OCR again. Failed jobs are retried with `ragctl jobs retry <job-id>`.

## MCP

`rag-store-mcp` serves Streamable HTTP at `/mcp`. The caller is the Authorization header. A user id inside a tool argument is ignored. Service accounts search GLOBAL only. There are no MCP tools that delete or modify documents.

## What was tested here

Unit tests cover path checks, chunking, rank fusion, OCR language codes, Docling option mapping, and production configuration rejection. An integration test on a local PostgreSQL 16 + pgvector 0.6.0 database uploaded text, indexed it with the deterministic test embedder, searched it, and showed that a second user receives 404 for the first user's document.

Docling and OCR were not executed here. The `docling` package and model weights were not installed. No GPU inference endpoint was available, so Nomic and Granite were not called. Container images were not built. Helm templates were rendered and linted. Those limits are written in `docs/test-results.md`.

## License and network

The application is intended to run without internet access. It does not phone home. Model files, Python wheels, npm packages, and base images have to be present in the internal Artifactory before a production build.
