"""Docling conversion adapter.

Imports of Docling happen inside methods so API processes do not load the
conversion stack. Missing models, missing libraries, and unsupported options
fail visibly. The adapter does not download models or call remote services.
"""

from __future__ import annotations

import os
from pathlib import Path

from rag_store.common.errors import ConfigurationError, Unavailable
from rag_store.config.settings import Settings
from rag_store.docling.config_map import (
    accelerator_values,
    assign_supported,
    ocr_option_values,
    pipeline_values,
    table_values,
)

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}


def configure_runtime(settings: Settings) -> None:
    threads = str(settings.docling.num_threads)
    for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS", "DOCLING_NUM_THREADS"):
        os.environ[name] = threads
    os.environ["DOCLING_DEVICE"] = "cpu"
    os.environ["DOCLING_ARTIFACTS_PATH"] = settings.docling.artifacts_path
    if settings.docling.offline_mode:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.environ["HF_DATASETS_OFFLINE"] = "1"


class DoclingAdapter:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.error: str | None = None
        configure_runtime(settings)

    def validate(self) -> None:
        if not self.settings.docling.enabled:
            raise ConfigurationError("Docling is disabled.")
        if not self.settings.docling.ocr_enabled and self.settings.environment == "production":
            raise ConfigurationError("OCR cannot be disabled in production.")
        if self.settings.docling.allow_model_downloads:
            raise ConfigurationError("Model downloads are disabled.")
        self._import_docling()
        artifacts = Path(self.settings.docling.artifacts_path)
        if not artifacts.is_dir() or not any(artifacts.iterdir()):
            raise ConfigurationError(
                "Docling model artifacts are missing.",
                details={
                    "path": str(artifacts),
                    "action": "Prepare the pinned Docling artifacts on a connected system and mount them at this path.",
                },
            )
        self._build("auto")

    def convert(self, path: Path, *, ocr_mode: str) -> dict:
        try:
            converter = self._build(ocr_mode)
            result = converter.convert(str(path))
        except ConfigurationError:
            raise
        except Exception as exc:
            raise Unavailable(f"Docling conversion failed: {exc.__class__.__name__}: {exc}") from exc
        document = result.document
        exported = document.export_to_dict()
        markdown = document.export_to_markdown()
        plain = document.export_to_text() if hasattr(document, "export_to_text") else markdown
        warnings = [str(item) for item in (getattr(result, "errors", None) or [])]
        pages = getattr(document, "pages", None)
        page_count = len(pages) if isinstance(pages, dict) else None
        forced = ocr_mode == "force" or path.suffix.lower() in IMAGE_SUFFIXES
        version = ""
        try:
            import docling

            version = getattr(docling, "__version__", "")
        except Exception:
            version = ""
        status = "warning" if warnings else "success"
        return {
            "representation": "docling",
            "schema_version": str(exported.get("version") or ""),
            "docling_version": version,
            "content": exported,
            "markdown": markdown,
            "plain_text": plain,
            "page_count": page_count,
            "warnings": warnings,
            "status": status,
            "ocr": {
                "engine": self.settings.docling.ocr_engine,
                "mode": ocr_mode,
                "applied": True if forced else None,
                "languages": self.settings.docling.language_list(),
            },
        }

    def _import_docling(self):
        try:
            import docling  # noqa: F401
            from docling.document_converter import DocumentConverter  # noqa: F401
        except Exception as exc:
            raise ConfigurationError(
                "Docling is not installed in this image.",
                details={"reason": str(exc)},
            ) from exc

    def _build(self, ocr_mode: str):
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import (
            AcceleratorOptions,
            PdfPipelineOptions,
            RapidOcrOptions,
            TableStructureOptions,
        )
        from docling.document_converter import DocumentConverter, ImageFormatOption, PdfFormatOption

        options = PdfPipelineOptions()
        assign_supported(options, pipeline_values(self.settings.docling, ocr_mode=ocr_mode), "PdfPipelineOptions")
        accelerator = AcceleratorOptions()
        assign_supported(accelerator, accelerator_values(self.settings.docling), "AcceleratorOptions")
        if not hasattr(options, "accelerator_options"):
            raise ConfigurationError("This Docling release has no accelerator_options field.")
        options.accelerator_options = accelerator
        tables = TableStructureOptions()
        assign_supported(tables, table_values(self.settings.docling), "TableStructureOptions")
        options.table_structure_options = tables
        ocr_values = ocr_option_values(self.settings.docling, ocr_mode=ocr_mode)
        if self.settings.docling.ocr_engine == "rapidocr":
            ocr = RapidOcrOptions(lang=ocr_values["lang"], backend="onnxruntime")
        elif self.settings.docling.ocr_engine == "tesseract_cli":
            from docling.datamodel.pipeline_options import TesseractCliOcrOptions

            ocr = TesseractCliOcrOptions(lang=ocr_values["lang"])
        else:
            from docling.datamodel.pipeline_options import TesseractOcrOptions

            ocr = TesseractOcrOptions(lang=ocr_values["lang"])
        if not hasattr(ocr, "mode"):
            raise ConfigurationError("This Docling OCR options object has no mode field, so OCR mode cannot be applied.")
        ocr.mode = ocr_values["mode"]
        options.ocr_options = ocr
        formats = {}
        if hasattr(InputFormat, "PDF"):
            formats[InputFormat.PDF] = PdfFormatOption(pipeline_options=options)
        if hasattr(InputFormat, "IMAGE"):
            formats[InputFormat.IMAGE] = ImageFormatOption(pipeline_options=options)
        return DocumentConverter(format_options=formats)
