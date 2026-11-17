---
id: pb_coverage_gap
title: Add an upstream check for rejected input
match:
  check_id: stage_gate
  classification: COVERAGE_GAP
---
1. Identify the first stage that rejected the input and the contract it expected.
2. Add an explicit upstream validation check so the failure is caught before that stage.
3. Verify the rejection is represented as a blocked stage with a useful reason.
