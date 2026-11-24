# High availability

Search, files, MCP, and the GUI are stateless and have multiple replicas. Workers claim jobs with skip-locked and fencing. The scanner fails over when its lease expires.

Application replicas do not make PostgreSQL, Longhorn, or vLLM highly available. A PostgreSQL outage stops search and ingestion. A document-volume outage stops downloads and new conversion that needs the file; already indexed chunks remain searchable while PostgreSQL and the query embedder are up. An embedding outage degrades hybrid search to keyword when fallback is enabled, and the response says so.

No recovery-time number is claimed.
