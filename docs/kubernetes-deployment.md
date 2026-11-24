# Kubernetes deployment

Default replicas are 3 search, 6 ingestion, 2 scanner, 3 MCP, 3 file, 3 GUI, and 3 Docling. Those counts are the starting values in the chart, not measurements.

Each Deployment has a topology spread constraint with `ScheduleAnyway`. That prefers different nodes and does not guarantee it. PodDisruptionBudgets do not survive a node failure.

Database migrations run as a pre-install and pre-upgrade Job using the migrator URL. They do not run while maintenance mode is on unless `maintenance.runMigration` is true.

The optional storage utility pod is off by default. It mounts both document PVCs and is an administrative back door, outside application authorization.
