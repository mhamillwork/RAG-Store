#!/usr/bin/env bash
# Refuse an unconfigured restore. Restoring the wrong snapshot would hide data loss.
set -euo pipefail
echo "Restore is not automated. Follow docs/backup-restore.md and confirm the PostgreSQL and Longhorn snapshots before any write." >&2
exit 1
