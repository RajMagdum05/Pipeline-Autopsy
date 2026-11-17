---
id: pb_decision_inconsistent
title: Reconcile the final decision with rule results
match:
  check_id: final.matches_rules
  classification: OUTPUT_CONTRACT_VIOLATION
---
1. Compare the final decision inputs with each recorded rule result.
2. Check whether stale state, missing fields, or a fallback branch changed the decision.
3. Add a regression case that asserts the final result follows the rule outcomes.
