#!/usr/bin/env bash
# Push the packaged chart to an OCI registry.
# Usage: CHART_REPO=oci://artifactory.example/tahaa-helm-local scripts/push-chart.sh
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
repo=${CHART_REPO:-}
[[ -n "$repo" ]] || { echo "Set CHART_REPO. No default Helm repository is assumed." >&2; exit 1; }
chart=$(ls "$root"/artifacts/rag-store-*.tgz | tail -n 1)
[[ -n "$chart" ]] || { echo "No packaged chart in artifacts/. Run scripts/package-chart.sh first." >&2; exit 1; }
helm push "$chart" "$repo"
