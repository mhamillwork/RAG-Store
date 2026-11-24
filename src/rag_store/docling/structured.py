"""Store structured documents without truncation.

Ordinary documents are stored as JSONB. Larger documents are split into ordered
segments that reconstruct the original object. A single value that cannot be split
safely is written through the supplied fallback callback and referenced from
PostgreSQL. Embedded base64 images are replaced with references.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from rag_store.common.checksum import sha256_bytes


@dataclass
class StoredStructure:
    content: dict | None
    segments: list[dict] = field(default_factory=list)
    content_storage: str = "inline"
    content_checksum: str = ""
    fallback_bytes: bytes | None = None
    warnings: list[str] = field(default_factory=list)


def json_bytes(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


def strip_embedded_payloads(value, warnings: list[str] | None = None):
    """Replace data URIs and very large base64-looking strings with references."""

    warnings = warnings if warnings is not None else []

    def walk(node):
        if isinstance(node, dict):
            return {key: walk(item) for key, item in node.items()}
        if isinstance(node, list):
            return [walk(item) for item in node]
        if isinstance(node, str) and (node.startswith("data:image") or (len(node) > 100_000 and _base64ish(node))):
            digest = sha256_bytes(node.encode("utf-8"))
            warnings.append(f"Replaced an embedded binary payload with reference {digest}.")
            return f"rag-store-embedded:{digest}"
        return node

    return walk(value)


def _base64ish(value: str) -> bool:
    sample = value[:200]
    return all(char.isalnum() or char in "+/=\n" for char in sample)


def prepare_structure(document: dict, max_bytes: int) -> StoredStructure:
    warnings: list[str] = []
    cleaned = strip_embedded_payloads(document, warnings)
    raw = json_bytes(cleaned)
    checksum = sha256_bytes(raw)
    if len(raw) <= max_bytes:
        return StoredStructure(content=cleaned, content_storage="inline", content_checksum=checksum, warnings=warnings)
    texts = list(cleaned.get("texts") or [])
    tables = list(cleaned.get("tables") or [])
    skeleton = {key: value for key, value in cleaned.items() if key not in {"texts", "tables"}}
    skeleton["texts"] = []
    skeleton["tables"] = []
    skeleton["rag_store_segmented"] = True
    skeleton_raw = json_bytes(skeleton)
    if len(skeleton_raw) > max_bytes or any(len(json_bytes(item)) > max_bytes for item in texts + tables):
        warnings.append("Structured content is stored on the document volume because it exceeds the PostgreSQL inline limit.")
        return StoredStructure(
            content={"rag_store_segmented": False, "storage": "longhorn_fallback", "checksum": checksum},
            content_storage="longhorn_fallback",
            content_checksum=checksum,
            fallback_bytes=raw,
            warnings=warnings,
        )
    segments: list[dict] = []
    segment_index = 0
    for kind, items in (("texts", texts), ("tables", tables)):
        batch: list = []
        batch_bytes = 2
        for item in items:
            encoded = json_bytes(item)
            if batch and batch_bytes + len(encoded) > max_bytes:
                segments.append({"segment_index": segment_index, "content": {"kind": kind, "items": batch}})
                segment_index += 1
                batch = []
                batch_bytes = 2
            batch.append(item)
            batch_bytes += len(encoded)
        if batch:
            segments.append({"segment_index": segment_index, "content": {"kind": kind, "items": batch}})
            segment_index += 1
    return StoredStructure(
        content=skeleton,
        segments=segments,
        content_storage="segmented",
        content_checksum=checksum,
        warnings=warnings,
    )


def reassemble(content: dict | None, segments: list[dict], fallback: bytes | None = None) -> dict:
    if fallback is not None:
        return json.loads(fallback.decode("utf-8"))
    if not content:
        raise ValueError("Structured content is missing and cannot be reconstructed.")
    if not content.get("rag_store_segmented"):
        return content
    texts: list = []
    tables: list = []
    for segment in sorted(segments, key=lambda item: item["segment_index"]):
        body = segment["content"]
        kind = body.get("kind")
        items = body.get("items") or []
        if kind == "texts":
            texts.extend(items)
        elif kind == "tables":
            tables.extend(items)
        else:
            raise ValueError("A structured segment has an unknown kind.")
    document = {key: value for key, value in content.items() if key != "rag_store_segmented"}
    document["texts"] = texts
    document["tables"] = tables
    return document
