#!/usr/bin/env bash
# Render the chart and check required Kubernetes objects.
# Usage: scripts/validate-deployment.sh [values-file]
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
values=${1:-$root/helm-deploy/rag-store-values.yaml}
command -v helm >/dev/null || { echo "helm is required" >&2; exit 1; }
helm lint "$root/helm-chart"
out=$(helm template rag-store "$root/helm-chart" -f "$values" --namespace rag-store)
echo "$out" | grep -q "kind: Deployment" || { echo "no Deployment rendered" >&2; exit 1; }
echo "$out" | grep -q "rag-store-docling" || { echo "Docling worker image missing" >&2; exit 1; }
echo "$out" | grep -q "rag-store-gui" || { echo "GUI image missing" >&2; exit 1; }
if echo "$out" | grep -q "nvidia.com/gpu"; then
  echo "a rendered manifest requests a GPU" >&2
  exit 1
fi
echo "rendered chart does not request GPUs and includes the GUI and Docling images"
