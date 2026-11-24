# Air-gapped installation

Production pods must not download Python packages, npm packages, models, tokenizers, OCR language data, fonts, or container images.

Prepare on a connected host, then transfer:

- The seven container images, or the base images `python:3.12.12-slim-bookworm`, `node:22.21.0-bookworm-slim`, and `nginxinc/nginx-unprivileged:1.27.4-alpine` plus a wheelhouse.
- `pgvector/pgvector:0.8.0-pg16` if Compose is used.
- The pinned Python requirements, including `docling==2.152.0` for the Docling image and Tesseract English data.
- The npm lockfile packages under `src/frontend`.
- Docling layout, table, and RapidOCR artifacts produced by `docling-tools models download` from that Docling release.
- A local tokenizer file for the embedding model when `tokenizer_required` is true.
- The chart package for `oci://artifactory.tahaa.local/tahaa-helm-local/rag-store`.

`scripts/download-docling-models.sh` refuses to run unless `RAG_STORE_ALLOW_MODEL_DOWNLOAD=1`.
