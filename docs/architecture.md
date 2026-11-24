# Architecture

RAG Store is one Python package deployed as several processes. They share configuration, database models, authorization, and the document catalog. They do not each keep a vector index.

| Process | Role |
|---|---|
| rag-store-api | Semantic, keyword, and hybrid search |
| rag-store-files | Uploads, folders, collections, jobs, administration |
| rag-store-worker | Lightweight parsing, chunking, embeddings |
| rag-store-docling | Docling conversion and OCR |
| rag-store-scanner | Dropbox reconciliation and leader lease |
| rag-store-mcp | Streamable HTTP tools |
| rag-store-gui | Static React application and same-origin proxy |

PostgreSQL is the authority for structured knowledge and the job queue. Longhorn is the authority for original bytes. A search replica does not mount the document volumes.

GLOBAL reads are open to every authenticated user. GLOBAL writes require an administrator. LOCAL rows are visible only to their owner. Administrators do not receive ordinary access to another user's LOCAL documents. Service accounts are GLOBAL-only.

The embedding dimension stored in the schema is 768. A different dimension is a migration, not a setting change.
