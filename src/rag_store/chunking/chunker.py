"""Document-aware chunking.

Prose is packed on paragraph and heading boundaries. Table rows stay with their
headers. Values are kept as extracted strings so numbers and units are not
reformatted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from rag_store.chunking.tokenizer import BasicTokenizer
from rag_store.common.checksum import sha256_bytes

_HEADING_LABELS = {"section_header", "title", "page_header"}
_CODE_SPLIT = re.compile(r"(?m)^(def |class |function |func |public |private |protected |package )")


@dataclass
class ChunkDraft:
    sequence: int
    content: str
    lexical_text: str
    page_number: int | None
    section_path: str
    line_start: int | None
    line_end: int | None
    table_index: int | None
    content_checksum: str
    provenance: dict = field(default_factory=dict)


def chunk_document(
    structured: dict,
    *,
    filename: str,
    relative_path: str,
    file_type: str,
    max_tokens: int,
    overlap_tokens: int,
    strategy: str,
    tokenizer=None,
) -> list[ChunkDraft]:
    tokenizer = tokenizer or BasicTokenizer()
    pieces = _pieces(structured, file_type=file_type, strategy=strategy)
    packed = _pack(pieces, max_tokens=max_tokens, overlap_tokens=overlap_tokens, tokenizer=tokenizer)
    drafts: list[ChunkDraft] = []
    for index, piece in enumerate(packed):
        header = _header(filename, relative_path, piece)
        lexical = f"{header}\n{piece['text']}".strip()
        drafts.append(
            ChunkDraft(
                sequence=index,
                content=piece["text"],
                lexical_text=lexical,
                page_number=piece.get("page"),
                section_path=piece.get("section") or "",
                line_start=piece.get("line_start"),
                line_end=piece.get("line_end"),
                table_index=piece.get("table_index"),
                content_checksum=sha256_bytes(piece["text"].encode("utf-8")),
                provenance={
                    "filename": filename,
                    "relative_path": relative_path,
                    "kind": piece.get("kind", "text"),
                    "oversized": piece.get("oversized", False),
                },
            )
        )
    return drafts


def _header(filename: str, relative_path: str, piece: dict) -> str:
    parts = [f"file: {filename}", f"path: {relative_path}"]
    if piece.get("section"):
        parts.append(f"section: {piece['section']}")
    if piece.get("page"):
        parts.append(f"page: {piece['page']}")
    if piece.get("table_index") is not None:
        parts.append(f"table: {piece['table_index']}")
    return "[" + "] [".join(parts) + "]"


def _pieces(structured: dict, *, file_type: str, strategy: str) -> list[dict]:
    tables = []
    for index, table in enumerate(structured.get("tables") or []):
        tables.extend(_table_pieces(table, index))
    texts = structured.get("texts") or []
    if not texts and structured.get("plain_text"):
        texts = [{"text": structured["plain_text"], "label": "text", "prov": []}]
    prose_strategy = strategy
    if strategy == "auto":
        prose_strategy = "code" if file_type in _CODE_TYPES or _looks_like_code(texts) else "heading"
    prose = _prose_pieces(texts, prose_strategy)
    return prose + tables


_CODE_TYPES = {
    "py", "c", "h", "cpp", "hpp", "cc", "java", "js", "ts", "tsx", "jsx", "go", "rs", "rb", "php", "sh", "bash", "sql",
}


def _looks_like_code(texts: list[dict]) -> bool:
    sample = "\n".join(item.get("text", "")[:400] for item in texts[:3])
    return bool(_CODE_SPLIT.search(sample))


def _prose_pieces(texts: list[dict], strategy: str) -> list[dict]:
    pieces: list[dict] = []
    section: list[str] = []
    for item in texts:
        text = (item.get("text") or "").strip()
        if not text:
            continue
        label = (item.get("label") or "text").lower()
        page = _page(item)
        line_start, line_end = _lines(item)
        if label in _HEADING_LABELS or label == "heading":
            level = int(item.get("level") or 1)
            section = section[: max(level - 1, 0)]
            section.append(text)
            pieces.append(
                {
                    "text": text,
                    "kind": "heading",
                    "section": " / ".join(section),
                    "page": page,
                    "line_start": line_start,
                    "line_end": line_end,
                    "break_before": True,
                }
            )
            continue
        blocks = _split_blocks(text, strategy)
        for block in blocks:
            pieces.append(
                {
                    "text": block,
                    "kind": "code" if strategy == "code" else "text",
                    "section": " / ".join(section),
                    "page": page,
                    "line_start": line_start,
                    "line_end": line_end,
                    "break_before": False,
                }
            )
    return pieces


def _split_blocks(text: str, strategy: str) -> list[str]:
    if strategy == "code":
        parts = _CODE_SPLIT.split(text)
        if len(parts) <= 1:
            return [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()] or [text]
        blocks = []
        prefix = parts[0].strip()
        if prefix:
            blocks.append(prefix)
        index = 1
        while index < len(parts) - 1:
            blocks.append((parts[index] + parts[index + 1]).strip())
            index += 2
        return [block for block in blocks if block]
    return [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()] or [text]


def _table_pieces(table: dict, index: int) -> list[dict]:
    headers, rows, caption, page = normalize_table(table)
    section = table.get("section_path") or ""
    pieces = []
    caption_prefix = f"Table {index + 1}"
    if caption:
        caption_prefix += f" ({caption})"
    if not rows and headers:
        rows = [headers]
        headers = [f"column_{position + 1}" for position in range(len(headers))]
    for row in rows:
        pairs = []
        for position, cell in enumerate(row):
            header = headers[position] if position < len(headers) and headers[position] else f"column_{position + 1}"
            pairs.append(f"{header}: {cell}")
        text = caption_prefix + " | " + " | ".join(pairs)
        pieces.append(
            {
                "text": text,
                "kind": "table",
                "section": section,
                "page": page,
                "table_index": index,
                "line_start": None,
                "line_end": None,
                "break_before": True,
            }
        )
    return pieces


def normalize_table(table: dict) -> tuple[list[str], list[list[str]], str, int | None]:
    """Return headers, body rows, caption, and page. Cell text is not parsed as a number."""

    page = table.get("page") or table.get("page_number") or _page(table)
    caption = table.get("caption") or ""
    if not caption:
        captions = table.get("captions") or []
        if captions:
            first = captions[0]
            caption = first.get("text", "") if isinstance(first, dict) else str(first)
    if "headers" in table and "rows" in table:
        headers = ["" if cell is None else str(cell) for cell in table.get("headers") or []]
        rows = [["" if cell is None else str(cell) for cell in row] for row in table.get("rows") or []]
        return headers, rows, str(caption), page
    data = table.get("data") or {}
    cells = data.get("table_cells") or table.get("table_cells") or []
    if not cells:
        return [], [], str(caption), page
    max_row = 0
    max_col = 0
    for cell in cells:
        max_row = max(max_row, int(cell.get("end_row_offset_idx") or (cell.get("start_row_offset_idx") or 0) + 1))
        max_col = max(max_col, int(cell.get("end_col_offset_idx") or (cell.get("start_col_offset_idx") or 0) + 1))
    grid = [["" for _ in range(max_col)] for _ in range(max_row)]
    for cell in cells:
        row = int(cell.get("start_row_offset_idx") or 0)
        col = int(cell.get("start_col_offset_idx") or 0)
        grid[row][col] = "" if cell.get("text") is None else str(cell.get("text"))
    headers = grid[0] if grid else []
    rows = grid[1:] if len(grid) > 1 else []
    return headers, rows, str(caption), page


def _page(item: dict) -> int | None:
    prov = item.get("prov") or []
    if prov and isinstance(prov, list) and isinstance(prov[0], dict):
        number = prov[0].get("page_no") or prov[0].get("page")
        return int(number) if number else None
    return None


def _lines(item: dict) -> tuple[int | None, int | None]:
    prov = item.get("prov") or []
    if prov and isinstance(prov, list) and isinstance(prov[0], dict):
        return prov[0].get("line_start"), prov[0].get("line_end")
    return item.get("line_start"), item.get("line_end")


def _pack(pieces: list[dict], *, max_tokens: int, overlap_tokens: int, tokenizer) -> list[dict]:
    chunks: list[dict] = []
    current: list[dict] = []
    current_tokens = 0

    def flush(*, final: bool = False) -> None:
        nonlocal current, current_tokens
        if not current:
            return
        text = "\n\n".join(part["text"] for part in current).strip()
        if text:
            chunks.append(
                {
                    "text": text,
                    "page": current[0].get("page"),
                    "section": current[-1].get("section") or "",
                    "line_start": current[0].get("line_start"),
                    "line_end": current[-1].get("line_end"),
                    "table_index": current[0].get("table_index") if all(part.get("kind") == "table" for part in current) else None,
                    "kind": current[0].get("kind", "text"),
                    "oversized": any(part.get("oversized") for part in current),
                }
            )
        if not final and overlap_tokens > 0 and current and current[-1].get("kind") != "table":
            tail = current[-1]
            if tokenizer.count(tail["text"]) <= overlap_tokens:
                current = [tail]
                current_tokens = tokenizer.count(tail["text"])
                return
        current = []
        current_tokens = 0

    for piece in pieces:
        if piece.get("kind") == "table":
            flush()
            piece_tokens = tokenizer.count(piece["text"])
            if piece_tokens > max_tokens:
                piece = {**piece, "oversized": True}
            chunks.append(
                {
                    "text": piece["text"],
                    "page": piece.get("page"),
                    "section": piece.get("section") or "",
                    "line_start": None,
                    "line_end": None,
                    "table_index": piece.get("table_index"),
                    "kind": "table",
                    "oversized": piece.get("oversized", False),
                }
            )
            current = []
            current_tokens = 0
            continue
        if piece.get("break_before") and current:
            flush()
        tokens = tokenizer.count(piece["text"])
        if tokens > max_tokens:
            if current:
                flush()
            for part in _split_oversized(piece["text"], max_tokens, tokenizer):
                chunks.append(
                    {
                        "text": part,
                        "page": piece.get("page"),
                        "section": piece.get("section") or "",
                        "line_start": piece.get("line_start"),
                        "line_end": piece.get("line_end"),
                        "table_index": None,
                        "kind": piece.get("kind", "text"),
                        "oversized": False,
                    }
                )
            continue
        if current and current_tokens + tokens > max_tokens:
            flush()
        current.append(piece)
        current_tokens += tokens
    flush(final=True)
    return chunks


def _split_oversized(text: str, max_tokens: int, tokenizer) -> list[str]:
    words = text.split()
    if not words:
        return []
    parts: list[str] = []
    current: list[str] = []
    for word in words:
        trial = " ".join(current + [word])
        if current and tokenizer.count(trial) > max_tokens:
            parts.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        parts.append(" ".join(current))
    return parts
