# Maintenance mode

Set `MAINTENANCE_MODE=true` or `maintenance.enabled=true`.

Workers, the scanner, and Docling scale to zero. Search, files, MCP, and the GUI stay up unless their own `pauseInMaintenance` is changed. Autoscalers are not rendered. The migration job is skipped unless `maintenance.runMigration` is true.

Queued jobs remain in PostgreSQL. When maintenance ends, expired leases return to `retry_pending` and workers claim them. A conversion that already committed is not repeated; the chunk job runs next.

The mode does not stop PostgreSQL, Longhorn, Cilium, cert-manager, or vLLM.
