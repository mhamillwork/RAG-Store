# Test results

Recorded while building this repository. The database was local PostgreSQL 16 with pgvector 0.6.0. The embedding provider was `deterministic-test`, which production rejects.

Passed:

- `tests/unit/test_core.py` path rejection, table chunking, rank fusion, language codes, production configuration rejection, dimension rejection.
- `tests/docling/test_mapper.py` OCR and pipeline mapping.
- `tests/integration/test_ingestion_isolation.py` local upload, global upload, ordinary-user GLOBAL write denied, keyword and hybrid search, second-user 404, second-user search does not return the first user's chunk.
- `src/frontend` `npm run build`.
- `helm lint helm-chart` and the template renders listed in `implementation-plan.md`.
- `ruff check src tests`.

Skipped, with a reason:

- `tests/ocr/test_requires_models.py` because the Docling package is not installed.
- `tests/concurrency/test_requires_database.py` is an explicit skip. Concurrent claiming was not load-tested.

Not run:

- A real Docling conversion, OCR accuracy, Tesseract, image builds, a Kubernetes install, Playwright against a browser, Nomic, Granite, and any capacity test.

Those gaps are open work on the isolated network, not successful results.
