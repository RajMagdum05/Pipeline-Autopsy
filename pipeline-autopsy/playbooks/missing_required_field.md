---
id: pb_missing_required_field
title: Restore a required stage output
match:
  check_id: facts.required
  classification: OUTPUT_CONTRACT_VIOLATION
---
1. Inspect the stage input and its declared output schema for the missing field.
2. Confirm that upstream filtering or an optional branch did not remove a required value.
3. Add a contract test for the affected branch before relaxing the schema.
