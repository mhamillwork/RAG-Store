# Processing

Plain text and source code use the lightweight parser. PDF, Office, HTML, and images are routed to Docling. Markdown and CSV use the lightweight parser unless a reprocess request forces another parser.

Empty extraction is not published. `partial_policy=reject` also refuses a partial Docling result. The original file stays on the volume.
