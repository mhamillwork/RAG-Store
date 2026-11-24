# pgvector

The embedding column is `vector(768)` with an HNSW index using cosine distance. Search tries `hnsw.iterative_scan` and ignores the error on pgvector 0.6.0, which does not have that setting. If the approximate result is short, the query repeats with index scans disabled for that statement.

Do not compare vectors from two models or two dimensions. The publish path keeps one active embedding model and records its name.
