"""OCR language identifiers differ by engine. Unknown codes are rejected."""

from __future__ import annotations

from rag_store.common.errors import ValidationFailed

_RAPID = {
    "en": "en",
    "eng": "en",
    "english": "en",
    "ch": "ch",
    "zh": "ch",
    "chinese": "ch",
    "latin": "latin",
    "cyrillic": "cyrillic",
}

_TESSERACT = {
    "en": "eng",
    "eng": "eng",
    "english": "eng",
    "de": "deu",
    "deu": "deu",
    "german": "deu",
    "fr": "fra",
    "fra": "fra",
    "french": "fra",
    "es": "spa",
    "spa": "spa",
    "spanish": "spa",
}


def map_languages(engine: str, languages: list[str]) -> list[str]:
    if not languages:
        raise ValidationFailed("At least one OCR language is required.")
    table = _RAPID if engine == "rapidocr" else _TESSERACT
    if engine not in {"rapidocr", "tesseract", "tesseract_cli"}:
        raise ValidationFailed(f"OCR engine '{engine}' is not supported.")
    mapped: list[str] = []
    unknown: list[str] = []
    for language in languages:
        key = language.strip().lower()
        if key not in table:
            unknown.append(language)
        elif table[key] not in mapped:
            mapped.append(table[key])
    if unknown:
        raise ValidationFailed(
            "One or more OCR languages are not mapped for the selected engine.",
            details={"engine": engine, "languages": unknown},
        )
    return mapped
