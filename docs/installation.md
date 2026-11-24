# Installation

1. Confirm pgvector is available: `SELECT * FROM pg_available_extensions WHERE name = 'vector';`
2. Create the database and the four roles in `docs/postgresql-setup.md`.
3. Install the application images in the internal registry.
4. Mount Docling artifacts read-only. See `docling-offline-installation.md`.
5. Create Secret `rag-store-credentials` with `migrator-url`, `search-url`, `files-url`, `worker-url`, and `jwt-secret`.
6. Label worker nodes: `kubectl label node <name> rag-worker=enabled`.
7. Set the empty embedding and reranking URLs in `helm-deploy/rag-store-values.yaml` to the internal services.
8. From `helm-deploy`, run `helmfile diff` and then `helmfile apply`.

The release does not install PostgreSQL, Longhorn, vLLM, or an identity provider.

Maintenance mode is `MAINTENANCE_MODE=true helmfile apply`. It scales the scanner, ingestion workers, and Docling workers to zero and skips the migration job unless `maintenance.runMigration` is true. PVCs are kept.
