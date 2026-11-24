"""Lightweight extraction for plain text and source code."""

from __future__ import annotations

from rag_store.parsers.router import looks_binary


def parse_text(filename: str, data: bytes, *, max_bytes: int) -> dict:
    if len(data) > max_bytes:
        raise ValueError("The file exceeds the configured maximum size.")
    if looks_binary(data[:8192]):
        raise ValueError("The file looks like a binary and was not parsed as text.")
    text = data.decode("utf-8", errors="replace")
    lines = text.splitlines()
    page_size = 200
    texts = []
    for start in range(0, max(len(lines), 1), page_size):
        block = lines[start : start + page_size]
        texts.append(
            {
                "text": "\n".join(block),
                "label": "text",
                "prov": [{"page_no": (start // page_size) + 1, "line_start": start + 1, "line_end": start + len(block)}],
            }
        )
    return {
        "representation": "rag-store-text",
        "schema_version": "rag-store-text/1",
        "name": filename,
        "texts": texts or [{"text": "", "label": "text", "prov": []}],
        "tables": [],
        "plain_text": text,
        "markdown": text,
        "page_count": max(1, (len(lines) + page_size - 1) // page_size) if lines else 1,
        "warnings": [],
        "ocr": {"engine": "", "applied": False},
    }
