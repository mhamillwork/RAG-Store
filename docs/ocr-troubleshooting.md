# OCR troubleshooting

| Symptom | What it means |
|---|---|
| Readiness says artifacts are missing | The model directory is empty or not mounted |
| Job ends `failed` with an empty-extraction message | Nothing searchable was produced and the document was not published |
| `ocr.applied` is null or false on a native PDF | Automatic mode did not claim full-page OCR |
| Tesseract language error | The language pack for that engine code is not in the image |

Worker logs omit document text. The job row's `last_error` is the operational message.
