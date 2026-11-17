---
id: pb_ocr_low_quality
title: Low OCR quality on a source document
match:
  check_id: ocr.quality
  classification: OUTPUT_CONTRACT_VIOLATION
  stage: document_processing
---
1. Open the page images for the flagged pages (artifact link in the evidence pane).
2. If the scan is skewed or low-resolution, request resubmission or raise OCR_RETRY_RENDER_DPI.
3. If the text layer is native but garbled, force OCR for that document.
