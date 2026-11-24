#!/usr/bin/env bash
# Ask the file API to reindex one document. Reindex reuses stored structure.
# Usage: scripts/reindex.sh <document-id>
set -euo pipefail
id=${1:-}
[[ -n "$id" ]] || { echo "usage: $0 <document-id>" >&2; exit 2; }
command -v ragctl >/dev/null || { echo "ragctl is not on PATH" >&2; exit 1; }
ragctl documents reindex "$id"
