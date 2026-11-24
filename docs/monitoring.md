# Monitoring

`/metrics` is Prometheus text. The dashboard and rules in `monitoring/` use the metrics the process actually registers: search requests and latency, degraded searches, job states, conversion outcomes, embedding failures, Docling model readiness, scanner leadership, database connectivity, and free bytes on the mounted document roots.

They do not chart per-user or per-filename series. PostgreSQL WAL and TOAST size are not exported by this application; use the existing database exporter for those.
