# Dropbox ingestion

The scanner holds a PostgreSQL lease named `dropbox-scanner`. Only the holder walks the directories. A file is ingested after its size and mtime stay unchanged for `RAG_STORE_STORAGE__STABILITY_SECONDS`. Symlinks and excluded directories are skipped.

The dropbox file is removed only after the database transaction commits. A crash before commit leaves the dropbox file in place. A published original whose database transaction did not commit keeps a `PENDING_DB` marker. The next scanner pass recreates the document version and conversion job from the manifest after the file checksum matches, and removes the marker only after that database transaction commits. A checksum or identity mismatch leaves the marker in place.

Administrative copy:

```bash
kubectl -n rag-store exec -it <storage-utility-pod> -- /bin/bash
# write into staging, then mv within the same volume
mv /data/global/staging/upload.pdf /data/global/dropbox/technical/upload.pdf
```

Do not give ordinary users `kubectl exec` on a pod that mounts every user's directory.
