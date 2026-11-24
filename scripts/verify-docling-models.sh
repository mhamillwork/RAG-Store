#!/usr/bin/env bash
# Confirm a model directory is non-empty. This does not score OCR accuracy.
# Usage: scripts/verify-docling-models.sh /models/docling
set -euo pipefail
path=${1:-}
[[ -d "$path" ]] || { echo "model directory does not exist: ${path:-<missing>}" >&2; exit 1; }
count=$(find "$path" -type f | wc -l)
[[ "$count" -gt 0 ]] || { echo "model directory is empty: $path" >&2; exit 1; }
echo "$count files under $path"
