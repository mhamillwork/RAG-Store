# Backup and restore

Back up the `ragstore` schema with the existing PostgreSQL backup. It holds ownership, Docling JSON, chunks, embeddings, and jobs. Back up the GLOBAL, LOCAL, and model volumes with Longhorn. Replication is not a backup.

`scripts/backup.sh` and `scripts/restore.sh` exit 1. They do not know the site's backup credentials and will not pretend a backup ran.

After a restore, expired leases should be allowed to time out or be moved to `retry_pending` before workers start. Compare source checksums to the files on the restored volume. Original files alone do not restore collection ownership.

No recovery-point objective is stated. It is the objective of the existing PostgreSQL and Longhorn jobs.
