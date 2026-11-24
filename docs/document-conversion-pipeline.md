# Pipeline

1. The file API stages the upload and publishes it with `os.replace`, a manifest, and a `PENDING_DB` marker.
2. A convert job is committed with the document version.
3. A worker parses outside any database transaction.
4. Structured rows and the next chunk job commit together. The convert job ends as `conversion_completed`.
5. Chunking and embedding run outside the publish transaction.
6. The publish transaction inserts chunks and vectors, points `active_version_id` at the new version, and deletes chunks from older versions.

A failed reindex leaves the previous `active_version_id` in place.
