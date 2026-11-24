# ragctl

`ragctl` talks to the file and search URLs. It does not open the database.

```bash
ragctl login
ragctl upload ./technical-docs --scope global --collection technical --recursive
ragctl upload ./my-project --scope local --collection projects --recursive
ragctl collections list
ragctl status
ragctl quota
ragctl jobs list
ragctl jobs retry <job-id>
ragctl documents list --scope local
ragctl documents download <document-id>
ragctl documents delete <document-id>
ragctl documents reindex <document-id>
ragctl documents reprocess <document-id> --ocr-mode force
ragctl documents markdown <document-id>
ragctl documents docling <document-id>
ragctl documents tables <document-id>
ragctl search "How does Cilium multicast work?"
```

Set `RAGCTL_FILES_URL`, `RAGCTL_SEARCH_URL`, and either `RAGCTL_API_KEY` or a token from `ragctl login`. Non-zero HTTP statuses become a non-zero exit code.
