#!/usr/bin/env bash
# Package the Helm chart. Usage: scripts/package-chart.sh
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
command -v helm >/dev/null || { echo "helm is required" >&2; exit 1; }
helm lint "$root/helm-chart"
helm package "$root/helm-chart" -d "$root/artifacts"
