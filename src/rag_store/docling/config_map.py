"""Map RAG Store Docling settings onto the pinned Docling release.

The mapper returns explicit option values. Applying them checks that the installed
Docling objects actually have those attributes, so an unsupported setting fails
instead of being ignored.
"""

from __future__ import annotations

from rag_store.config.settings import DoclingSettings
from rag_store.ocr.languages import map_languages


def pipeline_values(settings: DoclingSettings, *, ocr_mode: str | None = None) -> dict:
    mode = ocr_mode or settings.ocr_mode
    if mode not in {"auto", "force", "native"}:
        raise ValueError(f"Unsupported OCR mode '{mode}'.")
    do_ocr = settings.ocr_enabled and mode != "native"
    if mode == "force":
        do_ocr = True
    return {
        "artifacts_path": settings.artifacts_path or None,
        "enable_remote_services": False if not settings.allow_remote_services else True,
        "do_ocr": do_ocr,
        "do_table_structure": settings.table_structure_enabled,
        "generate_page_images": False,
        "generate_picture_images": False,
        "do_code_enrichment": False,
        "do_formula_enrichment": False,
        "force_backend_text": mode == "native",
        "document_timeout": float(settings.timeout_seconds),
    }


def accelerator_values(settings: DoclingSettings) -> dict:
    if settings.device != "cpu":
        raise ValueError("Docling device must be cpu.")
    return {"num_threads": settings.num_threads, "device": "cpu"}


def table_values(settings: DoclingSettings) -> dict:
    if settings.table_mode not in {"accurate", "fast"}:
        raise ValueError("Table mode must be accurate or fast.")
    return {"mode": settings.table_mode, "do_cell_matching": True}


def ocr_option_values(settings: DoclingSettings, *, ocr_mode: str | None = None) -> dict:
    mode = ocr_mode or settings.ocr_mode
    languages = map_languages(settings.ocr_engine, settings.language_list())
    rapid_mode = "full_page" if mode == "force" or settings.force_full_page_ocr else "default"
    return {
        "engine": settings.ocr_engine,
        "lang": languages,
        "mode": rapid_mode,
        "force_full_page_ocr": mode == "force" or settings.force_full_page_ocr,
        "backend": "onnxruntime" if settings.ocr_engine == "rapidocr" else None,
    }


REQUIRED_PIPELINE_ATTRIBUTES = (
    "artifacts_path",
    "do_ocr",
    "do_table_structure",
    "enable_remote_services",
    "document_timeout",
)


def assign_supported(target, values: dict, label: str) -> None:
    missing = [key for key in values if not hasattr(target, key)]
    if missing:
        raise RuntimeError(f"{label} does not support settings {missing}. Refusing to ignore them.")
    for key, value in values.items():
        if value is None:
            continue
        setattr(target, key, value)
