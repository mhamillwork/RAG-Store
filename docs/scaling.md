# Scaling

HPAs are optional and off for workers by default. KEDA ScaledObjects are optional and must not be combined with an HPA on the same Deployment. The chart render fails closed if both are set.

Raising replica counts does not raise the embedding permit limit. That limit stays at `RAG_STORE_CONCURRENCY__EMBEDDING_GLOBAL_LIMIT`.

Docling and ingestion are not scaled to zero in normal operation. Maintenance mode does scale them to zero on purpose.
