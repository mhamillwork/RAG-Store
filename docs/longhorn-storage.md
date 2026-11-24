# Longhorn

Production values request two 500Gi ReadWriteMany volumes on `longhorn-ha`, plus an optional 50Gi model volume. Three storage replicas of two 500Gi volumes are about 3Ti before snapshots. Confirm the StorageClass replica count, the eligible nodes, and free space in the Longhorn UI. This chart does not edit the StorageClass.

Indexed text remains searchable while the volume is mounted only by the processes that need files. Download and the scanner fail clearly when the volume is absent.

PVC resources carry `helm.sh/resource-policy: keep`.
