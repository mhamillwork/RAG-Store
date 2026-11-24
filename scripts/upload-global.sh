#!/usr/bin/env bash
# Upload a file or directory into GLOBAL knowledge with ragctl.
# Usage: RAGCTL_FILES_URL=https://rag-store.example RAGCTL_API_KEY=... scripts/upload-global.sh ./docs technical
set -euo pipefail
path=${1:-}
collection=${2:-}
[[ -n "$path" && -n "$collection" ]] || { echo "usage: $0 <path> <collection>" >&2; exit 2; }
command -v ragctl >/dev/null || { echo "ragctl is not on PATH" >&2; exit 1; }
ragctl upload "$path" --scope global --collection "$collection" --recursive
