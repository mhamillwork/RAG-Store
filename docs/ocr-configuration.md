# OCR

`rapidocr` is the default engine. `tesseract` and `tesseract_cli` are accepted configuration values. Language codes are mapped per engine: English is `en` for RapidOCR and `eng` for Tesseract. Unknown codes are rejected.

Modes are `auto`, `force`, and `native`. `native` is a per-document override. Production cannot set `RAG_STORE_DOCLING__OCR_ENABLED=false`.

No accuracy percentage is published. Run `scripts/validate-ocr.sh` after the models are mounted and record the result.
