---
id: pb_ungrounded_extraction
title: Verify extracted values against source text
match:
  check_id: facts.grounded
  classification: OUTPUT_CONTRACT_VIOLATION
---
1. Open the cited source artifact and compare the extracted value with the quoted evidence.
2. Check field normalization and citation offsets for the affected document format.
3. Add the failure as a regression fixture before changing extraction behavior.
