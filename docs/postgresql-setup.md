# PostgreSQL

Create a database named `ragstore` and these roles before migrating:

- `ragstore_migrator` owns the schema and runs Alembic.
- `ragstore_search` is used by the search API and MCP.
- `ragstore_files` is used by the file API.
- `ragstore_worker` is used by workers, the scanner, and Docling. It is not `BYPASSRLS`.

The chart expects those URLs in the Secret keys `migrator-url`, `search-url`, `files-url`, and `worker-url`.

Enable the extension as a superuser. The migration refuses to start if `vector` is missing. It does not run `CREATE EXTENSION`.

```sql
SELECT name, default_version, installed_version
FROM pg_available_extensions WHERE name = 'vector';
CREATE EXTENSION IF NOT EXISTS vector;
```

RAG Store does not change the PostgreSQL topology. If that cluster has no failover, it is a single point of failure for search and ingestion.
