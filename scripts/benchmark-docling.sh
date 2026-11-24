#!/usr/bin/env bash
# Placeholder entry point that refuses to invent timings.
# A real benchmark needs the isolated cluster, the model PVC, and a document corpus.
set -euo pipefail
echo "No Docling benchmark has been run in this environment." >&2
echo "Measure pages/second on the general-purpose workers after the model artifacts are mounted." >&2
exit 1
