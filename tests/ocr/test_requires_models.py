import pytest

pytest.importorskip("docling")


def test_ocr_quality_requires_local_models():
    pytest.skip(
        "OCR quality is not measured here. Run scripts/validate-ocr.sh on a host that has the pinned Docling artifacts mounted."
    )
