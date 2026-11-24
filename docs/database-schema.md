# Schema

The Alembic revision `20261124_0001` creates the `ragstore` schema. Tables include users, sessions, API credentials, quotas, collections, folders, documents, document versions, Docling documents and segments, tables, assets, chunks, embeddings, jobs, attempts, leases, inference permits, heartbeats, audit events, upload sessions, dropbox observations, and rate buckets.

Downgrade does not drop the schema. Take a backup and drop it explicitly if a teardown is required.

Chunk `search_vector` is a generated `to_tsvector('simple', lexical_text)` column. Ranking is `ts_rank_cd`, which is not BM25.
