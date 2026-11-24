"""Choose Docling or a lightweight parser. Unknown binaries are rejected."""

from __future__ import annotations

from pathlib import Path

from rag_store.common.errors import ValidationFailed

DOCLING_EXTENSIONS = {
    ".pdf", ".docx", ".pptx", ".xlsx", ".html", ".htm", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp",
}
LIGHTWEIGHT_EXTENSIONS = {
    ".txt", ".py", ".c", ".h", ".hh", ".hpp", ".cc", ".cpp", ".java", ".js", ".jsx", ".ts", ".tsx", ".sql",
    ".yaml", ".yml", ".json", ".xml", ".sh", ".bash", ".zsh", ".toml", ".ini", ".cfg", ".conf", ".log",
    ".md", ".markdown", ".csv", ".tsv", ".go", ".rs", ".rb", ".php", ".css", ".scss", ".env", ".tf",
    ".gradle", ".properties", ".service",
}
LIGHTWEIGHT_NAMES = {
    "dockerfile", "containerfile", "makefile", "jenkinsfile", "gemfile", "rakefile", "procfile",
}


def route_for(path: Path, *, forced: str | None = None, extra_docling: set[str] | None = None, extra_light: set[str] | None = None) -> str:
    if forced in {"docling", "lightweight"}:
        return forced
    if forced:
        raise ValidationFailed(f"Parser '{forced}' is not available.")
    name = path.name.lower()
    suffix = path.suffix.lower()
    docling = set(DOCLING_EXTENSIONS) | set(extra_docling or ())
    light = set(LIGHTWEIGHT_EXTENSIONS) | set(extra_light or ())
    if name in LIGHTWEIGHT_NAMES or name.endswith(".dockerfile"):
        return "lightweight"
    if suffix in docling:
        return "docling"
    if suffix in light:
        return "lightweight"
    raise ValidationFailed(
        "The file type is not in the ingestion allowlist.",
        details={"suffix": suffix or "(none)", "filename": path.name},
    )


def looks_binary(sample: bytes) -> bool:
    if b"\x00" in sample:
        return True
    if not sample:
        return False
    text_bytes = sum(32 <= byte <= 126 or byte in {9, 10, 13} for byte in sample)
    return text_bytes / len(sample) < 0.80
