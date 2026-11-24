# Configuration

Environment variables use the prefix `RAG_STORE_` and `__` between sections. Example: `RAG_STORE_EMBEDDING__BASE_URL`.

`MAINTENANCE_MODE=true` forces maintenance even when the YAML flag is false.

Production startup fails when:

- the JWT secret is shorter than 32 characters or is a known placeholder
- the embedding dimension is not 768
- Docling or OCR is disabled
- model downloads or remote Docling services are enabled
- the embedding or reranking provider is a test double
- a required tokenizer path is empty

Helm values map onto these variables in `helm-chart/templates/configmap.yaml`. Secrets are references, not literals.
