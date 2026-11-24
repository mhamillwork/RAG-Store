# Embedding migration

Changing the model name inserts or selects a row in `embedding_models` and marks the others inactive. Existing chunks keep their vectors until a reindex writes a new version. Search uses the active model id, so old vectors are not compared with a new query vector.

A dimension other than 768 requires a schema migration. The application will not start with a mismatched dimension.

Reindex does not repeat OCR when the structured document is still stored.
