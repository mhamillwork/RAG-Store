# Tables

Docling table structure is enabled with mode `accurate` unless configured otherwise. Table rows become chunks that keep the header next to the cell value as strings. Numbers are not coerced.

The GUI asks `GET /api/v1/documents/{id}/tables` and renders headers and rows as text. Table quality was not measured on engineering documents in this workspace.
