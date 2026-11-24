# Implementation status

The repository contains the six runtime processes, the GUI, the chart, Compose, CI, and tests described in the requirements. It is not a design-only tree.

Completed in this workspace:

- Schema, migrations, row-level security, and role grants.
- Upload, resumable upload, collections, folders, jobs, reindex, and reprocess.
- Lightweight text conversion, chunking, deterministic test embeddings, keyword and hybrid search.
- Multi-user isolation test against local PostgreSQL.
- Helm chart rendered for the default values, the production values, maintenance mode, existing PVCs, autoscaling, KEDA, and a Gateway route.

Not executed here:

- Docling conversion and OCR on real documents.
- Calls to Nomic or Granite.
- Image builds and a cluster install.
- Load tests. No performance numbers are claimed.

See `test-results.md`.
