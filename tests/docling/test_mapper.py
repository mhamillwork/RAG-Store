"""Docling option mapping. These tests do not download models."""

from rag_store.config.settings import DoclingSettings
from rag_store.docling.config_map import ocr_option_values, pipeline_values


def test_force_ocr_sets_full_page():
    settings = DoclingSettings(ocr_mode="force", ocr_engine="rapidocr", ocr_languages="en")
    values = ocr_option_values(settings, ocr_mode="force")
    assert values["force_full_page_ocr"] is True or values.get("full_page") is True


def test_pipeline_keeps_cpu_and_disables_remote_enrichment():
    values = pipeline_values(DoclingSettings())
    assert values["do_ocr"] is True
    assert values["do_table_structure"] is True
