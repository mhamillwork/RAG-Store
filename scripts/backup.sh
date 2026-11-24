#!/usr/bin/env bash
# Record the backup commands an administrator must run with the existing tools.
# This script does not contact a cluster and does not report success.
set -euo pipefail
cat <<'EOF'
PostgreSQL backup must be taken with the existing database backup job.
It has to include the ragstore schema: documents, Docling JSON, chunks, embeddings, jobs, and audit events.

Longhorn backups must cover the GLOBAL PVC, the LOCAL PVC, and the model PVC when one is used.
Replication is not a backup.

This repository does not know the backup schedule or credentials, so it will not run a backup.
EOF
exit 1
