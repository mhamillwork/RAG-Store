#!/usr/bin/env bash
# Build every RAG Store image from the repository root.
# Usage: scripts/build-images.sh [--tag TAG] [--python-image IMAGE]
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
tag=${TAG:-1.0.0}
python_image=${PYTHON_IMAGE:-python:3.12.12-slim-bookworm}
while [[ $# -gt 0 ]]; do
  case "$1" in
    --tag) tag=$2; shift 2 ;;
    --python-image) python_image=$2; shift 2 ;;
    -h|--help) sed -n '2,4p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
command -v docker >/dev/null || { echo "docker is required" >&2; exit 1; }
cd "$root"
images=(rag-store-api rag-store-worker rag-store-scanner rag-store-mcp rag-store-files rag-store-gui rag-store-docling)
for image in "${images[@]}"; do
  echo "building $image:$tag"
  if [[ "$image" == "rag-store-gui" ]]; then
    docker build -f "dockerfile/Dockerfile.$image" -t "$image:$tag" .
  else
    docker build -f "dockerfile/Dockerfile.$image" --build-arg "PYTHON_IMAGE=$python_image" -t "$image:$tag" .
  fi
done
