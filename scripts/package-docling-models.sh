#!/usr/bin/env bash
# Tar the prepared artifact directory and write a SHA-256 manifest.
# Usage: scripts/package-docling-models.sh /path/to/artifacts /path/to/output.tar
set -euo pipefail
src=${1:-}
out=${2:-}
[[ -d "$src" && -n "$out" ]] || { echo "usage: $0 <artifacts-dir> <output.tar>" >&2; exit 2; }
[[ -n "$(ls -A "$src")" ]] || { echo "artifact directory is empty" >&2; exit 1; }
tar -C "$(dirname "$src")" -cf "$out" "$(basename "$src")"
sha256sum "$out" | tee "$out.sha256"
