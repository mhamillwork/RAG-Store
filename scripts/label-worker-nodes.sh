#!/usr/bin/env bash
# Label nodes that may run RAG Store.
# Usage: scripts/label-worker-nodes.sh node-a node-b
# Does not invent node names. Pass the nodes an administrator has chosen.
set -euo pipefail
[[ $# -gt 0 ]] || { echo "usage: $0 <node> [node...]" >&2; exit 2; }
command -v kubectl >/dev/null || { echo "kubectl is required" >&2; exit 1; }
for node in "$@"; do
  kubectl label node "$node" rag-worker=enabled --overwrite
done
