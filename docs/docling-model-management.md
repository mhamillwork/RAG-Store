# Model management

Prefer an immutable image or a read-only PVC. Do not put model weights in the GLOBAL or LOCAL document trees. Do not let replicas download or write the shared model directory.

`scripts/verify-docling-models.sh` checks that the directory contains files. It does not certify OCR accuracy.
