#!/usr/bin/env bash
# Prepare Docling artifacts on a connected system. Do not run this in production.
# Usage: scripts/download-docling-models.sh /path/to/artifacts
set -euo pipefail
dest=${1:-}
[[ -n "$dest" ]] || { echo "usage: $0 <destination-directory>" >&2; exit 2; }
if [[ "${RAG_STORE_ALLOW_MODEL_DOWNLOAD:-}" != "1" ]]; then
  echo "Refusing to download models. Set RAG_STORE_ALLOW_MODEL_DOWNLOAD=1 on a connected preparation host." >&2
  exit 1
fi
command -v docling-tools >/dev/null || { echo "docling-tools from the pinned Docling release is not installed." >&2; exit 1; }
mkdir -p "$dest"
DOCLING_ARTIFACTS_PATH="$dest" docling-tools models download
echo "Verify the artifact list against the pinned Docling release before transferring $dest."
