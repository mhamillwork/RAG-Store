# Helm chart

`helm lint helm-chart` passes. `helm template` was run for the default values, `helm-deploy/rag-store-values.yaml`, maintenance mode, existing claims, an HPA, a KEDA ScaledObject, and a Gateway route. Enabling HPA and KEDA on the same component fails the render.

PVCs use `helm.sh/resource-policy: keep`. Uninstall does not delete them.

The GUI deployment mounts a ConfigMap so `/api/v1/search` reaches the search Service and other `/api` paths reach the file Service. Service names follow the release name.

No container requests `nvidia.com/gpu`.
