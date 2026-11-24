#!/usr/bin/env bash
# Retag and push images to the internal registry.
# Usage: REGISTRY=artifactory.example/ai-services scripts/push-images.sh --tag 1.0.0
set -euo pipefail
tag=${TAG:-1.0.0}
registry=${REGISTRY:-}
while [[ $# -gt 0 ]]; do
  case "$1" in
    --tag) tag=$2; shift 2 ;;
    --registry) registry=$2; shift 2 ;;
    -h|--help) sed -n '2,3p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
[[ -n "$registry" ]] || { echo "Set REGISTRY or --registry. No default registry is assumed." >&2; exit 1; }
command -v docker >/dev/null || { echo "docker is required" >&2; exit 1; }
for image in rag-store-api rag-store-worker rag-store-scanner rag-store-mcp rag-store-files rag-store-gui rag-store-docling; do
  docker tag "$image:$tag" "$registry/$image:$tag"
  docker push "$registry/$image:$tag"
done
