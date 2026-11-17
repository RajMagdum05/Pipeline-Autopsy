---
id: pb_rate_limit
title: Reduce provider rate-limit failures
match:
  error_type: ResourceExhausted
  classification: SERVICE_EXECUTION_FAILURE
---
1. Check provider quota and request concurrency around the failing time window.
2. Apply bounded exponential backoff with jitter and honor any retry-after value.
3. Verify retries do not amplify load or duplicate non-idempotent operations.
