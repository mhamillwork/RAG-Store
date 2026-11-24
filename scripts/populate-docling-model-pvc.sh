#!/usr/bin/env bash
# Copy a local artifact directory into the model PVC through the utility pod.
# Usage: NAMESPACE=rag-store POD=<utility-pod> scripts/populate-docling-model-pvc.sh ./models/docling
set -euo pipefail
src=${1:-}
namespace=${NAMESPACE:-rag-store}
pod=${POD:-}
[[ -d "$src" && -n "$pod" ]] || { echo "usage: POD=<storage-utility-pod> $0 <local-artifacts>" >&2; exit 2; }
command -v kubectl >/dev/null || { echo "kubectl is required" >&2; exit 1; }
tar -C "$src" -cf - . | kubectl -n "$namespace" exec -i "$pod" -- tar -C /models/docling -xf -
