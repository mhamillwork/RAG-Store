# Embeddings and reranking

Embeddings use an OpenAI-compatible `POST {baseUrl}{apiPath}` with the configured model name. The client checks that every returned vector has the configured dimension and that the count matches the batch. Timeouts and HTTP 429 or 5xx responses retry. A failure raises; it does not synthesize a vector.

Cluster-wide permits live in `inference_permits` under an advisory lock. Bulk ingestion can use `global limit - reserved interactive` slots. Interactive search uses the full limit. The defaults are 12 and 4.

Reranking accepts `tei` or `cohere`. If the call fails and fallback is allowed, the original order is returned with `degraded=true` and a reason. Scores are not invented.

Set the real base URL and model in the Helm values. They are empty in the repository on purpose.
