#!/usr/bin/env bash
# Run the OCR test module. It skips when Docling or the model files are absent.
# Usage: RAG_STORE_DOCLING_MODELS=/models/docling scripts/validate-ocr.sh
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
command -v python >/dev/null || { echo "python is required" >&2; exit 1; }
cd "$root"
PYTHONPATH=src python -m pytest tests/ocr -q
