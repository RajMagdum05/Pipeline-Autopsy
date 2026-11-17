---
id: pb_classification_mismatch
title: Check semantic classification against the source
match:
  check_id: semantic.classification
  classification: OUTPUT_CONTRACT_VIOLATION
---
1. Compare the classifier output with the document type and the classifier's declared label set.
2. Check whether OCR quality or document splitting changed the text seen by the classifier.
3. Add a labeled regression example before changing thresholds or prompt instructions.
