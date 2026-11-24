# Helmfile

`helm-deploy/helmfile.yaml` installs one release named `rag-store` in namespace `rag-store`. The chart defaults to `../helm-chart`. Set `RAG_STORE_CHART=oci://artifactory.tahaa.local/tahaa-helm-local/rag-store` and `RAG_STORE_CHART_VERSION` to use the internal chart.

`MAINTENANCE_MODE` is passed to `maintenance.enabled`.

```bash
cd helm-deploy
helmfile diff
helmfile apply
```

Helmfile itself was not executed here.
