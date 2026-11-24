# Structured storage

Ordinary Docling JSON is JSONB on `docling_documents`. Markdown and plain text are separate text columns. Tables are rows in `document_tables`. Large JSON is segmented or written to the document volume with a path and checksum stored in PostgreSQL. The code does not truncate JSON to fit a limit.

Page images are not embedded as base64. `generate_page_images` and `generate_picture_images` are off.

Reindex copies the structured rows onto a new version and enqueues chunking only.
