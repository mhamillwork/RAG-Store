#!/usr/bin/env bash
# Upload a file or directory into the caller's LOCAL knowledge.
# Usage: scripts/upload-local.sh ./notes projects
set -euo pipefail
path=${1:-}
collection=${2:-}
[[ -n "$path" && -n "$collection" ]] || { echo "usage: $0 <path> <collection>" >&2; exit 2; }
command -v ragctl >/dev/null || { echo "ragctl is not on PATH" >&2; exit 1; }
ragctl upload "$path" --scope local --collection "$collection" --recursive
