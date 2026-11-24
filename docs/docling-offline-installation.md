# Offline Docling

On a connected machine, with the pinned release installed and `RAG_STORE_ALLOW_MODEL_DOWNLOAD=1`:

```bash
scripts/download-docling-models.sh /tmp/docling-artifacts
scripts/package-docling-models.sh /tmp/docling-artifacts /tmp/docling-artifacts.tar
```

Copy the tar into the isolated network, verify `docling-artifacts.tar.sha256`, and either bake the files into the image or copy them to the model PVC with `scripts/populate-docling-model-pvc.sh`.

Workers read `RAG_STORE_DOCLING__ARTIFACTS_PATH` (default `/models/docling`). An empty directory fails readiness.
