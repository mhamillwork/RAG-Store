# Troubleshooting

| Check | Command or symptom |
|---|---|
| API ready | `GET /readyz` returns 503 when the database is down |
| Docling models | `/readyz` on the Docling pod lists the missing path |
| Job stuck | `last_error` on the job, then `ragctl jobs retry` |
| Search degraded | `degradation_reasons` in the search response |
| Permission denied on GLOBAL write | the caller is not an administrator |
| 404 on a known LOCAL id | the caller is not the owner; this is intentional |
| Upload marker left behind | the scanner clears `PENDING_DB` after the document row exists |

Logs are JSON. Credential fields and document text keys are redacted.
